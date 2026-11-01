"""The run a judgment belongs to, on its row (v0.1.64, for INB7-c4b: Progress shows a run's judgments with that
run). Matching rows to runs by conversation and time goes wrong for the after-turn job's memory questions (they
come after the run has ended), for two runs close together, and for a job's job.accomplished.

Where the id comes from, first that counts: the caller's own id (a job's `Job.run_id`), then the binding
`judgment.of_run` made for work that runs after its turn (the after-turn job, project evidence), then the run being
executed (execution_context). Only ints count. The turns and the job here are real; the models are scripted."""
import asyncio
import uuid

import sqlalchemy as sa

from server.services import execution_context, judgment, lessons, personal_context as pc, turn_facts
from tests.server import test_background_jobs as bg
from tests.server.conftest import MockAdapter
from tests.server.test_arslan_loop import settle_after_turn
from tests.server.test_judgment import _Adapter, _rows, judge_with  # noqa: F401  (the fixture)
from tests.server.test_project_evidence import _active, api  # noqa: F401  (the fixture)

fresh, active = bg.fresh, bg.active


async def _a_turn(conversation_id: str, message: str, monkeypatch, **context) -> int:
    """A real chat turn, then its after-turn work. Returns the turn's run id, as its events carry it."""
    from server.orchestrator import arslan, tool_loop
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: MockAdapter(stream_chunks=["ok"], chat_content="ok"))
    events = []
    with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="turn-1", conversation_id=conversation_id, **context)):
        await arslan.handle_user_message(conversation_id, message, events.append)
    await settle_after_turn()
    await asyncio.gather(*list(lessons._background))
    (run_id,) = {e["run_id"] for e in events if "run_id" in e}
    return run_id


async def _no_facts(conversation_id, user_message):
    return []


async def test_a_judgment_names_the_callers_run_then_the_binding_then_the_run_being_executed(execution_db,
                                                                                              judge_with):  # noqa: F811
    judge_with(_Adapter())

    async def run_of(**kw):
        await judgment.judge("memory.worth", {"candidate": "x"}, **kw)
        return (await _rows(execution_db))[-1].run_id
    assert await run_of() is None
    with execution_context.bind_run(7):
        assert await run_of() == 7
        with judgment.of_run(5):
            assert await run_of() == 5
            assert await run_of(run_id=3) == 3
            assert await run_of(run_id="3") == 5             # only ints count
        with judgment.of_run("5"):
            assert await run_of() == 7
    with execution_context.bind_run(uuid.uuid4()):
        assert await run_of() is None


async def test_a_lesson_the_after_turn_job_weighs_names_the_turn_it_came_from(execution_db, judge_with,  # noqa: F811
                                                                             monkeypatch):
    judge_with(_Adapter('{"answer": false, "p": 0.1}'))      # not worth keeping: only the row is left

    async def extract(conversation_id, user_message):        # the user corrected Arslan: a practice, no facts
        turn_facts._practices.set([{"situation": "Asked for a summary", "advice": "Keep it to three lines",
                                    "avoid": False}])
        return []
    monkeypatch.setattr(turn_facts, "extract", extract)
    run_id = await _a_turn("c1", "No, keep summaries to three lines", monkeypatch)
    assert [(r.point, r.run_id) for r in await _rows(execution_db)] == [("memory.worth", run_id)]


async def test_a_jobs_accomplished_judgment_names_the_jobs_run(execution_db, judge_with, active,  # noqa: F811
                                                               monkeypatch):
    from server.orchestrator import arslan
    from server.services import background_jobs
    judge_with(_Adapter('{"answer": true, "p": 0.9}'))

    async def job_body(conversation_id, goal, emit, confirmations):
        emit({"type": "tool_call", "tool": "list_dir", "target": "~"})   # a step, so the job notes its run
        return "Done: listed it"
    monkeypatch.setattr(arslan, "background_body", job_body)
    job = await background_jobs.start("c1", "List my home folder", [], outside_seen=False)
    await bg._wait(lambda: job.task.done(), 15)
    rows = [(r.point, r.run_id, r.ref) for r in await _rows(execution_db)]
    assert isinstance(job.run_id, int) and rows == [("job.accomplished", job.run_id, job.job_id)]


async def test_project_progress_after_a_turn_names_the_turn(api, execution_db, judge_with, monkeypatch):  # noqa: F811
    pid, _ = await _active(api)
    judge_with(_Adapter('{"answer": false, "p": 0.1}'))      # the gate says no: one row, nothing ticked
    monkeypatch.setattr(turn_facts, "extract", _no_facts)
    run_id = await _a_turn("c-pr", "The fun test went great", monkeypatch, project_id=pid)
    assert [(r.point, r.run_id) for r in await _rows(execution_db)] == [("project.progress", run_id)]


async def test_the_judgments_api_gives_every_row_its_run_null_for_one_with_none(client, judge_with):  # noqa: F811
    judge_with(_Adapter())
    with execution_context.bind_run(9):
        await judgment.judge("memory.worth", {"candidate": "x"})
    await judgment.judge("memory.worth", {"candidate": "y"})   # no run, like every row from before v0.1.64
    items = (await client.get("/api/v1/judgments")).json()["items"]
    assert [item["run_id"] for item in items] == [None, 9]


def test_0085_adds_a_null_run_id_and_leaves_the_rows_and_a_new_install_alone():
    from server.db.migrations.versions._0085_judgment_run import upgrade_sync
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        upgrade_sync(conn)                                     # no judgments table yet: nothing to do
        conn.execute(sa.text("CREATE TABLE judgments (id INTEGER PRIMARY KEY, point VARCHAR(40) NOT NULL)"))
        conn.execute(sa.text("INSERT INTO judgments (point) VALUES ('memory.worth')"))
        upgrade_sync(conn)
        upgrade_sync(conn)                                     # idempotent
        assert "run_id" in {c["name"] for c in sa.inspect(conn).get_columns("judgments")}
        assert conn.execute(sa.text("SELECT point, run_id FROM judgments")).all() == [("memory.worth", None)]

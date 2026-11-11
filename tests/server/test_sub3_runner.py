"""SUB3 (v0.1.64, card docs/plans/0164/SUB-sub-sessions.md): starting a sub-session and running it.

No tool table offers `start_sub_session` yet (SUB5 adds it after the M64 bench), so these tests reach the executor
and `sub_sessions.start` directly, and run the sub-session's job for real: its own conversation, the background job
runner, the real `background_body` and tool loop, with a scripted model.

- How many: four children of a commander, two of a sub-session, none below that, six alive in a tree.
- Cards: shown in the parent's conversation, granting for the sub-session only; the parent's grants don't answer.
- Outside content passes down: a brief written after reading a page is framed, and the child's turn is marked.
- A sub-session is offered files, commands, the web and its plan only.
- One tree's spending limit, read before each model request, besides each run's own.
- A phone holding a sub-session's id reads nothing of it.
"""
import asyncio
import json
import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from arslan.execution_budget import charge_usd, model_request
from arslan.execution_checkpoint import save
from arslan.models import LLMResponse
from server.db.companion_models import ConversationContext, Project
from server.db.models import ArslanMessage, PermissionGrant, Run
from server.db.task_models import CompanionTask, TaskAttempt, TaskRevision
from server.orchestrator import arslan as arslan_mod, tool_loop, untrusted
from server.orchestrator.tool_caller import ToolCaller
from server.registry import executors, hands_tools
from server.registry.task_tools import StartSubSessionExecutor
from server.registry.tool_defs import SCHEMAS
from server.registry.tool_defs.tasks import START_SUB_SESSION
from server.services import (agent_browser, approvals, background_jobs, permission_store, permissions,
                             personal_context as pc, phone_reads, project_evidence, run_registry, settings_service,
                             sub_sessions, task_service)
from tests.server.test_s64_0_outside_content_gaps import (  # noqa: F401  (the fixture)
    NETWORK, NOTE, _Page, _Run, memory)

ROOT = "c-commander"
BRIEF = "Draft the outline of the video in outline.md"


_SINKS: list = []


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(sub_sessions, "ended", lambda job, text: None)   # SUB4's summary turn: test_sub4_report
    background_jobs._reset_for_tests()
    approvals._reset_for_tests()
    sub_sessions._reset_for_tests()
    yield
    background_jobs._reset_for_tests()
    approvals._reset_for_tests()
    sub_sessions._reset_for_tests()
    while _SINKS:
        run_registry.detach_sink(*_SINKS.pop())


def _call(name, args):
    return {"id": f"call-{uuid.uuid4().hex[:8]}", "type": "function", "function": {"name": name, "arguments": args}}


def _steps(*steps, final="done"):
    return ([LLMResponse(usage={}, content=None, tool_calls=[_call(name, args)]) for name, args in steps]
            + [LLMResponse(usage={}, content=final, tool_calls=[])])


class _Model:
    """The commander's turn (marker SUB3-HOST) and the sub-session's (its background prompt), each scripted. A
    sub-session's request goes through what a provider does first: count it, save before it (where the tree's limit
    is read), and after it charge its price."""

    def __init__(self, host=(), child=(), price=0.0):
        self.replies = {"host": list(host), "child": list(child)}
        self.requests = {"host": [], "child": []}
        self.price = price

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        side = "child" if "BACKGROUND" in str(system) else "host" if "SUB3-HOST" in str(system) else None
        if side is None:
            return LLMResponse(usage={}, content="ok", tool_calls=[])
        if side == "child":
            model_request(1000)
            await save("before_model")
        self.requests[side].append({"user": user, "history": history, "context": pc.current()})
        replies = self.replies[side]
        reply = replies.pop(0) if replies else LLMResponse(usage={}, content="done", tool_calls=[])
        if side == "child":
            charge_usd(self.price)
        return reply


class _Asker:
    def __init__(self):
        self.frames = []

    async def __call__(self, frame):
        self.frames.append(frame)
        return {"approved": True, "scope": "once", "by": "mac", "call_id": frame["call_id"]}


class _Cards:
    async def __call__(self, command, argv, **kw):
        return True


def _ctx(cid, **kw):
    return pc.TaskMemoryContext(**{"task_id": f"t-{uuid.uuid4()}", "run_id": "r", "conversation_id": cid,
                                   "model_is_local": True, "query": "split the work", **kw})


async def _wait(predicate, seconds=10.0):
    deadline = asyncio.get_running_loop().time() + seconds
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)


@pytest.fixture
def jobs(memory, monkeypatch):  # noqa: F811
    """The sub-session's job runs for real; only the done-judge (another model) is left out."""
    async def reached(job, text):
        return False
    monkeypatch.setattr(background_jobs, "_goal_not_reached", reached)
    monkeypatch.setitem(executors.EXECUTORS, "start_sub_session", StartSubSessionExecutor())
    monkeypatch.setitem(executors.EXECUTORS, "web_extract", _Page())
    return memory


async def _commander_turn(monkeypatch, model, *steps, brief=BRIEF):
    """One chat turn of the commander that ends by starting a sub-session with `brief`; returns the child's job,
    finished."""
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    model.replies["host"] = _steps(*steps, ("start_sub_session", {"brief": brief}))

    async def tools():
        return [{"key": key, "description": "fixture"} for key in ("web_extract", "start_sub_session")]

    async def function(cid, message, emit):
        return await tool_loop.run_native(
            system="SUB3-HOST", user_content=message, history=[], emit=lambda e: None, on_chunk=lambda c: None,
            resolve_tools=tools, confirm_command=_Cards(), conversation_id=cid,
            caller=ToolCaller(actor="host", spawn_id=None, conversation_id=cid))
    with pc.bind(_ctx(ROOT)), permissions.asking_with(_Asker()):
        result = await task_service.run_turn(function, ROOT, "split the work", lambda e: None)
    started = next(t for t in result["tool_trace"] if t["tool"] == "start_sub_session")["result"]
    assert started["ok"] is True, started
    [job] = [j for j in background_jobs._jobs.values() if j.conversation_id == started["sub_session_id"]]
    await _wait(lambda: job.task.done())
    return job


def _answering(cid, scope="once"):
    """Every card shown in `cid` answered yes from a Mac window there, with `scope`. Returns what was shown."""
    shown = []

    def sink(frame):
        shown.append(frame)
        if str(frame.get("type", "")).startswith("propose_"):
            approvals.answer({"type": "confirm_" + frame["type"].removeprefix("propose_"),
                              "call_id": frame["call_id"], "scope": scope})
    run_registry.attach_sink(cid, sink)
    _SINKS.append((cid, sink))
    return shown


def _cards(frames):
    return [f for f in frames if str(f.get("type", "")).startswith("propose_")]


# -- starting one: the executor ----------------------------------------------------------------------------------

async def _start(cid, brief=BRIEF, *, read_outside=False):
    """The executor, called from a turn of `cid` that someone can be asked in."""
    turn = untrusted.track_turn()
    if read_outside:
        untrusted.mark_external()
    try:
        with pc.bind(_ctx(cid)), permissions.asking_with(_Asker()):
            return await StartSubSessionExecutor().execute({"brief": brief})
    finally:
        untrusted.end_turn(turn)


@pytest.fixture
def held(execution_db):
    """Every job waits for a slot that never comes: what is started stays alive (queued)."""
    background_jobs._slots = asyncio.Semaphore(0)
    return execution_db


async def test_it_returns_at_once_with_the_new_sub_session_queued(held):
    got = await _start(ROOT)
    assert (got["ok"], got["status"], got["sub_session_id"].startswith("sub-")) == (True, "queued", True)
    [job] = background_jobs._jobs.values()
    assert (job.conversation_id, job.parent_id, job.phase) == (got["sub_session_id"], ROOT, "queued")
    async with held() as db:
        row = await db.get(ConversationContext, got["sub_session_id"])
        [message] = (await db.scalars(select(ArslanMessage).where(ArslanMessage.conversation_id == row.id))).all()
    assert (row.kind, row.parent_id) == ("sub", ROOT)
    assert (message.role, message.content, message.display_content) == ("user", BRIEF, None)


async def test_a_brief_written_after_reading_outside_content_is_stored_framed(held):
    got = await _start(ROOT, read_outside=True)
    [job] = background_jobs._jobs.values()
    async with held() as db:
        [message] = (await db.scalars(select(ArslanMessage).where(
            ArslanMessage.conversation_id == got["sub_session_id"]))).all()
    assert message.content == untrusted.sub_session_brief(BRIEF) and message.display_content == BRIEF
    assert job.outside_seen is True


async def test_a_commander_starts_four_and_a_sub_session_two(held):
    children = [(await _start(ROOT))["sub_session_id"] for _ in range(4)]
    assert (await _start(ROOT))["error_code"] == "sub_session_children"
    grandchildren = [(await _start(children[0]))["sub_session_id"] for _ in range(2)]
    assert all(grandchildren)
    assert (await _start(children[0]))["error_code"] == "sub_session_children"
    assert (await _start(grandchildren[0]))["error_code"] == "sub_session_depth"


async def test_no_more_than_six_are_alive_in_a_tree_and_the_commanders_own_job_is_not_one(held):
    await background_jobs.start(ROOT, "the commander's own work", [], outside_seen=False)
    children = [(await _start(ROOT))["sub_session_id"] for _ in range(4)]
    assert (await _start(children[0]))["ok"] is True
    last = await _start(children[0])
    assert last["ok"] is True                                   # six alive, the commander's job not counted
    assert (await _start(children[1]))["error_code"] == "sub_session_alive"
    one = next(job for job in background_jobs._jobs.values() if job.conversation_id == last["sub_session_id"])
    one.task.cancel()
    await _wait(lambda: one.phase == "finished")
    assert (await _start(children[1]))["ok"] is True            # alive, not ever started


async def test_two_starts_at_once_cannot_both_pass_the_count(held):
    for _ in range(3):
        await _start(ROOT)
    got = await asyncio.gather(_start(ROOT), _start(ROOT))
    assert sorted(g.get("error_code") or "ok" for g in got) == ["ok", "sub_session_children"]
    async with held() as db:
        assert len(await sub_sessions.children(db, ROOT)) == 4


async def test_a_temporary_conversation_starts_none(held):
    async with held() as db:
        db.add(ConversationContext(id=ROOT, temporary=True))
        await db.commit()
    assert (await _start(ROOT))["error_code"] == "sub_session_from_temporary"
    assert background_jobs._jobs == {}


async def test_it_is_refused_where_nobody_can_be_asked_and_for_bad_arguments(held):
    with pc.bind(_ctx(ROOT)):
        assert (await StartSubSessionExecutor().execute({"brief": BRIEF}))["error_code"] == "sub_session_unavailable"
    with pc.bind(_ctx(ROOT)), permissions.asking_with(_Asker()):
        for args in ({}, {"brief": " "}, {"brief": BRIEF, "tools": ["browser_open"]}, {"brief": "x" * 4001}):
            assert (await StartSubSessionExecutor().execute(args))["error_code"] == "invalid_sub_session_arguments"
    assert background_jobs._jobs == {}


def test_its_schema_is_defined_but_in_no_tool_table():
    """SUB5 adds it to a table once the M64 bench passes; until then no model can reach it."""
    assert tool_loop._schema_problem({"brief": BRIEF}, START_SUB_SESSION.schema) is None
    assert tool_loop._schema_problem({}, START_SUB_SESSION.schema) is not None
    assert START_SUB_SESSION.schema["additionalProperties"] is False
    assert "start_sub_session" not in SCHEMAS and "start_sub_session" not in executors.EXECUTORS
    from tests.server.test_k5_tool_schemas import _walk
    bad: list = []
    _walk(START_SUB_SESSION.schema, "start_sub_session", bad)
    assert bad == []


# -- outside content passes down ---------------------------------------------------------------------------------

@pytest.mark.parametrize("read_page", [True, False], ids=["after-a-page", "clean"])
async def test_a_brief_from_a_turn_that_read_a_page_starts_the_child_as_having_read_it(jobs, monkeypatch, read_page):
    """The consequences, not the mark: a command reaching the network asks first, and Arslan's own note does not
    apply on its own. memory_note is not a sub-session's tool, so it is let in here to see what happens to it."""
    monkeypatch.setattr(sub_sessions, "TOOLS", sub_sessions.TOOLS | {"memory_note"})
    runner = _Run()
    monkeypatch.setitem(executors.EXECUTORS, "run_command", runner)
    shown = _answering(ROOT)
    model = _Model(child=_steps(("memory_note", {"action": "add", "set": "notes", "text": NOTE}),
                                ("run_command", {"command": NETWORK})))
    page = [("web_extract", {"url": "https://example.test/setup"})] if read_page else []
    await _commander_turn(monkeypatch, model, *page)
    async with jobs() as db:
        from server.db.models import MemoryEntry
        statuses = list((await db.scalars(select(MemoryEntry.status))).all())
    # A sub-session never learns (rule 9), so its note never applies, clean or not: the mark can't be seen here.
    assert statuses == [] and '"code": "learning_disabled"' in model.requests["child"][1]["user"]
    assert [f.get("perm_kind") for f in _cards(shown)] == (["network"] if read_page else [])
    assert runner.runs == [(False, False)]
    # The brief reached the model framed as outside content only after the page.
    first = json.dumps(model.requests["child"][0]["user"], ensure_ascii=False)
    at = first.index(BRIEF)
    framed = first.rfind(untrusted.DELIM_OPEN, 0, at) > first.rfind(untrusted.DELIM_CLOSE, 0, at)
    assert framed is read_page


# -- cards -------------------------------------------------------------------------------------------------------

async def test_a_child_asks_in_its_parents_window_and_the_grant_is_the_childs_alone(jobs, monkeypatch):
    runner = _Run()
    monkeypatch.setitem(executors.EXECUTORS, "run_command", runner)
    async with jobs() as db:                               # the commander already allowed the network here
        await permission_store.add_grant(db, ROOT, "", "network", "network:*")
        await db.commit()
    shown = _answering(ROOT, scope="conversation")
    model = _Model(child=_steps(("run_command", {"command": NETWORK}),
                                ("run_command", {"command": "curl -s https://example.test/more.json"})))
    job = await _commander_turn(monkeypatch, model, ("web_extract", {"url": "https://example.test/setup"}))
    child = job.conversation_id
    [card] = _cards(shown)                                 # asked although the parent's grant stands; once
    assert (card["sub_session"], card["perm_kind"], "conversation" in card["options"]) == (True, "network", True)
    assert runner.runs == [(False, False), (False, False)]
    async with jobs() as db:
        grants = {(g.conversation_id, g.kind) for g in (await db.scalars(select(PermissionGrant))).all()}
    assert grants == {(ROOT, "network"), (child, "network")}


async def test_a_card_its_job_asks_itself_grants_the_child_too(memory):  # noqa: F811
    """The command, write and schedule cards are asked on the job's own ladder (JobConfirmations), not the tool loop's."""
    async with memory() as db:
        await permission_store.add_grant(db, ROOT, "", "schedule", "*")
        await db.commit()
    shown = _answering(ROOT, scope="conversation")
    confirmations = approvals.JobConfirmations("c-kid", job_id="job-kid", ask_in=ROOT)
    with permissions.asking_with(confirmations.asker):
        assert await confirmations.schedule("tidy", "every: 3600") is True
        assert await confirmations.schedule("tidy", "every: 3600") is True       # its grant answers the second
    assert [(c["type"], c["sub_session"]) for c in _cards(shown)] == [("propose_schedule", True)]
    async with memory() as db:
        grants = {(g.conversation_id, g.kind) for g in (await db.scalars(select(PermissionGrant))).all()}
    assert grants == {(ROOT, "schedule"), ("c-kid", "schedule")}


async def test_a_childs_card_is_never_shown_in_the_child_and_never_joins_the_parents(memory):  # noqa: F811
    """The parent's own job asks the identical question while the child's card is open: two cards."""
    frame = {"type": "propose_action", "call_id": "c1", "dedupe": "same", "title": "t"}
    in_child, in_root = [], []
    for cid, sink in (("c-kid", in_child.append), (ROOT, in_root.append)):
        run_registry.attach_sink(cid, sink)
        _SINKS.append((cid, sink))
    asking = asyncio.ensure_future(approvals.SubSessionAsker(ROOT, "c-kid")(dict(frame)))
    await _wait(lambda: len(_cards(in_root)) == 1)
    own = asyncio.ensure_future(approvals.BroadcastAsker(ROOT)({**frame, "call_id": "c2"}))
    await _wait(lambda: len(_cards(in_root)) == 2)
    assert [f.get("sub_session") for f in _cards(in_root)] == [True, None] and _cards(in_child) == []
    for card in _cards(in_root):
        approvals.answer({"type": "confirm_action", "call_id": card["call_id"]})
    assert [(await asking)["call_id"], (await own)["call_id"]] == ["c1", "c2"]


async def test_two_children_asking_the_same_get_two_cards_each_granting_only_its_own_child(memory):  # noqa: F811
    """A child's card never joins another child's: one answer must not decide for two conversations. Two children of
    one parent ask the identical schedule at once; the parent shows two cards, and each answer grants its child only."""
    in_root = []
    run_registry.attach_sink(ROOT, in_root.append)
    _SINKS.append((ROOT, in_root.append))
    kids = ("c-kid", "c-kid2")

    async def ask(cid):
        confirmations = approvals.JobConfirmations(cid, job_id=f"job-{cid}", ask_in=ROOT)
        with permissions.asking_with(confirmations.asker):
            return await confirmations.schedule("tidy", "every: 3600")
    asking = [asyncio.ensure_future(ask(cid)) for cid in kids]
    await _wait(lambda: len(_cards(in_root)) == 2)

    async def grants():
        async with memory() as db:
            return {(g.conversation_id, g.kind) for g in (await db.scalars(select(PermissionGrant))).all()}
    first, second = _cards(in_root)
    assert first["sub_session"] is second["sub_session"] is True
    approvals.answer({"type": "confirm_schedule", "call_id": first["call_id"], "scope": "conversation"})
    await _wait(lambda: any(a.done() for a in asking))
    [answered] = [kid for kid, a in zip(kids, asking) if a.done()]
    assert await grants() == {(answered, "schedule")}
    approvals.answer({"type": "confirm_schedule", "call_id": second["call_id"], "scope": "conversation"})
    assert await asyncio.gather(*asking) == [True, True]
    assert await grants() == {(kid, "schedule") for kid in kids}


# -- tools -------------------------------------------------------------------------------------------------------

async def test_a_child_is_offered_files_commands_the_web_and_its_plan_only(jobs, monkeypatch):
    monkeypatch.setattr(agent_browser, "available", lambda: True)
    monkeypatch.setattr(hands_tools, "desktop_available", lambda: True)
    token = background_jobs._inside_job.set("job-x")
    try:
        with pc.bind(_ctx("c-kid")), permissions.asking_with(_Asker()):
            offered = {t["key"] for t in await arslan_mod._sub_session_tools()}
            job_tools = {t["key"] for t in await arslan_mod._background_callable()}
    finally:
        background_jobs._inside_job.reset(token)
    assert offered == sub_sessions.TOOLS & job_tools and {"run_command", "web_search", "write_file"} <= offered
    assert {"browser_open", "browser_click", "desktop_click"} <= job_tools       # what an ordinary job has
    called = []

    class _Browser:
        async def execute(self, args):
            called.append(args)
            return {"ok": True}
    monkeypatch.setitem(executors.EXECUTORS, "browser_open", _Browser())
    model = _Model(child=_steps(("browser_open", {"url": "https://example.test"})))
    await _commander_turn(monkeypatch, model)
    assert called == []                                     # refused before it ran: not this sub-session's tool


async def test_a_child_turn_never_learns_says_nothing_for_the_user_and_cannot_save_for_them(jobs, monkeypatch):
    """A "remember" in the brief is the commander's text, not the user asking."""
    async with jobs() as db:
        db.add(Project(id="p1", name="P"))
        await db.commit()
        db.add(ConversationContext(id=ROOT, project_id="p1"))
        await db.commit()
    turns = []

    def after_turn(project_id, conversation_id, message, *, said: bool):
        turns.append((conversation_id, said))
        return asyncio.sleep(0)
    monkeypatch.setattr(project_evidence, "after_turn", after_turn)
    model = _Model(child=_steps())
    job = await _commander_turn(monkeypatch, model, brief="remember that lunch is at noon")
    ctx = model.requests["child"][0]["context"]
    assert (ctx.no_learning, ctx.sub_session, ctx.explicit_save_digest, ctx.allow_global_save) == (True, True, None,
                                                                                                    False)
    assert [said for cid, said in turns if cid == job.conversation_id] == [False]
    assert job.outcome == "done"


# -- the tree's spending limit -----------------------------------------------------------------------------------

async def _sub(db, parent, child):
    await sub_sessions.create_child(db, parent, child)
    await db.commit()


async def _spent_task(db, cid, usd, *, run_ids=()):
    now, task_id = datetime.utcnow(), f"t-{uuid.uuid4()}"
    for row in (CompanionTask(id=task_id, conversation_id=cid, attempt_id=f"a-{task_id}", privacy={},
                              budget={"spend": {"usd": usd, "usd_cap": 2.0, "unpriced_requests": 0}},
                              phase="succeeded", results=[], created_at=now, updated_at=now),
                TaskRevision(task_id=task_id, revision=1, spec={"instruction": "x", "acceptance": []}),
                TaskAttempt(id=f"a-{task_id}", task_id=task_id, number=1, spec_revision=1, run_ids=list(run_ids))):
        db.add(row)
        await db.flush()
    await db.commit()


async def test_the_spend_is_every_sub_sessions_snapshot_and_finished_runs_no_task_holds(execution_db):
    async with execution_db() as db:
        await _sub(db, ROOT, "c-a")
        await _sub(db, "c-a", "c-a1")
        db.add_all([Run(id=1, conversation_id="c-a", user_message="x", ended_at=datetime.utcnow(),
                        execution_budget={"spend": {"usd": 1.0}}),           # held by the task below
                    Run(id=2, conversation_id="c-a1", user_message="x", ended_at=datetime.utcnow(),
                        execution_budget={"spend": {"usd": 2.0}}),
                    Run(id=3, conversation_id="c-a1", user_message="x", execution_budget={"spend": {"usd": 9.0}})])
        await db.commit()
        await _spent_task(db, "c-a", 1.0, run_ids=[1])
        await _spent_task(db, ROOT, 40.0)                   # the commander's own: not the tree's
        assert await sub_sessions.tree_spend(db, ["c-a", "c-a1"]) == 3.0
    await sub_sessions.check_tree_spend("c-a1")             # $3 of $6
    async with execution_db() as db:
        await _spent_task(db, "c-a1", 3.0)
    with pytest.raises(sub_sessions.TreeLimitReached):
        await sub_sessions.check_tree_spend("c-a1")


async def test_no_per_run_dollar_cap_means_no_tree_limit(execution_db, monkeypatch):
    async def off(db):
        return None
    monkeypatch.setattr(settings_service, "task_usd_cap", off)
    async with execution_db() as db:
        await _sub(db, ROOT, "c-a")
        await _spent_task(db, "c-a", 500.0)
    await sub_sessions.check_tree_spend("c-a")


@pytest.mark.parametrize("cap, before", [(2.0, 5.5), (1.0, 2.5)], ids=["default-$2", "$1"])
async def test_a_sub_session_stops_at_its_trees_limit_before_its_own(jobs, monkeypatch, cap, before):
    """Three times the per-run cap: a sibling spent `before` (read back from its stored snapshot, as after a
    restart); this child pays $0.30 a request, far from its own cap, and its third request would pass the tree's."""
    async def setting(db):
        return cap
    monkeypatch.setattr(settings_service, "task_usd_cap", setting)
    async with jobs() as db:
        await _sub(db, ROOT, "c-sibling")
        await _spent_task(db, "c-sibling", before)
    plan = {"items": [{"text": "outline", "status": "in_progress"}]}
    model = _Model(child=_steps(("update_plan", plan), ("update_plan", plan), ("update_plan", plan)), price=0.3)
    job = await _commander_turn(monkeypatch, model)
    # Told to wrap up first (it plans on regardless here); stopped at the tree's limit only after that.
    assert [_told(r) for r in model.requests["child"]] == [False, True]
    assert (job.outcome, job.budget_stop["scope"], job.budget_stop["limit"]) == ("out_of_budget", "tree",
                                                                                 f"${3 * cap:.2f}")
    async with jobs() as db:
        [note] = (await db.scalars(select(ArslanMessage).where(
            ArslanMessage.conversation_id == job.conversation_id, ArslanMessage.role == "arslan"))).all()
    assert f"${3 * cap:.2f}" in (note.display_content or note.content)


WRAP_UP = "Work budget nearly used"


def _told(request) -> bool:
    return WRAP_UP in json.dumps([request["user"], request["history"]], ensure_ascii=False, default=str)


class _Writes:
    key = "write_file"

    def __init__(self):
        self.written = []

    async def execute(self, args):
        self.written.append(args.get("path"))
        return {"ok": True, "path": args.get("path"), "bytes": len(args.get("content", ""))}


class _UntilToldToWrapUp(_Model):
    """A sub-session that keeps planning (a new item each time) until a request tells it to wrap up; told, it writes
    the outline, then answers."""

    def __init__(self, price):
        super().__init__(price=price)
        self.wrote = False

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        if "BACKGROUND" in str(system):
            told = _told({"user": user, "history": history})
            if self.wrote:
                reply = LLMResponse(usage={}, content="The outline is in outline.md.", tool_calls=[])
            elif told:
                self.wrote = True
                reply = LLMResponse(usage={}, content=None, tool_calls=[_call(
                    "write_file", {"path": "outline.md", "content": "# Outline\n- the hook\n- the demo\n"})])
            else:
                plan = {"items": [{"text": f"outline part {len(self.requests['child'])}", "status": "in_progress"}]}
                reply = LLMResponse(usage={}, content=None, tool_calls=[_call("update_plan", plan)])
            self.replies["child"] = [reply]
        return await super().chat(system, user, history=history, tools=tools, temperature=temperature)


async def test_near_its_trees_limit_a_sub_session_wraps_up_writes_up_and_only_then_stops(jobs, monkeypatch):
    """Completion first, as with the per-run cap: a sibling spent $5.50 of the tree's $6, past where the tree wraps up
    ($4, the limit / HARD_OVER_SOFT). This child pays $0.20 a request; it is told to wrap up from its second request
    (the first one's check is where it learns the tree's spend), writes the outline, answers, and its job is done
    before the tree's hard stop. Before the fix it planned on, was stopped at $6.10 and wrote nothing."""
    writer = _Writes()
    monkeypatch.setitem(executors.EXECUTORS, "write_file", writer)
    _answering(ROOT)
    async with jobs() as db:
        await _sub(db, ROOT, "c-sibling")
        await _spent_task(db, "c-sibling", 5.5)
    model = _UntilToldToWrapUp(price=0.2)
    job = await _commander_turn(monkeypatch, model)
    assert [_told(r) for r in model.requests["child"]] == [False, True, True]
    assert writer.written == ["outline.md"]
    assert (job.outcome, job.budget_stop) == ("done", None)
    async with jobs() as db:
        [result] = (await db.scalars(select(ArslanMessage).where(
            ArslanMessage.conversation_id == job.conversation_id, ArslanMessage.role == "arslan"))).all()
    assert "outline.md" in (result.display_content or result.content)


async def test_the_same_child_with_room_left_in_its_tree_finishes(jobs, monkeypatch):
    async with jobs() as db:
        await _sub(db, ROOT, "c-sibling")
        await _spent_task(db, "c-sibling", 0.5)
        await _spent_task(db, ROOT, 40.0)                   # the commander's own spend never stops a child
    plan = {"items": [{"text": "outline", "status": "in_progress"}]}
    model = _Model(child=_steps(("update_plan", plan), ("update_plan", plan), ("update_plan", plan)), price=0.3)
    job = await _commander_turn(monkeypatch, model)
    assert (job.outcome, len(model.requests["child"])) == ("done", 4)


# -- the phone ---------------------------------------------------------------------------------------------------

async def _family(client, monkeypatch):
    from server.db import session as db_session
    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)
    async with client.db_maker() as db:
        await sub_sessions.create_child(db, ROOT, "sub-kid")
        await db.commit()
        await sub_sessions.create_child(db, "sub-kid", "sub-grandkid")
        await db.commit()
        for i, cid in enumerate((ROOT, "sub-kid", "sub-grandkid"), start=1):
            db.add(ArslanMessage(conversation_id=cid, role="user", content=f"words of {cid}"))
            db.add(Run(id=i, conversation_id=cid, user_message=f"run of {cid}", status="done"))
        await db.commit()


async def test_a_phone_holding_a_sub_sessions_id_reads_nothing_of_it(client, monkeypatch):
    from server.services import artifact_store
    await _family(client, monkeypatch)
    files = {i: artifact_store.store_bytes(i, "notes.md", b"# notes") for i in (1, 2, 3)}
    assert (await client.get(f"/api/v1/phone/conversations/{ROOT}/history")).status_code == 200
    assert (await client.get("/api/v1/phone/runs/1")).json()["conversation_id"] == ROOT
    assert (await client.get("/api/v1/phone/runs/1/files")).status_code == 200
    assert (await client.get(f"/api/v1/phone/files/{files[1]['filename']}")).status_code == 200
    missing = await client.get("/api/v1/phone/runs/99")
    for run_id, cid in ((2, "sub-kid"), (3, "sub-grandkid")):
        history = await client.get(f"/api/v1/phone/conversations/{cid}/history")
        assert (history.status_code, history.json()["detail"]) == (404, "not_found")      # the Bridge links none
        run = await client.get(f"/api/v1/phone/runs/{run_id}")
        assert (run.status_code, run.json()) == (404, missing.json())                    # as a run that isn't there
        assert (await client.get(f"/api/v1/phone/runs/{run_id}/files")).status_code == 404
        got = await client.get(f"/api/v1/phone/files/{files[run_id]['filename']}")
        assert (got.status_code, got.json()["detail"]) == (404, "file_unavailable")


async def test_the_phone_cannot_turn_a_sub_session_into_a_quick_question(client, monkeypatch):
    from server.db import session as db_session
    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)
    phone_made = "phone-12345678-1234-4123-8123-123456789abc"
    async with client.db_maker() as db:
        await sub_sessions.create_child(db, ROOT, phone_made)
        await db.commit()
    got = await client.post(f"/api/v1/phone/conversations/{phone_made}/quick")
    assert (got.status_code, got.json()["detail"]) == (409, "conversation_exists")
    async with client.db_maker() as db:
        row = await db.get(ConversationContext, phone_made)
    assert (row.kind, row.parent_id) == ("sub", ROOT)
    fresh = "phone-12345678-1234-4123-8123-123456789abd"
    assert (await client.post(f"/api/v1/phone/conversations/{fresh}/quick")).status_code == 200


async def test_the_phone_stops_its_own_work_but_not_a_sub_sessions(held):
    child = (await _start(ROOT))["sub_session_id"]
    own = await background_jobs.start(ROOT, "the commander's own work", [], outside_seen=False)
    [kid] = [job for job in background_jobs._jobs.values() if job.conversation_id == child]
    assert phone_reads.stop_task(kid.job_id) is False
    assert phone_reads.stop_task(own.job_id) is True

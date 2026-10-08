"""0.1.56 P4: evidence that moves a project — files, what the user said, runs (§4)."""
import os

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from server import auth
from server.api.companion import router as companion_router
from server.api.projects import router as projects_router
from server.services import judgment, project_evidence, project_plan
from server.services.project_evidence import matches, scan_folder


@pytest.fixture
async def api(execution_db, monkeypatch):
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-evidence-token")
    app = FastAPI()
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(companion_router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                headers={"Authorization": "Bearer synthetic-evidence-token"}) as client:
        yield client


LEVELS = [
    {"name": "Prototype", "band": "shaping", "clear_condition": "Someone plays it start to end",
     "checkpoints": [{"text": "Three levels", "expects": {"kind": "file", "pattern": "levels/*.json", "min": 3}},
                     {"text": "Fun test"}]},
    {"name": "Production", "band": "doing",
     "checkpoints": [{"text": "Store art", "expects": {"kind": "file", "pattern": "store/**/*.png"}}]},
    {"name": "Launch", "band": "done", "checkpoints": []},
]


async def _active(api, folder=None, levels=LEVELS) -> tuple[str, dict]:
    body = {"name": "Sample game", "kind": "general", "template": "game"}
    if folder is not None:
        body["workspace_ref"] = str(folder)
    response = await api.post("/api/v1/projects", json=body)
    assert response.status_code == 201, response.text
    pid = response.json()["id"]
    response = await api.put(f"/api/v1/projects/{pid}/plan", json={"expected_version": 0, "levels": levels})
    assert response.status_code == 200, response.text
    await api.put(f"/api/v1/projects/{pid}/stage", json={"stage": "active"})
    return pid, (await api.get(f"/api/v1/projects/{pid}/plan")).json()


async def _check_files(execution_db, pid) -> int:
    from server.db.models import Project
    async with execution_db() as db:
        n = await project_evidence.check_files(db, await db.get(Project, pid))
        await db.commit()
    return n


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")


# ── the folder scan is bounded ───────────────────────────────────────────────

def test_the_scan_skips_hidden_secret_too_deep_and_symlinks_out(tmp_path):
    root = tmp_path / "proj"
    for rel in ("a.txt", "levels/l1.json", "a/b/c/d/deep4.txt", "a/b/c/d/e/deep5.txt", ".git/HEAD",
                ".env", "id_rsa", "node_modules/x/index.js"):
        _touch(root / rel)
    outside = tmp_path / "outside.txt"
    _touch(outside)
    os.symlink(outside, root / "escape.txt")
    os.symlink(root / "a.txt", root / "inside-link.txt")
    os.symlink(tmp_path, root / "loop")                       # a directory link is never walked
    found = scan_folder(root)
    assert "a.txt" in found and "levels/l1.json" in found and "inside-link.txt" in found
    assert "a/b/c/d/deep4.txt" in found and "a/b/c/d/e/deep5.txt" not in found
    assert not any(p.startswith((".git", "node_modules", "loop")) for p in found)
    assert ".env" not in found and "id_rsa" not in found and "escape.txt" not in found


def test_the_scan_stops_at_the_entry_budget(tmp_path, monkeypatch):
    for i in range(30):
        _touch(tmp_path / f"f{i:02}.txt")
    monkeypatch.setattr(project_evidence, "SCAN_ENTRIES", 10)
    assert len(scan_folder(tmp_path)) == 10


@pytest.mark.parametrize("pattern, expected", [
    ("levels/*.json", ["levels/a.json"]),                         # * stays in one folder
    ("levels/**/*.json", ["levels/a.json", "levels/x/b.json"]),   # ** spans folders (and none)
    ("*.json", ["top.json"]),
    ("./levels/*.json", ["levels/a.json"]),
    ("../levels/*.json", []),
    ("/levels/*.json", []),
    ("Levels/*.json", []),                                        # case-sensitive
])
def test_patterns_are_relative_globs_inside_the_folder(pattern, expected):
    paths = ["top.json", "levels/a.json", "levels/x/b.json", "levels/a.txt"]
    assert matches(pattern, paths) == expected


# ── files tick the current level ─────────────────────────────────────────────

async def test_files_tick_the_current_level_with_progress_until_min(api, execution_db, tmp_path):
    pid, plan = await _active(api, tmp_path)
    level1, level2 = plan["levels"][0], plan["levels"][1]
    assert level1["checkpoints"][0]["expects"] == {"kind": "file", "pattern": "levels/*.json", "min": 3}
    _touch(tmp_path / "levels/one.json")
    _touch(tmp_path / "levels/two.json")
    _touch(tmp_path / "store/shots/a.png")         # level 2's evidence: not looked at yet
    before = (await api.get(f"/api/v1/projects/{pid}/plan")).json()["version"]
    assert await _check_files(execution_db, pid) == 0
    plan = (await api.get(f"/api/v1/projects/{pid}/plan")).json()
    cp = plan["levels"][0]["checkpoints"][0]
    assert cp["state"] == "todo" and cp["progress"] == "2/3"
    assert plan["version"] == before + 1          # the page refetches on a new plan version
    assert await _check_files(execution_db, pid) == 0
    assert (await api.get(f"/api/v1/projects/{pid}/plan")).json()["version"] == before + 1   # unchanged: no bump
    assert plan["levels"][1]["checkpoints"][0]["state"] == "todo"
    _touch(tmp_path / "levels/three.json")
    assert await _check_files(execution_db, pid) == 1
    assert await _check_files(execution_db, pid) == 0                 # ticked once
    cp = (await api.get(f"/api/v1/projects/{pid}/plan")).json()["levels"][0]["checkpoints"][0]
    assert cp["state"] == "done" and cp["done_by"] == "arslan"
    assert cp["evidence"]["kind"] == "file" and cp["evidence"]["count"] == 3
    assert cp["evidence"]["paths"] == ["levels/one.json", "levels/three.json", "levels/two.json"]
    assert level2["checkpoints"][0]["state"] == "todo"


async def test_files_finishing_a_level_propose_it(api, execution_db, tmp_path):
    levels = [{"name": "Draft", "band": "shaping", "checkpoints": [
        {"text": "Outline", "expects": {"kind": "file", "pattern": "outline.md"}}]},
        {"name": "Ship", "band": "done", "checkpoints": []}]
    pid, _ = await _active(api, tmp_path, levels)
    _touch(tmp_path / "outline.md")
    assert await _check_files(execution_db, pid) == 1
    card = (await api.get("/api/v1/projects/board")).json()["cards"][0]
    assert card["proposal"]["level"] == "Draft" and card["current"]["name"] == "Draft"


async def test_the_loop_scans_only_active_unpaused_projects(api, execution_db, tmp_path):
    active_dir, paused_dir, idea_dir = tmp_path / "a", tmp_path / "p", tmp_path / "i"
    for d in (active_dir, paused_dir, idea_dir):
        _touch(d / "levels/1.json")
    one = [{"name": "Go", "band": "shaping", "checkpoints": [
        {"text": "A level", "expects": {"kind": "file", "pattern": "levels/*.json"}}]},
        {"name": "Done", "band": "done", "checkpoints": []}]
    a, _ = await _active(api, active_dir, one)
    p, _ = await _active(api, paused_dir, one)
    await api.put(f"/api/v1/projects/{p}/stage", json={"paused": True})
    response = await api.post("/api/v1/projects", json={"name": "Idea one", "kind": "general",
                                                       "workspace_ref": str(idea_dir)})
    i = response.json()["id"]
    await api.put(f"/api/v1/projects/{i}/plan", json={"expected_version": 0, "levels": one})
    assert await project_evidence.scan_projects() == 1
    for pid, state in ((a, "done"), (p, "todo"), (i, "todo")):
        plan = (await api.get(f"/api/v1/projects/{pid}/plan")).json()
        assert plan["levels"][0]["checkpoints"][0]["state"] == state, pid


def test_expects_min_is_normalised_and_bad_ones_refused():
    clean = project_plan._clean_level({"name": "X", "band": "doing", "checkpoints": [
        {"text": "a", "expects": {"kind": "file", "pattern": " shots/*.png "}},
        {"text": "b", "expects": {"kind": "file", "pattern": "x", "min": 5000}}]})
    assert [cp["expects"] for cp in clean["checkpoints"]] == [
        {"kind": "file", "pattern": "shots/*.png", "min": 1}, {"kind": "file", "pattern": "x", "min": 1000}]
    with pytest.raises(project_plan.PlanError, match="invalid_expects"):
        project_plan._clean_level({"name": "X", "band": "doing", "checkpoints": [
            {"text": "a", "expects": {"kind": "file", "pattern": "x", "min": "many"}}]})


# ── you said (§4.3) ──────────────────────────────────────────────────────────

class _Judge:
    """Answers by point and item text; records every question."""

    def __init__(self, gate=True, items=()):
        self.gate, self.items, self.asked = gate, set(items), []

    async def __call__(self, point, state, *, ref=None, conversation_id=None):
        self.asked.append((point, state.get("item")))
        if point == "project.progress":
            yes = self.gate
        else:
            yes = any(state["item"].startswith(item) for item in self.items)
        if yes is None:
            return None
        return judgment.Verdict(bool(yes), 0.95 if yes else 0.1, len(self.asked))


async def _said(execution_db, pid, message, conversation_id="conv-1"):
    from server.db.models import ArslanMessage
    async with execution_db() as db:
        db.add(ArslanMessage(conversation_id=conversation_id, role="user", content=message))
        await db.commit()
    return await project_evidence.check_said(pid, conversation_id, message)


async def test_a_no_from_the_gate_asks_nothing_more(api, execution_db, monkeypatch):
    pid, _ = await _active(api)
    judge = _Judge(gate=False, items=["Fun test"])
    monkeypatch.setattr(judgment, "judge", judge)
    out = await _said(execution_db, pid, "what should the next level be?")
    assert out == {"asked": True, "ticked": [], "proposed": False}
    assert [p for p, _ in judge.asked] == ["project.progress"]


async def test_the_user_saying_a_checkpoint_is_done_ticks_it_with_a_quote(api, execution_db, monkeypatch):
    pid, plan = await _active(api)
    fun = plan["levels"][0]["checkpoints"][1]
    judge = _Judge(items=["Fun test"])
    monkeypatch.setattr(judgment, "judge", judge)
    long = "The fun test went great, " + "everyone kept playing for ages " * 8
    out = await _said(execution_db, pid, long)
    assert out["ticked"] == [fun["id"]] and out["proposed"] is False
    # The gate, then each open checkpoint, then the condition.
    assert [item for _, item in judge.asked] == [None, "Three levels", "Fun test",
                                                 "Prototype: Someone plays it start to end"]
    cp = (await api.get(f"/api/v1/projects/{pid}/plan")).json()["levels"][0]["checkpoints"][1]
    ev = cp["evidence"]
    assert cp["done_by"] == "arslan" and ev["kind"] == "said" and ev["conversation_id"] == "conv-1"
    assert len(ev["quote"]) == project_evidence.QUOTE_CHARS and ev["quote"].endswith("…")
    assert isinstance(ev["message_id"], int)


async def test_the_user_saying_the_condition_is_met_proposes_never_advances(api, execution_db, monkeypatch):
    pid, _ = await _active(api)
    monkeypatch.setattr(judgment, "judge", _Judge(items=["Prototype:"]))
    out = await _said(execution_db, pid, "my friend played it start to end, this level is done")
    assert out["proposed"] is True and out["ticked"] == []
    card = (await api.get("/api/v1/projects/board")).json()["cards"][0]
    assert card["proposal"]["evidence"]["kind"] == "said" and card["current"]["name"] == "Prototype"


async def test_a_plan_that_moved_while_the_judge_thought_is_left_alone(api, execution_db, monkeypatch):
    pid, _ = await _active(api)
    judge = _Judge(items=["Fun test"])

    async def slow(point, state, **kw):
        if point == "project.progress.item" and state["item"] == "Fun test":
            await api.post(f"/api/v1/projects/{pid}/advance")          # the user clears it meanwhile
        return await judge(point, state, **kw)
    monkeypatch.setattr(judgment, "judge", slow)
    assert (await _said(execution_db, pid, "fun test done"))["ticked"] == []
    plan = (await api.get(f"/api/v1/projects/{pid}/plan")).json()
    assert plan["levels"][0]["state"] == "cleared"
    assert all(cp["state"] == "todo" for cp in plan["levels"][0]["checkpoints"])


async def test_no_judge_means_nothing_happens(api, execution_db, monkeypatch):
    pid, _ = await _active(api)
    monkeypatch.setattr(judgment, "judge", _Judge(gate=None))
    assert (await _said(execution_db, pid, "done!"))["ticked"] == []
    plan = (await api.get(f"/api/v1/projects/{pid}/plan")).json()
    assert all(cp["state"] == "todo" for cp in plan["levels"][0]["checkpoints"])


async def test_said_is_not_asked_for_a_project_not_moving(api, execution_db, monkeypatch):
    judge = _Judge(items=["Fun test"])
    monkeypatch.setattr(judgment, "judge", judge)
    pid, _ = await _active(api)
    await api.put(f"/api/v1/projects/{pid}/stage", json={"paused": True})
    assert (await _said(execution_db, pid, "fun test done"))["asked"] is False
    response = await api.post("/api/v1/projects", json={"name": "Just an idea", "kind": "general"})
    assert (await _said(execution_db, response.json()["id"], "fun test done"))["asked"] is False
    assert judge.asked == []


async def test_the_real_judge_sends_only_the_declared_fields(api, execution_db, monkeypatch):
    """The points exist, are active, and the ledger rows carry the minimal state."""
    pid, _ = await _active(api)

    class Reply:
        content = '{"answer": true, "p": 0.97}'

    class Adapter:
        model = "stub-router"

        async def chat(self, **_kw):
            return Reply()

    async def adapter():
        return Adapter()
    monkeypatch.setattr(judgment, "_adapter", adapter)
    out = await _said(execution_db, pid, "fun test done and three levels are in")
    assert out["asked"] and len(out["ticked"]) == 2 and out["proposed"] is False   # level done → proposal
    from server.db.models import Judgment
    async with execution_db() as db:
        rows = (await db.execute(select(Judgment).order_by(Judgment.id))).scalars().all()
    assert [r.point for r in rows] == ["project.progress"] + ["project.progress.item"] * 3
    assert set(rows[0].state) == {"level", "condition", "open_checkpoints", "user_message"}
    assert set(rows[1].state) == {"item", "user_message"} and rows[0].mode == "active"
    card = (await api.get("/api/v1/projects/board")).json()["cards"][0]
    assert card["proposal"]["evidence"]["kind"] == "checkpoints"


# ── runs (§4.4) ──────────────────────────────────────────────────────────────

async def _conversation(api, pid, conversation_id):
    response = await api.put(f"/api/v1/conversations/{conversation_id}/context", json={
        "expected_version": 0, "project_id": pid, "no_memory": False, "no_learning": False, "temporary": False,
        "cloud_memory_allowed": False, "allow_sensitive": False})
    assert response.status_code == 200, response.text


async def test_a_handed_off_checkpoint_is_ticked_by_a_done_job_only(api, execution_db):
    pid, plan = await _active(api)
    fun = plan["levels"][0]["checkpoints"][1]["id"]
    await _conversation(api, pid, "thread-h1")
    response = await api.post(f"/api/v1/projects/{pid}/handoff",
                              json={"checkpoint_id": fun, "conversation_id": "thread-h1"})
    assert response.status_code == 200, response.text
    assert await project_evidence.job_finished("thread-h1", "job-1", "Run the fun test", "partial") == []
    assert await project_evidence.job_finished("thread-other", "job-2", "Something else", "done") == []
    await _conversation(api, pid, "thread-sibling")          # same project, nothing handed to it
    assert await project_evidence.job_finished("thread-sibling", "job-4", "Something else", "done") == []
    assert await project_evidence.job_finished("thread-h1", "job-3", "Run the fun test", "done") == [fun]
    cp = (await api.get(f"/api/v1/projects/{pid}/plan")).json()["levels"][0]["checkpoints"][1]
    assert cp["state"] == "done" and cp["evidence"] == {
        "kind": "run", "job_id": "job-3", "goal": "Run the fun test", "conversation_id": "thread-h1"}


async def test_a_handoff_needs_the_conversation_in_the_project(api):
    pid, plan = await _active(api)
    fun = plan["levels"][0]["checkpoints"][1]["id"]
    response = await api.post(f"/api/v1/projects/{pid}/handoff",
                              json={"checkpoint_id": fun, "conversation_id": "thread-elsewhere"})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "conversation_not_in_project"
    await _conversation(api, pid, "thread-h2")
    response = await api.post(f"/api/v1/projects/{pid}/handoff",
                              json={"checkpoint_id": "nope", "conversation_id": "thread-h2"})
    assert response.status_code == 404


async def test_a_finished_job_reports_to_its_project(monkeypatch):
    from server.services import background_jobs
    seen = []

    async def execute(job):
        return "all done", "succeeded", None

    async def nothing(*_a, **_k):
        return False

    async def finished(conversation_id, job_id, goal, outcome):
        seen.append((conversation_id, job_id, goal, outcome))
    monkeypatch.setattr(background_jobs, "_execute", execute)
    monkeypatch.setattr(background_jobs, "_goal_not_reached", nothing)
    monkeypatch.setattr(background_jobs, "_report", nothing)
    monkeypatch.setattr(background_jobs, "_emit", lambda job: None)
    monkeypatch.setattr(project_evidence, "job_finished", finished)
    job = background_jobs.Job(job_id="job-x", conversation_id="thread-x", goal="Make it", acceptance=[])
    await background_jobs._run(job)
    assert seen == [("thread-x", "job-x", "Make it", "done")]


# ── after a turn ─────────────────────────────────────────────────────────────

async def test_a_project_turn_looks_for_evidence_after_answering(api, execution_db, monkeypatch):
    """After the answer (not before), with `said` only for the user's own turn."""
    pev, _ = await _active(api)
    from server.services import background_jobs, lessons, task_service
    from server.services import personal_context as pc
    order, scheduled = [], []

    async def launch(value, emit, body, **_kw):
        order.append("answer")
        return "answer"

    async def after(project_id, conversation_id, message, *, said):
        order.append(("evidence", project_id, conversation_id, message, said))
    monkeypatch.setattr(task_service, "_launch", launch)
    monkeypatch.setattr(project_evidence, "after_turn", after)
    monkeypatch.setattr(lessons, "later", lambda coro: scheduled.append(coro))

    async def note(_pid):
        return None
    monkeypatch.setattr(task_service, "_note_project_activity", note)
    ctx = pc.TaskMemoryContext(task_id="t-ev1", run_id="turn-t-ev1", conversation_id="c-ev", model_is_local=True,
                               project_id=pev)
    with pc.bind(ctx):
        assert await task_service.run_turn(lambda *a, **k: None, "c-ev", "fun test done", None) == "answer"
    assert order == ["answer"] and len(scheduled) == 1
    await scheduled.pop()
    assert order[-1] == ("evidence", pev, "c-ev", "fun test done", True)
    token = background_jobs._inside_job.set("job-ev")
    try:
        ctx2 = pc.TaskMemoryContext(task_id="t-ev2", run_id="turn-t-ev2", conversation_id="c-ev2",
                                    model_is_local=True, project_id=pev)
        with pc.bind(ctx2):
            await task_service.run_turn(lambda *a, **k: None, "c-ev2", "the job goal", None)
    finally:
        background_jobs._inside_job.reset(token)
    await scheduled.pop()
    assert order[-1][-1] is False
    plain = pc.TaskMemoryContext(task_id="t-ev3", run_id="turn-t-ev3", conversation_id="c-pl", model_is_local=True)
    with pc.bind(plain):
        await task_service.run_turn(lambda *a, **k: None, "c-pl", "hello", None)
    assert scheduled == []


async def test_evidence_after_a_turn_never_raises(api, execution_db, monkeypatch):
    pid, _ = await _active(api)

    async def broken(*_a, **_k):
        raise RuntimeError("judge exploded")
    monkeypatch.setattr(project_evidence, "check_said", broken)
    await project_evidence.after_turn(pid, "c1", "done", said=True)


async def test_ticks_and_proposals_never_reach_the_inbox(api, execution_db, monkeypatch, tmp_path):
    from server.db.models import ProactiveItem
    pid, _ = await _active(api, tmp_path)
    monkeypatch.setattr(judgment, "judge", _Judge(items=["Fun test", "Prototype:"]))
    for name in ("a", "b", "c"):
        _touch(tmp_path / f"levels/{name}.json")
    await project_evidence.after_turn(pid, "conv-1", "fun test done, level cleared", said=True)
    async with execution_db() as db:
        assert await db.scalar(select(func.count()).select_from(ProactiveItem)) == 0
    card = (await api.get("/api/v1/projects/board")).json()["cards"][0]
    assert card["proposal"] is not None

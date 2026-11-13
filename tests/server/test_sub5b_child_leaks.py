"""SUB5b (v0.1.64, card docs/plans/0164/SUB-sub-sessions.md, SUB5 points 3, 8 and 9): where a sub-session still showed
or ran where it shouldn't.

These tests make sub-sessions with `sub_sessions.create_child` or
`sub_sessions.start` and run the rest for real: the Inbox's accept route, the background job runner with
`background_body` and the tool loop (a scripted model), the chat entry, the island and status endpoints, `/runs`,
`/tasks` and the socket's turn lock.

1. An accepted Inbox follow-up for a sub-session's job runs as the sub-session's job: its tools only, its cards in its
   parent's window, the tree's spend, its report going up. An ordinary conversation's follow-up is unchanged.
2. Whole-app summaries (the island, notifications, the waiting badge) count a sub-session's
   work once, as its commander's; the whole app's `/runs` and `/tasks` leave it out, its own conversation's keep it.
3. A brief framed as outside content marks the sub-session's later typed turns, and a summary folding it in.
4. A message typed in a sub-session waits for its background turn.
"""
import asyncio
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from arslan.execution_budget import model_request
from arslan.execution_checkpoint import save
from arslan.models import LLMResponse
from server.db.companion_models import ConversationContext, Project
from arslan.companion.contracts import TaskSpec
from server.db.models import ArslanMessage, ProactiveItem, Run
from server.services.task_repository import repository
from server.orchestrator import tool_loop, untrusted
from server.registry import executors
from server.services import (agent_browser, approvals, background_jobs, desktop_status, proactive_service, progress,
                             run_registry, sub_sessions, task_context)
import tests.server.test_s64_0b_attachments_and_job_results as s64b
from tests.server.test_s64_0_outside_content_gaps import NETWORK, POISON, _Run, memory  # noqa: F401  (the fixture)
from tests.server.test_s64_0b_attachments_and_job_results import COMMAND, NOTE_ADD, _turn, chat  # noqa: F401
from tests.server.test_run_command_confirm_flow import _collect_until, app_client  # noqa: F401  (the fixture)
from tests.server.test_sub3_runner import _RefusedRun

ROOT, KID, KID2 = "c-commander", "sub-kid", "sub-kid2"
GOAL = "Continue the outline the sub-session left unfinished"
BRIEF = "Draft the outline of the video in outline.md"

_SINKS: list = []


@pytest.fixture(autouse=True)
def _fresh():
    for module in (background_jobs, approvals, sub_sessions, desktop_status):
        module._reset_for_tests()
    yield
    for module in (background_jobs, approvals, sub_sessions, desktop_status):
        module._reset_for_tests()
    while _SINKS:
        run_registry.detach_sink(*_SINKS.pop())


async def _wait(predicate, seconds=10.0):
    deadline = asyncio.get_running_loop().time() + seconds
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)


def _sink(cid):
    """What `cid`'s windows are shown; every card answered yes, this time."""
    shown = []

    def sink(frame):
        shown.append(frame)
        if str(frame.get("type", "")).startswith("propose_"):
            approvals.answer({"type": "confirm_" + frame["type"].removeprefix("propose_"), "call_id": frame["call_id"],
                              "scope": "once"})
    run_registry.attach_sink(cid, sink)
    _SINKS.append((cid, sink))
    return shown


def _cards(frames):
    return [f for f in frames if str(f.get("type", "")).startswith("propose_")]


async def _family(db, *kids, parent=ROOT):
    for kid in kids:
        await sub_sessions.create_child(db, parent, kid)
        await db.commit()


@pytest.fixture
async def api(memory, monkeypatch):  # noqa: F811
    """The app's routes over the test database. Real jobs; only the done-judge (another model) is left out."""
    from server.db.session import get_session
    from server.main import create_app

    async def reached(job, text):
        return False

    async def configured():
        return True
    monkeypatch.setattr(background_jobs, "_goal_not_reached", reached)
    monkeypatch.setattr(proactive_service, "model_configured", configured)
    app = create_app()

    async def session():
        async with memory() as db:
            yield db
    app.dependency_overrides[get_session] = session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.db = memory
        yield client


# -- 1. the Inbox's follow-up for a sub-session's job --------------------------------------------------------------

class _JobModel:
    """A background job's requests, scripted, with the tools each one offered; anything else (a judge) answers ok."""

    def __init__(self, *steps):
        self.replies = [LLMResponse(usage={}, content=None, tool_calls=[
            {"id": f"call-{n}", "type": "function", "function": {"name": name, "arguments": args}}])
            for n, (name, args) in enumerate(steps)] + [LLMResponse(usage={}, content="Outline finished.",
                                                                     tool_calls=[])]
        self.offered: list[set] = []

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        if "BACKGROUND" not in str(system):
            return LLMResponse(usage={}, content="ok", tool_calls=[])
        model_request(1000)             # what a provider does first: count it, save before it (the tree is read there)
        await save("before_model")
        self.offered.append({t["function"]["name"] for t in tools or []})
        return self.replies.pop(0) if self.replies else LLMResponse(usage={}, content="done", tool_calls=[])


class _Browser:
    def __init__(self):
        self.opened = []

    async def execute(self, args):
        self.opened.append(args.get("url"))
        return {"ok": True, "url": args.get("url")}


@pytest.fixture
def follow_up(api, monkeypatch):
    """Accept a `job_followup` for `cid` through the Inbox's route; returns the job, finished, and what happened."""
    seen = {"runner": _Run(), "browser": _Browser(), "tree": [], "reported": []}
    monkeypatch.setitem(executors.EXECUTORS, "run_command", seen["runner"])
    monkeypatch.setitem(executors.EXECUTORS, "browser_open", seen["browser"])
    monkeypatch.setattr(agent_browser, "available", lambda: True)
    checked = sub_sessions.check_tree_spend

    async def tree(cid):
        seen["tree"].append(cid)
        return await checked(cid)
    monkeypatch.setattr(sub_sessions, "check_tree_spend", tree)
    monkeypatch.setattr(sub_sessions, "ended", lambda job, text: seen["reported"].append((job.conversation_id,
                                                                                         job.parent_id)))

    async def accept(cid):
        model = _JobModel(("browser_open", {"url": "https://example.test/cover"}), ("run_command", {"command": NETWORK}))
        monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
        async with api.db() as db:
            item = ProactiveItem(kind="job_followup", fingerprint=f"job:t-{cid}", source_key=f"job:t-{cid}",
                                 title_key="title.job_followup", evidence=[{"key": "job.goal"}], goal=GOAL,
                                 status="new", conversation_id=cid, created_at=datetime.utcnow())
            db.add(item)
            await db.commit()
            item_id = item.id
        got = await api.post(f"/api/v1/proactive/items/{item_id}/accept", json={})
        assert got.status_code == 200, got.text
        assert got.json()["conversation_id"] == cid
        job = background_jobs._jobs[got.json()["job_id"]]
        await _wait(lambda: job.task.done())
        return job, model, seen
    return accept


@pytest.mark.usefixtures("s2a1_network_rule")          # NET-a: S2a-1's network card as the probe, its switch off
async def test_an_accepted_follow_up_for_a_sub_sessions_job_runs_as_the_sub_sessions(api, follow_up):
    async with api.db() as db:
        await _family(db, KID)
    in_root, in_kid = _sink(ROOT), _sink(KID)
    job, model, seen = await follow_up(KID)
    assert (job.parent_id, job.commander) == (ROOT, ROOT)
    # Its tools only: the browser is neither offered nor run.
    assert model.offered and all(offered <= sub_sessions.TOOLS for offered in model.offered)
    assert seen["browser"].opened == []
    # Its card in its parent's window, marked as the sub-session's; none in its own.
    assert [(c["perm_kind"], c.get("sub_session")) for c in _cards(in_root)] == [("network", True)]
    assert _cards(in_kid) == [] and seen["runner"].runs == [(False, False)]
    # The tree's spend is read before its requests, and its report goes up to its parent.
    assert KID in seen["tree"] and seen["reported"] == [(KID, ROOT)]
    # Its result and its spoken line stay in its own conversation; the whole app hears nothing of its end.
    assert [f["type"] for f in in_root if f.get("type") in {"message", "job_spoken"}] == []
    assert {"message", "job_spoken"} <= {f.get("type") for f in in_kid}
    assert [e for e in desktop_status.snapshot()["events"] if e["kind"] == "turn_finished"] == []


@pytest.mark.usefixtures("s2a1_network_rule")          # NET-a: S2a-1's network card as the probe, its switch off
async def test_an_ordinary_conversations_follow_up_is_unchanged(api, follow_up):
    """The counterpart: the job's own toolset (the browser runs), its card in its own conversation, its end told."""
    in_conversation = _sink("c-plain")
    job, model, seen = await follow_up("c-plain")
    assert (job.parent_id, job.commander) == (None, None)
    assert seen["browser"].opened == ["https://example.test/cover"]
    assert [(c["perm_kind"], c.get("sub_session")) for c in _cards(in_conversation)] == [("network", None)]
    assert seen["tree"] == [] and seen["reported"] == []
    assert [e["conversation_id"] for e in desktop_status.snapshot()["events"]
            if e["kind"] == "turn_finished"] == ["c-plain"]


async def test_a_sub_sessions_follow_up_asks_its_card_for_a_refused_site_in_its_parents_window(api, follow_up,
                                                                                              monkeypatch):
    """NET-a, its switch on: the card after the proxy refused a site its command reached is asked as the sub-session's,
    in its parent's window, and none in its own."""
    async with api.db() as db:
        await _family(db, KID)
    in_root, in_kid = _sink(ROOT), _sink(KID)
    monkeypatch.setitem(executors.EXECUTORS, "run_command", _RefusedRun())
    await follow_up(KID)
    assert [(c["perm_kind"], c.get("sub_session")) for c in _cards(in_root)] == [("network", True)]
    assert _cards(in_kid) == []


async def test_an_ordinary_conversations_follow_up_asks_its_card_for_a_refused_site_in_its_own_window(api, follow_up,
                                                                                                    monkeypatch):
    """NET-a, its switch on: the counterpart, its card in its own conversation."""
    in_conversation = _sink("c-plain")
    monkeypatch.setitem(executors.EXECUTORS, "run_command", _RefusedRun())
    await follow_up("c-plain")
    assert [(c["perm_kind"], c.get("sub_session")) for c in _cards(in_conversation)] == [("network", None)]


async def test_a_sub_session_whose_parent_cant_be_named_starts_no_job(memory):  # noqa: F811
    async with memory() as db:
        db.add(ConversationContext(id=KID, kind="sub", parent_id=None))
        await db.commit()
    with pytest.raises(sub_sessions.SubSessionError, match="sub_session_parent_missing"):
        await background_jobs.start(KID, GOAL, [], outside_seen=True)
    assert background_jobs._jobs == {}


async def _row_gone_or_deleted(db, how):
    """KID made by `create_child`, then its row removed (`row-gone`) or left a tombstone after a restart forgot the
    process's mark (`tombstone`)."""
    await _family(db, KID)
    if how == "row-gone":
        await db.delete(await db.get(ConversationContext, KID))
    else:
        await sub_sessions.tombstone(db, [KID])
    await db.commit()
    sub_sessions._deleted.clear()


REFUSED = {"row-gone": "sub_session_parent_missing", "tombstone": "conversation_deleted"}


@pytest.mark.parametrize("how", ["row-gone", "tombstone"])
async def test_a_follow_up_for_a_sub_session_with_no_row_or_a_tombstone_is_refused_not_run_as_ordinary(
        api, follow_up, how):
    """Its job would otherwise run as an ordinary conversation's: memory and learning on, the browser, its card in its
    own window, no tree check and no report up. The Inbox's accept refuses it before claiming the item."""
    async with api.db() as db:
        db.add(ConversationContext(id=ROOT, no_memory=True))
        await db.commit()
        await _row_gone_or_deleted(db, how)
        item = ProactiveItem(kind="job_followup", fingerprint="job:gone", source_key="job:gone",
                             title_key="title.job_followup", evidence=[{"key": "job.goal"}], goal=GOAL, status="new",
                             conversation_id=KID, created_at=datetime.utcnow())
        db.add(item)
        await db.commit()
    in_kid = _sink(KID)
    got = await api.post(f"/api/v1/proactive/items/{item.id}/accept", json={})
    assert got.status_code == 422 and got.json()["detail"] == {"code": REFUSED[how]}
    async with api.db() as db:
        assert (await db.get(ProactiveItem, item.id)).status == "new"
    assert background_jobs._jobs == {} and in_kid == []


@pytest.mark.parametrize("how", ["row-gone", "tombstone"])
async def test_no_caller_starts_a_job_in_a_sub_session_with_no_row_or_a_tombstone(memory, how):  # noqa: F811
    """`placement` itself refuses, whoever starts the job (a typed turn's background work, the phone, a summary)."""
    async with memory() as db:
        await _row_gone_or_deleted(db, how)
    with pytest.raises(sub_sessions.SubSessionError, match=REFUSED[how]):
        await background_jobs.start(KID, GOAL, [], outside_seen=True)
    assert background_jobs._jobs == {}


async def test_an_id_that_only_looks_like_a_sub_session_by_its_row_is_ordinary(memory):  # noqa: F811
    """The counterparts: a sub-session a delete's keep promoted (a `chat` row, its `sub-` id kept), and an ordinary
    conversation with no row yet, run as ordinary."""
    async with memory() as db:
        db.add(ConversationContext(id="sub-promoted", kind="chat"))
        await db.commit()
    for cid in ("sub-promoted", "thread-new"):
        assert await sub_sessions.placement(cid) == (None, None)


async def test_a_summary_waits_for_a_follow_up_started_after_a_restart(memory):  # noqa: F811
    """A restart forgets which sub-session is whose; a job started in one is its parent's work again (`_at_work`), so
    the parent's summary doesn't sum up while it runs."""
    async with memory() as db:
        await _family(db, KID, KID2)
    sub_sessions._parents.clear()                     # a restart
    background_jobs._slots = asyncio.Semaphore(0)
    try:
        job = await background_jobs.start(KID, GOAL, [], outside_seen=True)
        assert sub_sessions._at_work(ROOT)
    finally:
        job.task.cancel()
        await asyncio.wait({job.task})
        background_jobs._slots = None


async def test_a_card_under_the_commander_wins_over_its_own_reminder(memory, monkeypatch):  # noqa: F811
    async with memory() as db:
        await _family(db, KID)
        db.add(ArslanMessage(conversation_id=ROOT, role="user", content="words"))
        db.add(ProactiveItem(kind="job_followup", fingerprint="job:r", source_key="job:r", title_key="t",
                             evidence=[], goal="again", status="new", conversation_id=ROOT,
                             created_at=datetime.utcnow()))
        await db.commit()
        monkeypatch.setattr(approvals, "all_pending", lambda: [{"conversation_id": KID, "call_id": "c1"}])
        assert await progress.waiting_reasons(db) == {ROOT: "card"}


# -- 2. the whole app's summaries and lists ------------------------------------------------------------------------

async def test_the_island_and_the_status_count_a_sub_sessions_work_once_as_its_commanders(api):
    async with api.db() as db:
        await _family(db, KID, KID2)
        db.add(ArslanMessage(conversation_id=ROOT, role="user", content="Make the launch video"))
        await db.commit()
    with desktop_status.working(KID, title=BRIEF, kind="job", job_id="job-a"), \
            desktop_status.working(KID2, title="Find a cover", kind="job", job_id="job-b"), \
            desktop_status.awaiting_approval(KID):
        desktop_status.push("turn_finished", conversation_id=KID2, outcome="ok", title="typed there", work="turn")
        feed = (await api.get("/api/v1/island/feed")).json()
        status = (await api.get("/api/v1/desktop/status")).json()
        # SUB5 (commander stop): the entry's Stop names every sub-session under the commander.
        assert [(a["conversation_id"], a["title"], a["job_id"]) for a in feed["active"]] == [
            (ROOT, "Make the launch video", f"{sub_sessions.STOP_ALL}{ROOT}")]
        assert feed["awaiting_conversations"] == [ROOT]
        assert {(e["kind"], e["conversation_id"]) for e in feed["events"]} == {
            ("approval_needed", ROOT), ("turn_finished", ROOT)}
        assert status["working"] == 1
        assert {(e["kind"], e["conversation_id"]) for e in status["events"]} == {
            ("approval_needed", ROOT), ("turn_finished", ROOT)}
        with desktop_status.working(ROOT, title="Make the launch video"):       # the commander's own turn
            feed = (await api.get("/api/v1/island/feed")).json()
            assert [(a["conversation_id"], a["kind"]) for a in feed["active"]] == [(ROOT, "turn")]
            assert (await api.get("/api/v1/desktop/status")).json()["working"] == 1


async def test_the_island_lists_ordinary_conversations_as_before(api):
    with desktop_status.working("c-one", title="one", kind="job", job_id="job-1"), \
            desktop_status.working("c-two", title="two"):
        feed = (await api.get("/api/v1/island/feed")).json()
        assert [(a["conversation_id"], a["title"], a["job_id"]) for a in feed["active"]] == [
            ("c-one", "one", "job-1"), ("c-two", "two", None)]
        assert (await api.get("/api/v1/desktop/status")).json()["working"] == 2


async def test_the_waiting_badge_counts_waiting_sub_sessions_once_as_their_commander(memory):  # noqa: F811
    async with memory() as db:
        await _family(db, KID, KID2)
        await _family(db, "sub-grandkid", parent=KID)
        for n, cid in enumerate((KID, KID2, "sub-grandkid", "c-plain")):
            db.add(ArslanMessage(conversation_id=cid, role="user", content=f"words of {cid}"))
            db.add(ProactiveItem(kind="job_followup", fingerprint=f"job:{n}", source_key=f"job:{n}", title_key="t",
                                 evidence=[], goal="again", status="new", conversation_id=cid,
                                 created_at=datetime.utcnow()))
        await db.commit()
        assert await progress.waiting_reasons(db) == {ROOT: "reminder", "c-plain": "reminder"}
        assert (await progress.waiting_on_user(db)).count == 2
        db.add(Project(id="p1", name="P"))
        await db.commit()
        (await db.get(ConversationContext, ROOT)).project_id = "p1"
        await db.commit()
        waiting = await progress.waiting_on_user(db)
    assert (waiting.projects, waiting.conversations) == ({"p1"}, {"c-plain"})


async def test_the_whole_apps_runs_and_tasks_leave_a_sub_session_out_and_its_own_keep_it(api):
    now = datetime.utcnow()
    async with api.db() as db:
        await _family(db, KID)
        for n, cid in enumerate((ROOT, KID, "c-plain"), start=1):
            db.add(Run(id=n, conversation_id=cid, user_message=f"run of {cid}", kind="host", status="failed",
                       created_at=now))
        await db.commit()
    for cid in (ROOT, KID):
        spec = TaskSpec.model_validate({
            "id": f"t-{cid}", "scope": {"kind": "task", "owner_id": "local", "task_id": f"t-{cid}"},
            "instruction": "Prepare a result", "locale": "en",
            "acceptance": [{"id": "review", "description": "Review result", "evaluator": "human"}]})
        async with repository() as repo:
            await repo.create(spec, cid)
    assert [r["id"] for r in (await api.get("/api/v1/runs")).json()] == [3, 1]
    assert [r["id"] for r in (await api.get("/api/v1/runs", params={"conversation_id": KID})).json()] == [2]
    assert (await api.get("/api/v1/runs/counts")).json()["failed"] == 2
    assert [t["state"]["task_id"] for t in (await api.get("/api/v1/tasks")).json()] == [f"t-{ROOT}"]
    assert [t["state"]["task_id"] for t in (await api.get("/api/v1/tasks", params={"conversation_id": KID})).json()
            ] == [f"t-{KID}"]


# -- 3. a brief framed as outside content marks the sub-session's later turns ----------------------------------------

@pytest.fixture
def child(chat, monkeypatch):  # noqa: F811
    """A sub-session started with `brief` by a turn that did (or didn't) read outside content; its job is stopped
    before it runs, and S64-0b's chat entry then types into the sub-session."""
    async def make(outside: bool, brief: str = BRIEF) -> str:
        monkeypatch.setattr(sub_sessions, "ended", lambda job, text: None)
        background_jobs._slots = asyncio.Semaphore(0)
        kid = await sub_sessions.start(ROOT, brief, outside_seen=outside)
        [job] = [j for j in background_jobs._jobs.values() if j.conversation_id == kid]
        job.task.cancel()
        await _wait(lambda: job.task.done())
        background_jobs._slots = None
        monkeypatch.setattr(s64b, "CID", kid)              # the chat entry's conversation
        return kid
    return make


@pytest.mark.parametrize("outside", [True, False], ids=["brief-after-a-page", "clean-brief"])
async def test_a_turn_typed_in_a_sub_session_records_its_framed_briefs_sites_as_outside_content(chat, child,  # noqa: F811
                                                                                                outside):
    """NET-a, its switch on: the proxy refuses a site that appeared only in outside content, so a turn typed in the
    sub-session records the sites its framed brief names; a clean brief is the commander's words and records none."""
    from server.services import net_policy
    net_policy._reset_for_tests()
    try:
        kid = await child(outside, "Gather the notes from https://drop.evil.example/notes")
        await chat(s64b._Model(chat=_turn(NOTE_ADD)))
        assert net_policy.outside_hosts(kid) == ({"drop.evil.example"} if outside else frozenset())
    finally:
        net_policy._reset_for_tests()


@pytest.mark.usefixtures("s2a1_network_rule")          # NET-a: S2a-1's network card as the probe, its switch off
@pytest.mark.parametrize("outside", [True, False], ids=["brief-after-a-page", "clean-brief"])
async def test_a_turn_typed_in_a_sub_session_counts_its_framed_brief_as_outside_content(chat, child, outside):  # noqa: F811
    """The consequences: Arslan's own note waits for the user, and a command reaching the network asks first. (A
    sub-session's real turn never learns, so its note never applies anyway; the chat entry's context here lets it,
    so the mark can be seen.)"""
    kid = await child(outside)
    notes, network, runs = await chat(s64b._Model(chat=_turn(NOTE_ADD, COMMAND)))
    assert (notes, network) == ((["proposed"], ["network"]) if outside else (["active"], []))
    assert runs == [(False, False)]
    async with chat.db() as db:
        [brief] = (await db.scalars(select(ArslanMessage).where(ArslanMessage.conversation_id == kid,
                                                                 ArslanMessage.role == "user").limit(1))).all()
    assert brief.content.startswith(untrusted.BRIEF_FROM_OUTSIDE) is outside and brief.display_content in (BRIEF, None)


@pytest.mark.parametrize("outside", [True, False], ids=["brief-after-a-page", "clean-brief"])
async def test_a_summary_folding_in_a_framed_brief_stays_marked(chat, child, monkeypatch, outside):  # noqa: F811
    await child(outside, brief=POISON * 3)
    summary = await s64b._compact(chat, monkeypatch, ("arslan", "fine " * 40, None), ("user", "ok", None),
                                  ("arslan", "fine", None))
    assert summary.startswith(untrusted.SUMMARY_FROM_OUTSIDE) is outside


def test_only_a_users_line_that_opens_with_the_briefs_header_counts():
    framed = untrusted.sub_session_brief(POISON)
    assert untrusted.history_from_outside([{"role": "user", "content": framed}])
    assert not untrusted.history_from_outside([{"role": "assistant", "content": framed}])
    assert not untrusted.history_from_outside([{"role": "user", "content": untrusted.wrap_external(POISON)}])


# -- 4. typing into a running sub-session -------------------------------------------------------------------------

class _Answers:
    def __init__(self):
        self.calls = 0

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        if "BACKGROUND" not in str(system):
            self.calls += 1
        return LLMResponse(content="Hello! I'm here.", tool_calls=[], usage={})


@pytest.mark.parametrize("cid", [KID, "c-plain"], ids=["sub-session", "ordinary"])
def test_a_message_typed_in_a_sub_session_waits_for_its_background_turn(app_client, monkeypatch, cid):  # noqa: F811
    """In a sub-session, the message is told `queued`, runs only once the background turn is over, and is then told
    `dequeued`, as one sent during a chat turn is. An ordinary conversation answers while its job works (0.1.42)."""
    import time

    import server.ws.arslan as ws_arslan
    from server.services import personal_context as pc

    async def load(conversation_id, **kwargs):
        return pc.TaskMemoryContext(task_id=f"t-{time.monotonic_ns()}", run_id="r", conversation_id=conversation_id,
                                    no_memory=True, no_learning=True, query=kwargs.get("user_message", ""))
    model = _Answers()
    monkeypatch.setattr(task_context, "load", load)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    monkeypatch.setattr(sub_sessions, "ended", lambda job, text: None)
    ws_arslan._turn_locks.clear()

    async def held_job():
        async with app_client.db_maker() as db:
            await _family(db, KID)
        background_jobs._slots = asyncio.Semaphore(0)          # its background turn never gets a slot until stopped
        return await background_jobs.start(cid, BRIEF, [], outside_seen=False)
    job = app_client.portal.call(held_job)

    async def stop():
        job.task.cancel()
        await _wait(lambda: job.task.done())
    try:
        with app_client.websocket_connect(f"/ws/arslan/{cid}") as ws:
            ws.receive_json()
            ws.send_json({"type": "user_message", "content": "hi"})
            if cid == KID:
                before = [f.get("type") for f in _collect_until(ws, "queued", max_frames=20)]
                assert before[-1] == "queued" and "stream_start" not in before, before
                time.sleep(0.3)
                assert model.calls == 0, "the turn waits for the sub-session's background turn"
                app_client.portal.call(stop)
            frames = _collect_until(ws, "stream_end", max_frames=400)
            kinds = [f.get("type") for f in frames]
            assert model.calls >= 1 and "Hello" in "".join(f.get("content") or "" for f in frames)
            assert ("dequeued" in kinds) is (cid == KID) and "queued" not in kinds
            if cid != KID:
                assert job.phase == "queued", "answered while the job still waits"
    finally:
        if not job.task.done():
            app_client.portal.call(stop)
        ws_arslan._turn_locks.clear()
        background_jobs._slots = None

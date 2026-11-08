"""SUB4 (v0.1.64, card docs/plans/0164/SUB-sub-sessions.md): a sub-session's report and its commander's summary turn.

No tool table offers `start_sub_session` yet (SUB5 adds it after the M64 bench), so these tests start sub-sessions with
`sub_sessions.start` and run everything else for real: each sub-session's job and the commander's summary turn through
the background job runner, the real `background_body` and tool loop, real cards and the real turn lock, with a
scripted model.

- A sub-session's result is posted in its own conversation only; its commander gets one summary turn, with every
  report framed as outside content.
- A report from a sub-session that read outside content (or that nobody can vouch for) starts the summary flagged:
  Arslan's own note waits for the user, and a command that reaches the network asks first.
- The summary waits for every sub-session (one waiting for the user's answer doesn't hold it) and for an idle
  commander, and counts against the tree's spending limit.
- A sub-session's `done` ticks no project checkpoint.
"""
import asyncio
import json

import pytest
from sqlalchemy import select

from arslan.execution_budget import charge_usd, model_request
from arslan.execution_checkpoint import save
from arslan.models import LLMResponse
from server.db.models import ArslanMessage, MemoryEntry
from server.orchestrator import arslan as arslan_mod, untrusted
from server.registry import executors
from server.services import (approvals, background_jobs, personal_context as pc, project_evidence, run_registry,
                             settings_service, sub_sessions)
from tests.server.test_project_evidence import _active, _conversation, api  # noqa: F401  (the fixture)
from tests.server.test_s64_0_outside_content_gaps import (  # noqa: F401  (the fixture)
    NETWORK, NOTE, POISON, _Page, _Run, memory)

ROOT = "c-commander"
OUTLINE, COVER = "Draft the outline of the video", "Find a cover image idea"
PAGE = ("web_extract", {"url": "https://example.test/cover"})
NOTE_ADD = ("memory_note", {"action": "add", "set": "notes", "text": NOTE})
COMMAND = ("run_command", {"command": NETWORK})

_SINKS: list = []


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(sub_sessions, "POLL_SECONDS", 0.01)
    for module in (background_jobs, approvals, sub_sessions):
        module._reset_for_tests()
    yield
    monkeypatch.setattr(sub_sessions, "ended", lambda job, text: None)    # a job cancelled here reports nothing
    for module in (background_jobs, sub_sessions, approvals):
        module._reset_for_tests()
    while _SINKS:
        run_registry.detach_sink(*_SINKS.pop())


def _call(name, args):
    return {"id": f"call-{abs(hash((name, json.dumps(args))))}", "type": "function",
            "function": {"name": name, "arguments": args}}


def _steps(*steps, final="done"):
    return ([LLMResponse(usage={}, content=None, tool_calls=[_call(name, args)]) for name, args in steps]
            + [LLMResponse(usage={}, content=final, tool_calls=[])])


class _Model:
    """Every run scripted by where it is: the commander's summary turns (in ROOT), and each sub-session by its brief.
    A request goes through what a provider does first (count it, save before it: where the tree's limit is read) and
    is charged `price[side]` after. `hold[side]`, an Event, keeps that side's request open until it is set."""

    def __init__(self, children: dict, summary=(), price=None):
        self.replies = {"summary": list(summary), **{brief: list(r) for brief, r in children.items()}}
        self.requests = {side: [] for side in self.replies}
        self.price = price or {}
        self.hold: dict[str, asyncio.Event] = {}

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        ctx, text = pc.current(), json.dumps([user, history], ensure_ascii=False, default=str)
        side = "summary" if ctx and ctx.conversation_id == ROOT else next(
            (brief for brief in self.replies if brief != "summary" and brief in text), None)
        if side is None:
            return LLMResponse(usage={}, content="ok", tool_calls=[])
        model_request(1000)
        await save("before_model")
        self.requests[side].append({"user": user, "history": history})
        if side in self.hold:
            await self.hold[side].wait()
        replies = self.replies[side]
        reply = replies.pop(0) if replies else LLMResponse(usage={}, content=f"{side}: finished", tool_calls=[])
        charge_usd(self.price.get(side, 0.0))
        return reply


class _Writes:
    async def execute(self, args):
        return {"ok": True, "path": args.get("path"), "bytes": len(args.get("content", ""))}


async def _summary_tools():
    return [{"key": key, "description": "fixture"} for key in ("memory_note", "run_command", "update_plan")]


@pytest.fixture
def runs(memory, monkeypatch):  # noqa: F811
    """Real jobs; only the done-judge (another model) is left out. The summary turn is offered its note, a command
    and its plan (an ordinary job's tools, cut down to these)."""
    async def reached(job, text):
        return False
    monkeypatch.setattr(background_jobs, "_goal_not_reached", reached)
    monkeypatch.setattr(arslan_mod, "_background_tools", _summary_tools)
    monkeypatch.setattr(arslan_mod, "_background_callable", _summary_tools)
    monkeypatch.setitem(executors.EXECUTORS, "web_extract", _Page())
    monkeypatch.setitem(executors.EXECUTORS, "write_file", _Writes())
    return memory


async def _wait(predicate, seconds=10.0):
    deadline = asyncio.get_running_loop().time() + seconds
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)


def _sink(cid, answer=True):
    """What `cid`'s windows are shown; with `answer`, every card yes, this time."""
    shown = []

    def sink(frame):
        shown.append(frame)
        if answer and str(frame.get("type", "")).startswith("propose_"):
            _yes(frame)
    run_registry.attach_sink(cid, sink)
    _SINKS.append((cid, sink))
    return shown


def _yes(card):
    approvals.answer({"type": "confirm_" + card["type"].removeprefix("propose_"), "call_id": card["call_id"],
                      "scope": "once"})


def _cards(frames):
    return [f for f in frames if str(f.get("type", "")).startswith("propose_")]


def _summaries():
    return [job for job in background_jobs._jobs.values() if job.job_id.startswith(sub_sessions.SUMMARY_JOB)]


def _children():
    return [job for job in background_jobs._jobs.values() if job.parent_id == ROOT]


def _settled():
    return not background_jobs.unreported() and ROOT not in sub_sessions._summaries


async def _start(*briefs):
    for brief in briefs:
        await sub_sessions.start(ROOT, brief, outside_seen=False)


async def _messages(db, cid):
    async with db() as session:
        return list((await session.scalars(select(ArslanMessage).where(
            ArslanMessage.conversation_id == cid, ArslanMessage.role == "arslan"))).all())


def _framed(text: str, needle: str) -> bool:
    at = text.index(needle)
    return text.rfind(untrusted.DELIM_OPEN, 0, at) > text.rfind(untrusted.DELIM_CLOSE, 0, at)


# -- the report ---------------------------------------------------------------------------------------------------

async def test_results_stay_in_each_sub_session_and_the_commander_gets_one_summary_with_each_report_framed(
        runs, monkeypatch):
    _sink(ROOT)
    model = _Model({OUTLINE: _steps(("write_file", {"path": "outline.md", "content": "# Outline"}),
                                    final=f"Outline written. {POISON}"),
                    COVER: _steps(final="Cover: a fox at dawn.")},
                   summary=_steps(final="Both are done: the outline is in outline.md, and a cover idea."))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _start(OUTLINE, COVER)
    await _wait(_settled)
    [summary] = _summaries()
    [request] = model.requests["summary"][:1]
    sent = json.dumps(request["user"], ensure_ascii=False)
    for needle in (POISON, "Cover: a fox at dawn.", "outline.md"):
        assert _framed(sent, needle), needle                # each report, its files too, inside a data frame
    assert (summary.conversation_id, summary.parent_id, summary.outcome) == (ROOT, None, "done")
    assert summary.goal == "Sum up what the sub-sessions reported" and POISON not in summary.goal
    by_brief = {job.goal: job for job in _children()}
    assert by_brief[OUTLINE].files == ["outline.md"] and by_brief[COVER].files == []
    # The commander's conversation holds the summary's answer only, never a sub-session's own result.
    assert [m.display_content or m.content for m in await _messages(runs, ROOT)] == [
        "Both are done: the outline is in outline.md, and a cover idea."]
    for job in _children():
        [own] = await _messages(runs, job.conversation_id)
        assert ("Outline written" if job.goal == OUTLINE else "a fox at dawn") in (own.display_content or own.content)


@pytest.mark.parametrize("child_reads_page", [True, False], ids=["a-child-read-a-page", "clean"])
async def test_a_report_from_a_child_that_read_outside_content_starts_the_summary_flagged(
        runs, monkeypatch, child_reads_page):
    """The consequences in the summary turn, not the mark: Arslan's own note waits for the user, and a command that
    reaches the network asks first. The commander learns (it is no sub-session), so its note does tell the two apart."""
    runner = _Run()
    monkeypatch.setitem(executors.EXECUTORS, "run_command", runner)
    shown = _sink(ROOT)
    model = _Model({OUTLINE: _steps(*([PAGE] if child_reads_page else []), final="outline ready"),
                    COVER: _steps(final="cover ready")},
                   summary=_steps(NOTE_ADD, COMMAND, final="summed up"))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _start(OUTLINE, COVER)
    await _wait(_settled)
    assert {job.goal: job.external_seen for job in _children()} == {OUTLINE: child_reads_page, COVER: False}
    async with runs() as db:
        statuses = list((await db.scalars(select(MemoryEntry.status))).all())
    assert statuses == (["proposed"] if child_reads_page else ["active"])
    cards = _cards(shown)
    assert [c.get("perm_kind") for c in cards] == (["network"] if child_reads_page else [])
    assert all(c.get("sub_session") is None for c in cards)       # the commander's own card, as for any job
    assert runner.runs == [(False, False)]
    assert [s.outcome for s in _summaries()] == ["done"]


async def test_a_sub_session_nobody_can_vouch_for_counts_as_having_read_outside_content(runs, monkeypatch):
    """A child stopped mid-request read nothing, but it did not end on its own: its report starts the summary
    flagged."""
    shown = _sink(ROOT)
    model = _Model({OUTLINE: _steps(final="never sent")}, summary=_steps(NOTE_ADD, final="summed up"))
    model.hold[OUTLINE] = asyncio.Event()
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _start(OUTLINE)
    [child] = _children()
    await _wait(lambda: model.requests[OUTLINE])
    assert background_jobs.stop(child.conversation_id, child.job_id)
    await _wait(_settled)
    assert (child.outcome, child.external_seen) == ("stopped", None)
    async with runs() as db:
        assert list((await db.scalars(select(MemoryEntry.status))).all()) == ["proposed"]
    assert _cards(shown) == []


# -- when the summary runs ------------------------------------------------------------------------------------------

async def test_the_summary_waits_for_every_sub_session_and_is_one_turn_for_all_of_them(runs, monkeypatch):
    _sink(ROOT)
    model = _Model({OUTLINE: _steps(final="outline ready"), COVER: _steps(final="cover ready")},
                   summary=_steps(final="summed up"))
    model.hold[COVER] = asyncio.Event()
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _start(OUTLINE, COVER)
    await _wait(lambda: any(job.phase == "finished" for job in _children()))
    await asyncio.sleep(0.2)                                   # twenty polls: the cover is still at work
    assert _summaries() == [] and model.requests["summary"] == []
    model.hold[COVER].set()
    await _wait(_settled)
    [_] = _summaries()
    [request] = model.requests["summary"]
    sent = json.dumps(request["user"], ensure_ascii=False)
    assert "outline ready" in sent and "cover ready" in sent


async def test_a_sub_session_waiting_for_the_users_answer_does_not_hold_the_summary(runs, monkeypatch):
    """The cover child's network card waits in the commander's window: the outline's report is summed up meanwhile,
    with a line that one more waits for the user. Answered, the cover's report gets a summary of its own."""
    runner = _Run()
    monkeypatch.setitem(executors.EXECUTORS, "run_command", runner)
    shown = _sink(ROOT, answer=False)
    model = _Model({OUTLINE: _steps(final="outline ready"), COVER: _steps(PAGE, COMMAND, final="cover ready")},
                   summary=_steps(final="first summary") + _steps(final="second summary"))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _start(OUTLINE, COVER)
    await _wait(lambda: _cards(shown) and model.requests["summary"])
    [card] = _cards(shown)
    assert card["sub_session"] is True and card["perm_kind"] == "network"
    first = json.dumps(model.requests["summary"][0]["user"], ensure_ascii=False)
    assert "outline ready" in first and "cover ready" not in first
    assert "1 more sub-session(s) are waiting for the user's answer" in first
    await _wait(lambda: len(_summaries()) == 1 and _summaries()[0].phase == "finished")
    _yes(card)
    await _wait(_settled)
    assert len(_summaries()) == 2 and runner.runs == [(False, False)]
    second = json.dumps(model.requests["summary"][-1]["user"], ensure_ascii=False)
    assert "cover ready" in second and "outline ready" not in second


async def test_a_sub_session_that_started_its_own_sums_them_up_as_a_sub_session_before_its_commander_does(
        runs, monkeypatch):
    """The outline child started a child of its own. Its summary of it runs as the outline child's job (offered a
    sub-session's tools, asked in the commander's window), and is one more report to the commander, whose own summary
    waits for it."""
    _sink(ROOT)
    model = _Model({OUTLINE: _steps(final="outline: started the cover") + _steps(final="outline: the cover is in"),
                    COVER: _steps(final="cover ready")}, summary=_steps(final="summed up"))
    model.hold[OUTLINE] = asyncio.Event()
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    offered = []
    real = arslan_mod._sub_session_tools

    async def sub_tools():
        offered.append(pc.current().conversation_id)
        return await real()
    monkeypatch.setattr(arslan_mod, "_sub_session_tools", sub_tools)
    await _start(OUTLINE)
    [kid] = _children()
    await sub_sessions.start(kid.conversation_id, COVER, outside_seen=False)
    model.hold[OUTLINE].set()
    await _wait(_settled)
    [inner, outer] = sorted(_summaries(), key=lambda job: job.started_at)
    assert (inner.conversation_id, inner.parent_id, outer.conversation_id) == (kid.conversation_id, ROOT, ROOT)
    assert offered.count(kid.conversation_id) >= 2               # its own job's turn, and its summary's
    [request] = model.requests["summary"]
    sent = json.dumps(request["user"], ensure_ascii=False)
    assert "outline: started the cover" in sent and "outline: the cover is in" in sent and "cover ready" not in sent


@pytest.mark.parametrize("busy", ["turn_lock", "live_run"])
async def test_the_summary_waits_while_the_commander_is_busy(runs, monkeypatch, busy):
    """Rule 3: while the user talks to the commander (its turn lock held, or a run of it live), the report waits."""
    from server.ws import arslan as ws_arslan
    _sink(ROOT)
    model = _Model({OUTLINE: _steps(final="outline ready")}, summary=_steps(final="summed up"))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    lock = ws_arslan._turn_lock(ROOT)
    turn = asyncio.ensure_future(asyncio.Event().wait())
    if busy == "turn_lock":
        await lock.acquire()
    else:
        run_registry.register(987654, ROOT, turn)
    try:
        await _start(OUTLINE)
        await _wait(lambda: all(job.phase == "finished" for job in _children()))
        await asyncio.sleep(0.2)
        assert _summaries() == [] and ROOT in sub_sessions._summaries
    finally:
        if busy == "turn_lock":
            lock.release()
        else:
            run_registry.unregister(987654, ROOT)
        turn.cancel()
    await _wait(_settled)
    assert [s.outcome for s in _summaries()] == ["done"]


# -- spend --------------------------------------------------------------------------------------------------------

async def _cap(monkeypatch, usd):
    async def setting(db):
        return usd
    monkeypatch.setattr(settings_service, "task_usd_cap", setting)


async def test_a_summary_turn_is_stopped_at_its_trees_limit(runs, monkeypatch):
    """The sub-sessions spent the tree's $6 between them: the summary turn's first request is stopped there."""
    await _cap(monkeypatch, 2.0)
    _sink(ROOT)
    model = _Model({OUTLINE: _steps(final="outline ready"), COVER: _steps(final="cover ready")},
                   summary=_steps(final="summed up"), price={OUTLINE: 3.0, COVER: 3.2})
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _start(OUTLINE, COVER)
    await _wait(_settled)
    [summary] = _summaries()
    assert model.requests["summary"] == []
    assert (summary.outcome, summary.budget_stop["scope"], summary.budget_stop["limit"]) == ("out_of_budget", "tree",
                                                                                             "$6.00")


async def test_what_a_summary_turn_spends_counts_in_its_tree(runs, monkeypatch):
    """Three sub-sessions spent $4.50 of the tree's $6 and the summary $1.80, under each run's own $2 (read back from
    the stored snapshots): a sub-session's next request finds the tree past its limit."""
    await _cap(monkeypatch, 2.0)
    _sink(ROOT)
    plan = ("update_plan", {"items": [{"text": "sum up", "status": "in_progress"}]})
    third = "Write the voice-over"
    model = _Model({OUTLINE: _steps(final="outline ready"), COVER: _steps(final="cover ready"),
                    third: _steps(final="voice-over ready")}, summary=_steps(plan, final="summed up"),
                   price={OUTLINE: 1.5, COVER: 1.5, third: 1.5, "summary": 0.9})
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)
    await _start(OUTLINE, COVER, third)
    await _wait(_settled)
    assert [s.outcome for s in _summaries()] == ["done"] and len(model.requests["summary"]) == 2
    async with runs() as db:
        assert await sub_sessions.tree_spend(db, [c.conversation_id for c in _children()]) == pytest.approx(4.5)
    with pytest.raises(sub_sessions.TreeLimitReached):
        await sub_sessions.check_tree_spend(_children()[0].conversation_id)


# -- the project ----------------------------------------------------------------------------------------------------

async def test_a_sub_sessions_done_ticks_no_checkpoint_and_its_summary_says_nothing_for_the_user(
        runs, api, monkeypatch):  # noqa: F811
    """The commander was handed a checkpoint. Its sub-session's done ticks nothing, nor does the summary of it
    (v0.1.65: ticked when the commander accepts the report); the commander's own job still does. The summary is a
    job: what it says is not the user's words (`said=False`)."""
    pid, plan = await _active(api)
    fun = plan["levels"][0]["checkpoints"][1]["id"]
    await _conversation(api, pid, ROOT)
    assert (await api.post(f"/api/v1/projects/{pid}/handoff",
                           json={"checkpoint_id": fun, "conversation_id": ROOT})).status_code == 200
    turns = []

    def after_turn(project_id, conversation_id, message, *, said: bool):
        turns.append((conversation_id, said))
        return asyncio.sleep(0)
    monkeypatch.setattr(project_evidence, "after_turn", after_turn)
    _sink(ROOT)
    model = _Model({OUTLINE: _steps(final="outline ready")}, summary=_steps(final="summed up"))
    monkeypatch.setattr("server.orchestrator.tool_loop._get_adapter", lambda: model)

    async def state():
        return (await api.get(f"/api/v1/projects/{pid}/plan")).json()["levels"][0]["checkpoints"][1]["state"]
    await _start(OUTLINE)
    await _wait(_settled)
    assert [(c.outcome, s.outcome) for c in _children() for s in _summaries()] == [("done", "done")]
    assert await state() != "done"
    assert (ROOT, False) in turns and (ROOT, True) not in turns
    own = await background_jobs.start(ROOT, "Run the fun test", [], outside_seen=False)
    await _wait(lambda: own.task.done())
    assert own.outcome == "done" and await state() == "done"

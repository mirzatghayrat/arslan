"""0.1.61 §A4: the chat window's cards through decide(); a typed message answers the card;
an expired card is not a refusal; grants are kept per conversation.

Also the carries from Tasks 1–3 that live in the window: a window ask identical to a job's card
joins it and shows THAT card; a card shared with a job outlives the window's copy; a card's wait
does not spend the turn's wall clock. (The shadow judge these cards had was removed in C4: the tests
that followed it now check that nothing is judged.)"""
from __future__ import annotations

import asyncio
import threading
import time
import types

import pytest
from sqlalchemy import select

from arslan import execution_budget

from server.services import approvals, command_sandbox, run_registry, turn_journal
from tests.server.conftest import build_ws_client
from tests.server.test_run_command_confirm_flow import (
    _collect_until,
    _enable_shell,
    _stub_run_command_executor,
    _stub_tool_loop_adapter,
    _ToolThenAnswerAdapter,
)
import server.orchestrator.tool_loop as tool_loop_mod


@pytest.fixture(autouse=True)
def _clean_registry():
    for d in (run_registry._tasks, run_registry._by_conversation, run_registry._sinks, run_registry._recorders):
        d.clear()
    turn_journal._active.clear()
    approvals._reset_for_tests()
    yield
    approvals._reset_for_tests()
    for d in (run_registry._tasks, run_registry._by_conversation, run_registry._sinks, run_registry._recorders):
        d.clear()
    turn_journal._active.clear()


@pytest.fixture(autouse=True)
def _no_sandbox(monkeypatch):
    # S2a-2: an `rm` inside the folder is layer ③ — it runs in the sandbox without a card. These tests
    # use it as their example card, so the sandbox cannot start here and the card is the unsandboxed
    # one (this time / this conversation) on every platform.
    monkeypatch.setattr(command_sandbox, "available", lambda: False)


@pytest.fixture
def app_client(tmp_path, monkeypatch, portal):
    return build_ws_client(portal, tmp_path, monkeypatch, db_name="window_permissions.db")


class _Recording(_ToolThenAnswerAdapter):
    """The confirm-flow model, keeping what it was given each time: the follow-up call after the
    tool result is what the model was told about the card."""

    def __init__(self, command: str, argv: list[str]):
        super().__init__(command, argv)
        self.inputs: list[str] = []

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):  # noqa: ANN001
        self.inputs.append(f"{user}\n{history}")
        return await super().chat(system, user, history=history, tools=tools, temperature=temperature)


def _record_model(monkeypatch, command: str, argv: list[str]) -> _Recording:
    adapter = _Recording(command, argv)
    monkeypatch.setattr(tool_loop_mod, "_get_adapter", lambda: adapter)
    return adapter


def _until(predicate, seconds: float = 5.0) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "condition not reached"
        time.sleep(0.02)


def _waiters(call_id: str) -> int:
    pending = approvals._pending.get(call_id)
    return pending.waiters if pending is not None else 0


# ── the brief ─────────────────────────────────────────────────────────────────

def test_a_rule_card_offers_scopes_and_this_conversation_holds_on_a_new_socket(app_client, monkeypatch):
    _enable_shell(app_client, policy="ask_risky")
    _stub_tool_loop_adapter(monkeypatch, "rm", ["-f", "build/out.txt"])
    executor = _stub_run_command_executor(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/conv-a") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "clean the build"})
        card = _collect_until(ws, "propose_run_command")[-1]
        assert card["options"] == ["once", "conversation"]          # layer ③ is never "always"
        assert "outside the sandbox" in card["title"]
        ws.send_json({"type": "confirm_run_command", "call_id": card["call_id"], "scope": "conversation"})
        _collect_until(ws, "stream_end")
    # The scripted model calls its tool once; the next turn gets a fresh script.
    _stub_tool_loop_adapter(monkeypatch, "rm", ["-f", "build/out.txt"])
    with app_client.websocket_connect("/ws/arslan/conv-a") as ws2:        # a new socket, same conversation
        ws2.receive_json()
        ws2.send_json({"type": "user_message", "content": "again"})
        frames = _collect_until(ws2, "stream_end")
        assert "propose_run_command" not in [f.get("type") for f in frames]
    assert len(executor.calls) == 2
    # ...and only there: another conversation is asked again.
    _stub_tool_loop_adapter(monkeypatch, "rm", ["-f", "build/out.txt"])
    with app_client.websocket_connect("/ws/arslan/conv-other") as ws3:
        ws3.receive_json()
        ws3.send_json({"type": "user_message", "content": "clean the build"})
        card = _collect_until(ws3, "propose_run_command")[-1]
        ws3.send_json({"type": "cancel_run_command", "call_id": card["call_id"]})
        _collect_until(ws3, "stream_end")
    assert len(executor.calls) == 2


def test_a_message_typed_while_a_card_waits_answers_it(app_client, monkeypatch):
    monkeypatch.setattr(approvals, "TIMEOUT_S", 10)     # a message left waiting fails in seconds
    _enable_shell(app_client, policy="ask_all")
    model = _record_model(monkeypatch, "git", ["status"])
    executor = _stub_run_command_executor(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/conv-b") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "check the repo"})
        card = _collect_until(ws, "propose_run_command")[-1]
        # S2a-2 (②Main's review, D): no sandbox can start here, so the Careful-mode card is marked unsandboxed.
        assert card.get("unsandboxed") is True
        ws.send_json({"type": "user_message", "content": "no — look at the other folder"})
        frames = _collect_until(ws, "stream_end")
        assert card["call_id"] not in approvals.known_ids()
        results = [f for f in frames if f.get("type") == "tool_result"]
        assert results and results[0]["ok"] is False
        # The window's copy closes: the card was answered, by the message.
        assert {"type": "card_resolved", "call_id": card["call_id"], "outcome": "declined",
                "by": "mac"} in frames
        # The note reaches the MODEL: the call after the tool result (same turn, before the typed
        # message runs as a turn of its own) carries it as the user's answer to the card.
        assert "They said: no — look at the other folder" in model.inputs[1]
        # The typed message was not swallowed by the card: it runs next, as its own turn.
        later = _collect_until(ws, "stream_end")
        assert "dequeued" in [f.get("type") for f in later]
        assert len(model.inputs) == 3 and "no — look at the other folder" in model.inputs[2]
    assert executor.calls == []


def test_an_expired_window_card_is_reported_as_no_answer(app_client, monkeypatch):
    monkeypatch.setattr(approvals, "TIMEOUT_S", 0.2)
    _enable_shell(app_client, policy="ask_all")
    model = _record_model(monkeypatch, "git", ["status"])
    _stub_run_command_executor(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/conv-c") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "check the repo"})
        frames = _collect_until(ws, "stream_end")
        results = [f for f in frames if f.get("type") == "tool_result"]
        assert results and "NOT a refusal" in str(results[0])
        assert "declined" not in results[0]["summary"] and "said no" not in results[0]["summary"]
        assert "NOT a refusal" in model.inputs[1]


class _Steps:
    """A scripted model: one tool call per step, then a plain answer."""

    def __init__(self, *calls: tuple[str, dict]):
        self.calls = list(calls)

    async def chat_stream(self, system, user, history=None, tools=None, temperature=0.7):  # noqa: ANN001
        yield "done"

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):  # noqa: ANN001
        from arslan.models import LLMResponse
        if self.calls:
            name, arguments = self.calls.pop(0)
            return LLMResponse(content=None, usage={}, tool_calls=[
                {"id": f"c{len(self.calls)}", "function": {"name": name, "arguments": arguments}}])
        return LLMResponse(content="done", tool_calls=[], usage={})


def test_a_card_after_a_refused_one_is_told_its_own_answer(app_client, monkeypatch):
    """The words of a No (the user's note) belong to that card: a card after it in the same turn
    (leaving the sandbox, decided through permissions.decide since S4a) is told its own answer."""
    _enable_shell(app_client, policy="ask_risky")
    monkeypatch.setattr(tool_loop_mod, "_get_adapter", lambda: _Steps(
        ("run_command", {"command": "rm", "argv": ["-rf", "build"]}),
        ("run_command", {"command": "ls", "argv": [], "outside_sandbox": True, "why": "see home"})))
    executor = _stub_run_command_executor(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/conv-p") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "clean up, then look around"})
        rule = _collect_until(ws, "propose_run_command")[-1]
        ws.send_json({"type": "cancel_run_command", "call_id": rule["call_id"], "note": "keep build"})
        frames = _collect_until(ws, "propose_run_command")
        outside = frames[-1]
        assert outside.get("sandbox") == "outside"
        ws.send_json({"type": "cancel_run_command", "call_id": outside["call_id"]})
        frames += _collect_until(ws, "stream_end")
    summaries = [f["summary"] for f in frames if f.get("type") == "tool_result"]
    assert summaries == ["The user said no to: Run `rm -rf build` outside the sandbox?. They said: keep build",
                         "The user said no to: Run `ls` outside the sandbox?. Don't ask for it again in this turn."]
    assert executor.calls == []


def test_an_expired_card_to_leave_the_sandbox_is_no_answer_either(app_client, monkeypatch):
    """§A9 for the card to leave the sandbox too: expired is not declined."""
    monkeypatch.setattr(approvals, "TIMEOUT_S", 0.2)
    _enable_shell(app_client, policy="ask_risky")
    monkeypatch.setattr(tool_loop_mod, "_get_adapter", lambda: _Steps(
        ("run_command", {"command": "ls", "argv": [], "outside_sandbox": True, "why": "see home"})))
    executor = _stub_run_command_executor(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/conv-x") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "look around"})
        frames = _collect_until(ws, "stream_end")
    assert any(f.get("type") == "propose_run_command" and f.get("sandbox") == "outside" for f in frames)
    [result] = [f for f in frames if f.get("type") == "tool_result"]
    assert "NOT a refusal" in result["summary"] and "declined" not in result["summary"]
    assert executor.calls == []


def test_a_write_with_no_folder_is_not_told_an_earlier_refusal(app_client, monkeypatch, tmp_path):
    """No card at all (the folder the user chose is gone): the earlier card's words are not this
    refusal's. K7 (Q4): with the folder gone write_file is not offered, so it is refused as not
    callable before any card or folder check."""
    from server.services import settings_service
    _enable_shell(app_client, policy="ask_risky")

    async def gone_folder():
        async with app_client.db_maker() as db:
            await settings_service.update_settings(db, {"workspace_dir": str(tmp_path / "moved-away")})
    app_client.portal.call(gone_folder)
    monkeypatch.setattr(tool_loop_mod, "_get_adapter", lambda: _Steps(
        ("run_command", {"command": "rm", "argv": ["-rf", "build"]}),
        ("write_file", {"path": "notes.txt", "content": "x"})))
    _stub_run_command_executor(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/conv-w") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "clean up, then write notes"})
        rule = _collect_until(ws, "propose_run_command")[-1]
        ws.send_json({"type": "cancel_run_command", "call_id": rule["call_id"], "note": "keep build"})
        frames = _collect_until(ws, "stream_end")
    summaries = [f["summary"] for f in frames if f.get("type") == "tool_result"]
    assert "write_file' is not available" in summaries[-1] and "keep build" not in summaries[-1], summaries
    assert not any(f.get("type") == "propose_workspace_write" for f in frames)


# ── carry 3: a window ask identical to a job's card shows THAT card ───────────

def test_a_window_ask_identical_to_a_jobs_card_joins_it_and_one_answer_serves_both(app_client, monkeypatch):
    monkeypatch.setattr(approvals, "TIMEOUT_S", 8)      # a wrong card id fails in seconds, not 30 min
    _enable_shell(app_client, policy="ask_risky")
    _stub_tool_loop_adapter(monkeypatch, "rm", ["-rf", "build"])
    executor = _stub_run_command_executor(monkeypatch)
    job = approvals.JobConfirmations("conv-m", job_id="job-m")
    with app_client.websocket_connect("/ws/arslan/conv-m") as ws:
        ws.receive_json()
        asked = app_client.portal.start_task_soon(job.command, "rm -rf build", [])
        job_card = _collect_until(ws, "propose_run_command")[-1]
        assert job_card.get("background") is True                    # the job's card, on every window
        ws.send_json({"type": "user_message", "content": "clean the build"})
        _until(lambda: _waiters(job_card["call_id"]) == 2)            # the window joined it
        # The user answers the card on top of the window: it must be the one that is waiting.
        ws.send_json({"type": "confirm_run_command", "call_id": job_card["call_id"], "scope": "once"})
        frames = _collect_until(ws, "stream_end")
        shown = [f["call_id"] for f in frames if f.get("type") == "propose_run_command"]
        assert shown == [], f"the window painted a card of its own: {shown}"
        assert "error" not in [f.get("type") for f in frames]
        assert [f["ok"] for f in frames if f.get("type") == "tool_result"] == [True]
        assert asked.result(timeout=5) is True
    assert len(executor.calls) == 1 and approvals.known_ids() == set()


# ── carry 5 (M7): a card shared with a job outlives the window's copy ─────────

def test_a_typed_message_leaves_a_card_a_job_shares_open_for_the_job(app_client, monkeypatch):
    monkeypatch.setattr(approvals, "TIMEOUT_S", 8)
    _enable_shell(app_client, policy="ask_risky")
    model = _record_model(monkeypatch, "rm", ["-rf", "build"])
    executor = _stub_run_command_executor(monkeypatch)
    job = approvals.JobConfirmations("conv-s", job_id="job-s")
    with app_client.websocket_connect("/ws/arslan/conv-s") as ws, \
            app_client.websocket_connect("/ws/arslan/conv-s") as other:
        ws.receive_json(), other.receive_json()
        ws.send_json({"type": "user_message", "content": "clean the build"})
        card = _collect_until(ws, "propose_run_command")[-1]       # the window's own, private card
        asked = app_client.portal.start_task_soon(job.command, "rm -rf build", [])
        _until(lambda: _waiters(card["call_id"]) == 2)                # the job joined it
        ws.send_json({"type": "user_message", "content": "keep build, clean dist instead"})
        first = _collect_until(ws, "stream_end")
        # The window's turn has its answer (no, with the note) ...
        assert [f["ok"] for f in first if f.get("type") == "tool_result"] == [False]
        assert "They said: keep build, clean dist instead" in model.inputs[1]
        # ... and the card was not answered for the job: it stays open, now for everyone to see.
        assert card["call_id"] in approvals.known_ids()
        assert [c["call_id"] for c in approvals.pending_cards("conv-s")] == [card["call_id"]]
        _collect_until(ws, "stream_end")                              # the typed message's own turn
        seen = _collect_until(other, "stream_end") + _collect_until(other, "stream_end")
        assert card["call_id"] in [f.get("call_id") for f in seen if f.get("type") == "propose_run_command"]
        other.send_json({"type": "confirm_run_command", "call_id": card["call_id"], "scope": "once"})
        assert asked.result(timeout=5) is True
    assert executor.calls == [] and approvals.known_ids() == set()


def test_a_window_card_a_job_joined_expires_for_both_at_the_time_it_showed(app_client, monkeypatch):
    """PR 2b plan review: the job that joined the window's card waits only what is left of the
    card's time, not a fresh wait of its own — so the card never outlives the expiry it showed, is
    never published to the other windows as it expires, and both read it as no answer."""
    monkeypatch.setattr(approvals, "TIMEOUT_S", 2)                    # the card's time
    _enable_shell(app_client, policy="ask_risky")
    _stub_tool_loop_adapter(monkeypatch, "rm", ["-rf", "build"])
    executor = _stub_run_command_executor(monkeypatch)
    job = approvals.JobConfirmations("conv-e", job_id="job-e")
    with app_client.websocket_connect("/ws/arslan/conv-e") as ws, \
            app_client.websocket_connect("/ws/arslan/conv-e") as other:
        ws.receive_json(), other.receive_json()
        ws.send_json({"type": "user_message", "content": "clean the build"})
        card = _collect_until(ws, "propose_run_command")[-1]
        monkeypatch.setattr(approvals, "TIMEOUT_S", 30)               # a fresh wait would be longer
        asked = app_client.portal.start_task_soon(job.command, "rm -rf build", [])
        _until(lambda: _waiters(card["call_id"]) == 2)
        frames = _collect_until(ws, "stream_end")                     # the card expires
        assert "NOT a refusal" in str([f for f in frames if f.get("type") == "tool_result"])
        assert asked.result(timeout=5) is False                       # the job's wait ended with it
        assert approvals.pending_cards("conv-e") == [] and approvals.known_ids() == set()
        seen = _collect_until(other, "stream_end")
        assert card["call_id"] not in [f.get("call_id") for f in seen
                                       if f.get("type") == "propose_run_command"]
    assert executor.calls == []


def test_a_window_ask_that_joins_a_jobs_card_waits_only_what_is_left_of_it(app_client, monkeypatch):
    """The other way round: the window joins the job's card, and its wait ends when the card's
    does — not a fresh 30 minutes after it joined (PR 2b plan review)."""
    monkeypatch.setattr(approvals, "TIMEOUT_S", 4)                    # the job's card's time
    _enable_shell(app_client, policy="ask_risky")
    _stub_tool_loop_adapter(monkeypatch, "rm", ["-rf", "build"])
    executor = _stub_run_command_executor(monkeypatch)
    job = approvals.JobConfirmations("conv-j", job_id="job-j")
    with app_client.websocket_connect("/ws/arslan/conv-j") as ws:
        ws.receive_json()
        started = time.monotonic()
        asked = app_client.portal.start_task_soon(job.command, "rm -rf build", [])
        job_card = _collect_until(ws, "propose_run_command")[-1]
        monkeypatch.setattr(approvals, "TIMEOUT_S", 30)               # a fresh wait would be longer
        ws.send_json({"type": "user_message", "content": "clean the build"})
        _until(lambda: _waiters(job_card["call_id"]) == 2)            # the window joined it
        frames = _collect_until(ws, "stream_end")
        assert time.monotonic() - started < 8
        assert "NOT a refusal" in str([f for f in frames if f.get("type") == "tool_result"])
        assert asked.result(timeout=5) is False
    assert executor.calls == [] and approvals.known_ids() == set()


# ── carry 4: the window shows only the cards that need asking (C4: and judges none) ────

@pytest.fixture
def judge(monkeypatch):
    from server.services import judgment
    calls = []

    class Model:
        model = "judge-fixture"

        async def chat(self, *, system, user):
            calls.append(user)

            class Reply:
                content = '{"answer": false, "p": 0.2}'
            return Reply()

    async def adapter():
        return Model()
    monkeypatch.setattr(judgment, "_adapter", adapter)
    return calls


def _judgments(app_client, count: int) -> list:
    from server.db.models import Judgment

    async def read():
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 5
        while True:
            async with app_client.db_maker() as db:
                rows = (await db.scalars(select(Judgment))).all()
            if len([r for r in rows if r.outcome]) >= count or loop.time() > deadline:
                await asyncio.sleep(0.3)               # a stray extra row would have landed by now
                async with app_client.db_maker() as db:
                    return (await db.scalars(select(Judgment))).all()
            await asyncio.sleep(0.05)
    return app_client.portal.call(read)


def test_the_window_shows_only_the_cards_that_need_asking_and_judges_none(app_client, monkeypatch, judge):
    _enable_shell(app_client, policy="ask_risky")
    executor = _stub_run_command_executor(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/conv-j") as ws:
        ws.receive_json()
        _stub_tool_loop_adapter(monkeypatch, "rm", ["old.txt"])
        ws.send_json({"type": "user_message", "content": "delete old.txt"})
        shown = _collect_until(ws, "propose_run_command")[-1]
        ws.send_json({"type": "confirm_run_command", "call_id": shown["call_id"], "scope": "conversation"})
        _collect_until(ws, "stream_end")
        _stub_tool_loop_adapter(monkeypatch, "rm", ["old.txt"])      # the grant answers: no card
        ws.send_json({"type": "user_message", "content": "delete it again"})
        assert "propose_run_command" not in [f.get("type") for f in _collect_until(ws, "stream_end")]
        monkeypatch.setattr(approvals, "TIMEOUT_S", 0.3)
        _stub_tool_loop_adapter(monkeypatch, "git", ["push"])        # a rule: a card, unanswered
        ws.send_json({"type": "user_message", "content": "publish it"})
        frames = _collect_until(ws, "stream_end")
        unanswered = [f for f in frames if f.get("type") == "propose_run_command"][-1]
    assert shown["call_id"] != unanswered["call_id"]
    assert _judgments(app_client, 0) == [] and judge == []           # C4: no shadow judgment
    assert len(executor.calls) == 2


# ── carry 2: a card's wait is not the turn's time ─────────────────────────────

def test_a_card_answered_after_the_turns_wall_clock_still_finishes_the_turn(app_client, monkeypatch):
    # As in the app with its memory store active: the turn runs as a task, under its wall clock.
    # LOAD2: the user's time is a jump of the clocks while the card holds the turn's clock paused, not a
    # real sleep, so the turn's own work keeps room to spare (20 s, hard stop 30 s) and load cannot end
    # it. (A 2 s budget around a 4 s sleep failed 2 of 5 loaded runs with task_budget_exhausted.) Both
    # clocks jump: the budget's (time.monotonic) and the event loop's, which runs the turn's
    # asyncio.timeout. A wait that counted against the turn still ends it: 60 s is past the hard stop.
    monkeypatch.setenv("ARSLAN_RUN_MAX_WALL_SECONDS", "20")
    clock = {"offset": 0.0}
    real_monotonic = time.monotonic
    monkeypatch.setattr(execution_budget, "time", types.SimpleNamespace(monotonic=lambda: real_monotonic() + clock["offset"]))
    loop = app_client.portal.call(asyncio.get_running_loop)
    real_loop_time = loop.time
    monkeypatch.setattr(loop, "time", lambda: real_loop_time() + clock["offset"])
    holding = threading.Event()
    real_pause = execution_budget._WallClock.pause

    def pause(self):
        real_pause(self)
        holding.set()
    monkeypatch.setattr(execution_budget._WallClock, "pause", pause)
    _enable_shell(app_client, policy="ask_all")
    _stub_tool_loop_adapter(monkeypatch, "git", ["status"])
    executor = _stub_run_command_executor(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/conv-t") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "check the repo"})
        card = _collect_until(ws, "propose_run_command")[-1]
        assert holding.wait(10), "the card's wait never paused the turn's clock"   # the card frame goes out first
        clock["offset"] += 60                                         # the user takes a minute
        ws.send_json({"type": "confirm_run_command", "call_id": card["call_id"]})
        frames: list[dict] = []
        while not frames or frames[-1].get("type") not in ("stream_end", "error"):
            frames.append(ws.receive_json())
    assert frames[-1]["type"] == "stream_end", frames[-1]
    assert [f["ok"] for f in frames if f.get("type") == "tool_result"] == [True]
    assert len(executor.calls) == 1


# ── review fix round 1 ───────────────────────────────────────────────────────

def _ledger(app_client, conversation_id: str) -> list:
    from server.db.models import ApprovalEvent

    async def read():
        async with app_client.db_maker() as db:
            return (await db.scalars(select(ApprovalEvent).where(
                ApprovalEvent.conversation_id == conversation_id).order_by(ApprovalEvent.id))).all()
    return app_client.portal.call(read)


def test_once_a_card_in_a_turn_goes_unanswered_the_turns_later_cards_do_not_wait(app_client, monkeypatch, judge):
    """I1: as a job's surface, the window has a "person is away" latch. A turn can never stack
    30-minute waits; the next turn asks again.

    The ledger says it, not the clock (PR 2c): the later three decisions are "away" expiries
    whose card never opened (`wait_ms` None). The old check, under 2.0 s with a 0.5 s card, failed
    on a slow CI runner (2.08 s, run 38354283470) and in a loaded local run (2.05 s). Traced, no
    later card opened or waited in any run: the turn is the one card's wait (the final answer's paced
    reveal, about 0.5 s for "done", went in K8c), plus 130-odd
    statements of turn overhead, 0.15 s idle and up to 1.75 s under background-QoS throttling.
    The time bound only catches every card waiting its full time, which takes 4 x TIMEOUT_S."""
    monkeypatch.setattr(approvals, "TIMEOUT_S", 1.5)
    _enable_shell(app_client, policy="ask_all")
    monkeypatch.setattr(tool_loop_mod, "_get_adapter", lambda: _Steps(
        *[("run_command", {"command": "git", "argv": ["log", f"-{n}"]}) for n in range(1, 5)]))
    executor = _stub_run_command_executor(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/conv-u") as ws:
        ws.receive_json()
        started = time.monotonic()
        ws.send_json({"type": "user_message", "content": "look"})
        frames = _collect_until(ws, "stream_end")
        elapsed = time.monotonic() - started
        assert len([f for f in frames if f.get("type") == "propose_run_command"]) == 1
        results = [f["summary"] for f in frames if f.get("type") == "tool_result"]
        assert len(results) == 4 and all("NOT a refusal" in r for r in results), results
        first, *later = [(e.decided_by, e.decision, e.wait_ms) for e in _ledger(app_client, "conv-u")]
        assert first[:2] == ("expired", "expired") and first[2] >= 1000, first   # it waited its time
        assert later == [("away", "expired", None)] * 3, later                   # these never opened
        assert elapsed < 4 * approvals.TIMEOUT_S, f"the later cards waited: {elapsed:.2f} s"
        # A new turn: the person may be back, and is asked again.
        monkeypatch.setattr(tool_loop_mod, "_get_adapter", lambda: _Steps(
            ("run_command", {"command": "git", "argv": ["log", "-5"]})))
        monkeypatch.setattr(approvals, "TIMEOUT_S", 10)
        ws.send_json({"type": "user_message", "content": "look again"})
        card = _collect_until(ws, "propose_run_command")[-1]
        ws.send_json({"type": "confirm_run_command", "call_id": card["call_id"]})
        later = _collect_until(ws, "stream_end")
        assert [f["ok"] for f in later if f.get("type") == "tool_result"] == [True]
    assert len(executor.calls) == 1
    assert _judgments(app_client, 0) == [] and judge == []           # C4: no shadow judgment


class _FakeSsh:
    key = "ssh_run"

    def __init__(self):
        self.calls = []

    async def execute(self, args):
        self.calls.append(args)
        return {"ok": True, "summary": "ran remotely"}


def test_a_remote_card_answered_with_remember_still_asks_next_time(app_client, monkeypatch):
    """I2, P3b ruling ③ at the window: a remote command is never remembered — not by "remember",
    not by "in this conversation". (The reviewer's probe.)"""
    import server.registry.executors as executors_mod
    from server.registry import ssh_tools
    from server.services import settings_service, ssh_exec
    _enable_shell(app_client, policy="ask_risky")

    async def ssh_on():
        async with app_client.db_maker() as db:
            await settings_service.update_settings(db, {"ssh_enabled": "true"})
            # C3b: ssh_run is offered once a machine is enrolled
            from server.services import ssh_nodes
            await ssh_nodes.enroll(db, name="box", host="192.168.1.9", username="me",
                                   host_keys=["ssh-ed25519 AAAA"], fingerprints=["SHA256:x"])
    app_client.portal.call(ssh_on)

    async def prep(args):
        return {"ok": True, "host": "192.168.1.8", "user": "me", "command": "git", "argv": ["status"],
                "fingerprints": ["256 SHA256:abc (ED25519)"], "node_name": None}
    monkeypatch.setattr(ssh_tools, "prepare_confirmation", prep)
    monkeypatch.setattr(ssh_exec, "take", lambda host: None)
    fake = _FakeSsh()
    patched = dict(executors_mod.EXECUTORS)
    patched["ssh_run"] = fake
    monkeypatch.setattr(executors_mod, "EXECUTORS", patched)
    monkeypatch.setattr(tool_loop_mod, "EXECUTORS", patched)
    args = {"host": "192.168.1.8", "user": "me", "command": "git", "argv": ["status"]}
    with app_client.websocket_connect("/ws/arslan/conv-r") as ws:
        ws.receive_json()
        monkeypatch.setattr(tool_loop_mod, "_get_adapter", lambda: _Steps(("ssh_run", args)))
        ws.send_json({"type": "user_message", "content": "check the other machine"})
        card = _collect_until(ws, "propose_run_command")[-1]
        assert card.get("remote_host") == "me@192.168.1.8"
        ws.send_json({"type": "confirm_run_command", "call_id": card["call_id"], "remember": True,
                      "scope": "conversation"})
        _collect_until(ws, "stream_end")
        monkeypatch.setattr(tool_loop_mod, "_get_adapter", lambda: _Steps(("ssh_run", args)))
        ws.send_json({"type": "user_message", "content": "again"})
        frames = _collect_until(ws, "propose_run_command")
        assert frames[-1].get("type") == "propose_run_command", "a remote command must ask every time"
        assert frames[-1].get("remote_host") == "me@192.168.1.8"
        ws.send_json({"type": "cancel_run_command", "call_id": frames[-1]["call_id"]})
        _collect_until(ws, "stream_end")
    assert len(fake.calls) == 1
    # S4a: each card is one ledger row, under the machine's address (⓪Plan Q7), this time only.
    assert [(e.kind, e.target, e.decision, e.scope) for e in _ledger(app_client, "conv-r")] == [
        ("remote", "remote:192.168.1.8", "allow", "once"), ("remote", "remote:192.168.1.8", "deny", None)]


class _AsksForApps:
    """A tool that asks through permissions.decide (as Hands will): Notes, then Reminders."""
    key = "list_dir"

    def __init__(self, maker):
        self.maker, self.during = maker, None

    async def execute(self, args):
        from server.db.models import PermissionGrant
        from server.services import permissions
        for title, app in (("Use Notes?", "com.apple.Notes"), ("Use Reminders?", "com.apple.reminders")):
            await permissions.decide(permissions.Request(kind="app", target=app, title=title),
                                     permissions.Context(conversation_id="conv-g"))
        async with self.maker() as db:
            self.during = sorted((bool(g.task_id), g.target) for g in (await db.scalars(select(PermissionGrant))).all())
        return {"ok": True, "summary": "asked"}


def test_a_turns_task_grants_end_with_the_turn_and_its_conversation_grants_stay(app_client, monkeypatch):
    """S2 (§A5): "for this task" ends with the turn, as with a job."""
    import server.registry.executors as executors_mod
    from server.db.models import PermissionGrant
    tool = _AsksForApps(app_client.db_maker)
    patched = dict(executors_mod.EXECUTORS)
    patched["list_dir"] = tool
    monkeypatch.setattr(executors_mod, "EXECUTORS", patched)
    monkeypatch.setattr(tool_loop_mod, "EXECUTORS", patched)
    monkeypatch.setattr(tool_loop_mod, "_get_adapter", lambda: _Steps(("list_dir", {"path": "."})))
    scopes = {"Use Notes?": "task", "Use Reminders?": "conversation"}

    async def grants():
        for _ in range(50):              # the turn ends just after its last frame
            async with app_client.db_maker() as db:
                rows = sorted((bool(g.task_id), g.target) for g in (await db.scalars(select(PermissionGrant))).all())
            if len(rows) < 2:
                return rows
            await asyncio.sleep(0.05)
        return rows
    with app_client.websocket_connect("/ws/arslan/conv-g") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "tidy my notes into reminders"})
        for _ in scopes:
            card = _collect_until(ws, "propose_action")[-1]
            ws.send_json({"type": "confirm_action", "call_id": card["call_id"], "scope": scopes[card["title"]]})
        _collect_until(ws, "stream_end")
        assert tool.during == [(False, "com.apple.reminders"), (True, "com.apple.Notes")]
        assert app_client.portal.call(grants) == [(False, "com.apple.reminders")]


def test_a_window_ask_that_joins_a_card_on_screen_shares_it_and_nothing_is_judged(app_client, monkeypatch, judge):
    """J1: one card — the job's, which opened it; the window's ask joins it. C4: nothing judged."""
    monkeypatch.setattr(approvals, "TIMEOUT_S", 8)
    _enable_shell(app_client, policy="ask_risky")
    _stub_tool_loop_adapter(monkeypatch, "rm", ["-rf", "build"])
    _stub_run_command_executor(monkeypatch)
    job = approvals.JobConfirmations("conv-jj", job_id="job-jj")
    with app_client.websocket_connect("/ws/arslan/conv-jj") as ws:
        ws.receive_json()
        asked = app_client.portal.start_task_soon(job.command, "rm -rf build", [])
        job_card = _collect_until(ws, "propose_run_command")[-1]
        ws.send_json({"type": "user_message", "content": "clean the build"})
        _until(lambda: _waiters(job_card["call_id"]) == 2)
        ws.send_json({"type": "confirm_run_command", "call_id": job_card["call_id"], "scope": "once"})
        _collect_until(ws, "stream_end")
        assert asked.result(timeout=5) is True
    assert _judgments(app_client, 0) == [] and judge == []


# ── final-review fix wave: F3 ────────────────────────────────────────────────

def test_a_turns_card_that_never_opened_while_the_person_was_away_is_listed_with_no_always(
        app_client, monkeypatch, judge):
    """F3 (final review I3, §A4): after the window's away latch, a later card of the turn does not
    open. The model is told it expired ("NOT a refusal"); the Inbox lists it. S2a-2: a command rule
    is layer ②, once only, so its card never offered "Always" and the Inbox offers none either."""
    monkeypatch.setattr(approvals, "TIMEOUT_S", 0.3)
    _enable_shell(app_client, policy="ask_risky")
    monkeypatch.setattr(tool_loop_mod, "_get_adapter", lambda: _Steps(
        ("run_command", {"command": "rm", "argv": ["-rf", "build"]}),
        ("run_command", {"command": "git", "argv": ["push", "origin", "main"]})))
    executor = _stub_run_command_executor(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/conv-away") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "clean up, then publish"})
        frames = _collect_until(ws, "stream_end")
    assert len([f for f in frames if f.get("type") == "propose_run_command"]) == 1
    results = [f["summary"] for f in frames if f.get("type") == "tool_result"]
    assert len(results) == 2 and all("NOT a refusal" in r for r in results), results
    [row] = app_client.get("/api/v1/approvals/refused").json()       # the shown card is not listed
    assert (row["kind"], row["target"], row["conversation_id"]) == ("command", "rules:git-push",
                                                                     "conv-away")
    assert (row["always_ok"], row["always"]) == (False, [])
    allowed = app_client.post("/api/v1/permissions/rules", json={"refused_id": row["id"]})
    assert allowed.status_code == 409 and allowed.json()["detail"] == {"code": "no_always"}
    assert app_client.get("/api/v1/permissions/rules").json() == []
    assert executor.calls == []


# ── CI fix wave F1 (CI 38293278888): a turn's end and the grants it never got ──────────────────

class _AsksForNotes:
    """A tool that asks through permissions.decide once: Notes."""
    key = "list_dir"

    async def execute(self, args):
        from server.services import permissions
        await permissions.decide(permissions.Request(kind="app", target="com.apple.Notes", title="Use Notes?"),
                                 permissions.Context(conversation_id="conv-f1"))
        return {"ok": True, "summary": "asked"}


def test_a_turn_given_nothing_for_its_task_ends_without_waiting_on_the_database(app_client, monkeypatch):
    """A turn's end forgets what it was given "for this task", and only that: a turn whose card was
    answered for the conversation has none, so its end does not wait on the database — whose write
    lock a stopped run's own interrupted transaction can hold for seconds. Here deleting would
    wait 10 s."""
    import server.registry.executors as executors_mod
    from server.services import desktop_status, permission_store
    patched = dict(executors_mod.EXECUTORS)
    patched["list_dir"] = _AsksForNotes()
    monkeypatch.setattr(executors_mod, "EXECUTORS", patched)
    monkeypatch.setattr(tool_loop_mod, "EXECUTORS", patched)
    monkeypatch.setattr(tool_loop_mod, "_get_adapter", lambda: _Steps(("list_dir", {"path": "."})))
    deleting = []

    async def held(db, task_id):
        deleting.append(task_id)
        await asyncio.sleep(10)
        return 0
    monkeypatch.setattr(permission_store, "delete_task_grants", held)
    desktop_status._reset_for_tests()

    def ended() -> bool:
        return any(e["kind"] == "turn_finished" and e["conversation_id"] == "conv-f1"
                   for e in desktop_status.snapshot()["events"])
    with app_client.websocket_connect("/ws/arslan/conv-f1") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "look at my notes"})
        card = _collect_until(ws, "propose_action")[-1]
        ws.send_json({"type": "confirm_action", "call_id": card["call_id"], "scope": "conversation"})
        _collect_until(ws, "stream_end")
        _until(ended, seconds=2)
    assert deleting == []


# ── PR 2 fix wave 2 (M3 X5): a forget that raises is never a turn that does not end ────────────────

def test_a_turns_forget_that_raises_does_not_stop_the_turn_from_ending(app_client, monkeypatch, caplog):
    """The store's 24-hour prune is the backstop for a turn's grants a locked database would not
    let go: the turn still ends — `turn_finished` goes out and the socket flushes."""
    import logging

    import server.registry.executors as executors_mod
    from server.services import desktop_status, permissions
    patched = dict(executors_mod.EXECUTORS)
    patched["list_dir"] = _AsksForNotes()
    monkeypatch.setattr(executors_mod, "EXECUTORS", patched)
    monkeypatch.setattr(tool_loop_mod, "EXECUTORS", patched)
    monkeypatch.setattr(tool_loop_mod, "_get_adapter", lambda: _Steps(("list_dir", {"path": "."})))
    forgetting = []

    async def locked(task_id):
        forgetting.append(task_id)
        raise RuntimeError("database is locked")
    monkeypatch.setattr(permissions, "forget_task", locked)
    desktop_status._reset_for_tests()

    def ended() -> bool:
        return any(e["kind"] == "turn_finished" and e["conversation_id"] == "conv-f1"
                   for e in desktop_status.snapshot()["events"])
    with caplog.at_level(logging.WARNING, logger="server.ws.arslan"):
        with app_client.websocket_connect("/ws/arslan/conv-f1") as ws:
            ws.receive_json()
            ws.send_json({"type": "user_message", "content": "look at my notes"})
            card = _collect_until(ws, "propose_action")[-1]
            ws.send_json({"type": "confirm_action", "call_id": card["call_id"], "scope": "task"})
            _collect_until(ws, "stream_end")
            _until(ended, seconds=2)
    assert len(forgetting) == 1                                       # it was tried, for the turn's task
    assert "task grants not forgotten" in caplog.text

"""0.1.61 §A4: the chat window's cards through decide(); a typed message answers the card;
an expired card is not a refusal; grants are kept per conversation.

Also the carries from Tasks 1–3 that live in the window: a window ask identical to a job's card
joins it and shows THAT card; a card shared with a job outlives the window's copy; the shadow judge
sees only the cards that were shown; a card's wait does not spend the turn's wall clock."""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from server.services import approvals, run_registry, task_context, turn_journal
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
        assert card["options"] == ["once", "conversation", "always"]
        assert card["always_label"] and card["title"]
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
    """The words of a No (the user's note) belong to that card: a plain card after it in the same
    turn (leaving the sandbox) is told its own answer, not the earlier one's."""
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
    assert summaries == ["The user said no to: Run `rm -rf build`?. They said: keep build",
                         "user declined running this command outside the sandbox"]
    assert executor.calls == []


def test_an_expired_card_to_leave_the_sandbox_is_no_answer_either(app_client, monkeypatch):
    """§A9 for the plain window cards too (leaving the sandbox): expired is not declined."""
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
    refusal's."""
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
    assert summaries[-1] == "user declined workspace write access", summaries


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


def test_a_window_copy_that_expires_leaves_the_card_to_the_job_for_everyone(app_client, monkeypatch):
    monkeypatch.setattr(approvals, "TIMEOUT_S", 2)                    # the window's wait
    _enable_shell(app_client, policy="ask_risky")
    _stub_tool_loop_adapter(monkeypatch, "rm", ["-rf", "build"])
    executor = _stub_run_command_executor(monkeypatch)
    job = approvals.JobConfirmations("conv-e", job_id="job-e")
    with app_client.websocket_connect("/ws/arslan/conv-e") as ws, \
            app_client.websocket_connect("/ws/arslan/conv-e") as other:
        ws.receive_json(), other.receive_json()
        ws.send_json({"type": "user_message", "content": "clean the build"})
        card = _collect_until(ws, "propose_run_command")[-1]
        monkeypatch.setattr(approvals, "TIMEOUT_S", 30)               # the job's wait, longer
        asked = app_client.portal.start_task_soon(job.command, "rm -rf build", [])
        _until(lambda: _waiters(card["call_id"]) == 2)
        frames = _collect_until(ws, "stream_end")                     # the window's copy expires
        assert "NOT a refusal" in str([f for f in frames if f.get("type") == "tool_result"])
        assert [c["call_id"] for c in approvals.pending_cards("conv-e")] == [card["call_id"]]
        seen = _collect_until(other, "stream_end")
        assert card["call_id"] in [f.get("call_id") for f in seen if f.get("type") == "propose_run_command"]
        other.send_json({"type": "confirm_run_command", "call_id": card["call_id"], "scope": "once"})
        assert asked.result(timeout=5) is True
    assert executor.calls == [] and approvals.known_ids() == set()


# ── carry 4: the window's shadow judge sees only the cards that were shown ────

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


def test_the_windows_shadow_judge_sees_only_cards_that_were_shown(app_client, monkeypatch, judge):
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
        _stub_tool_loop_adapter(monkeypatch, "rm", ["-rf", "build"])  # two rules: a card, unanswered
        ws.send_json({"type": "user_message", "content": "clean the build"})
        frames = _collect_until(ws, "stream_end")
        unanswered = [f for f in frames if f.get("type") == "propose_run_command"][-1]
    rows = _judgments(app_client, 2)
    assert sorted((r.ref, r.outcome) for r in rows) == sorted(
        [(shown["call_id"], "approved"), (unanswered["call_id"], "expired")])
    assert len(judge) == 2 and len(executor.calls) == 2


# ── carry 2: a card's wait is not the turn's time ─────────────────────────────

def test_a_card_answered_after_the_turns_wall_clock_still_finishes_the_turn(app_client, monkeypatch):
    # As in the app with its memory store active: the turn runs as a task, under its wall clock.
    monkeypatch.setattr(task_context, "is_active", AsyncMock(return_value=True))
    monkeypatch.setenv("ARSLAN_RUN_MAX_WALL_SECONDS", "2")           # hard stop at 3 s
    _enable_shell(app_client, policy="ask_all")
    _stub_tool_loop_adapter(monkeypatch, "git", ["status"])
    executor = _stub_run_command_executor(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/conv-t") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "check the repo"})
        card = _collect_until(ws, "propose_run_command")[-1]
        time.sleep(4)                                                 # the user takes their time
        ws.send_json({"type": "confirm_run_command", "call_id": card["call_id"]})
        frames: list[dict] = []
        while not frames or frames[-1].get("type") not in ("stream_end", "error"):
            frames.append(ws.receive_json())
    assert frames[-1]["type"] == "stream_end", frames[-1]
    assert [f["ok"] for f in frames if f.get("type") == "tool_result"] == [True]
    assert len(executor.calls) == 1

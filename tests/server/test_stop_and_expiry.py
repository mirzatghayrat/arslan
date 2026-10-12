"""Seen on a real iPhone (2026-10-04): a task stopped from the phone left its command running
(`sleep 150` ran to the end, unseen), and a card that expired unanswered came back to the model as
"user declined", so Arslan told the user they had refused."""
import asyncio
import random
import subprocess

import pytest

from server.orchestrator import tool_loop
from server.services import approvals, run_registry, terminal_exec


def _sleeps(tag: str) -> int:
    """The shell's children only (not the shell, whose command line names them too)."""
    out = subprocess.run(["pgrep", "-f", f"^sleep {tag}"], capture_output=True, text=True).stdout
    return len(out.split())


async def test_a_stopped_command_stops_with_its_children(tmp_path):
    tag = f"{30 + random.random():.6f}"
    task = asyncio.create_task(terminal_exec.run(f"sleep {tag} & sleep {tag}; wait", cwd=tmp_path))
    for _ in range(60):
        await asyncio.sleep(0.05)
        if _sleeps(tag) == 2:
            break
    assert _sleeps(tag) == 2
    # Stopped while the command runs, not while it is being started (asyncio cleans that up itself).
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.3)
    assert _sleeps(tag) == 0, "nothing of it is left running"


def _a_surface():
    """A card surface bound, as in a chat turn or a job (with none, `approvals.ask` refuses at
    once: a scheduled run)."""
    from server.services import permissions
    return permissions.asking_with(approvals.BroadcastAsker("c"))


async def test_a_card_nobody_answered_is_not_reported_as_a_refusal(monkeypatch):
    monkeypatch.setattr(approvals, "TIMEOUT_S", 0.05)
    with _a_surface():
        assert await approvals.ask("c", {"type": "propose_run_command", "call_id": "x1"}) is False
    assert approvals.LAST_OUTCOME.get() == "expired"
    text = tool_loop._declined("user declined this command", "this command")
    assert text.startswith("Nobody answered the card for this command") and "NOT a refusal" in text
    # Told it may ask again, the model asked again within two seconds (device, 2026-10-05).
    assert "Don't retry it in this turn" in text and "can be asked again" not in text


async def test_a_decision_tells_the_model_in_its_own_words():
    """0.1.61: a card decided through permissions.decide says what happened in its own text —
    the user's note on a No — and a later plain card is not told the earlier decision."""
    from server.services import permissions
    permissions.LAST_DECISION.set(permissions.Decision(
        False, "user", note="use dist", model_text="The user said no to: Run `rm`?. They said: use dist"))
    approvals.LAST_OUTCOME.set("declined")
    assert tool_loop._declined("user declined this command", "this command") == \
        "The user said no to: Run `rm`?. They said: use dist"
    permissions.LAST_DECISION.set(None)                 # a plain card: no decision of its own
    assert tool_loop._declined("user declined this command", "this command") == "user declined this command"


async def test_after_one_unanswered_card_a_job_opens_no_more(execution_db, monkeypatch):
    # 0.1.61: the rule lives in the job's card surface (approvals.BroadcastAsker), and covers the
    # cards decided through permissions.decide too (the schedule below).
    monkeypatch.setattr(approvals, "TIMEOUT_S", 0.05)
    opened = []
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: lambda f: (
        opened.append(f["call_id"]) if f["type"].startswith("propose_") else None))
    job = approvals.JobConfirmations("c7", job_id="job-c7")
    assert await job.command("touch ~/Downloads/a", [], sandbox="retry") is False
    assert await job.command("touch ~/Downloads/a", [], sandbox="outside", why="again") is False
    assert await job.schedule("daily", "08:00") is False
    assert len(opened) == 1, "the person is away: one card, not one per retry"
    assert approvals.LAST_OUTCOME.get() == "expired", "and the retries read as expired, not refused"


async def test_a_refused_card_does_not_close_the_job_to_later_cards(monkeypatch):
    opened = []

    def window(f):                    # a window on the conversation that says no to each card
        if f["type"].startswith("propose_"):
            opened.append(f["call_id"])
            approvals.answer({"type": "cancel_run_command", "call_id": f["call_id"]})
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: window)
    job = approvals.JobConfirmations("c8")
    await job.command("touch ~/Downloads/a", [], sandbox="retry")
    await job.command("touch ~/Downloads/b", [], sandbox="retry")
    assert len(opened) == 2, "a person who answered is there: a different request may still ask"


async def test_a_real_refusal_keeps_its_words(monkeypatch):
    monkeypatch.setattr(approvals, "TIMEOUT_S", 5)

    async def ask_and_tell():
        with _a_surface():
            approved = await approvals.ask("c", {"type": "propose_run_command", "call_id": "x2"})
        return approved, approvals.LAST_OUTCOME.get(), tool_loop._declined("user declined this command", "this command")

    task = asyncio.create_task(ask_and_tell())
    await asyncio.sleep(0.01)
    assert approvals.answer({"type": "cancel_run_command", "call_id": "x2", "source": "phone"})
    assert await task == (False, "declined", "user declined this command")


async def test_a_plain_card_is_not_told_an_earlier_decision(monkeypatch):
    """A card that is not decided by permissions.decide (Hands' plain card) starts afresh: the
    words of an earlier No are not its answer."""
    from server.services import permissions
    monkeypatch.setattr(approvals, "TIMEOUT_S", 5)

    async def ask_and_tell():
        permissions.LAST_DECISION.set(permissions.Decision(False, "user", note="x", model_text="earlier words"))
        with _a_surface():
            approved = await approvals.ask("c", {"type": "propose_run_command", "call_id": "x4"})
        return approved, tool_loop._declined("user declined this command", "this command")

    task = asyncio.create_task(ask_and_tell())
    await asyncio.sleep(0.01)
    assert approvals.answer({"type": "cancel_run_command", "call_id": "x4", "source": "phone"})
    assert await task == (False, "user declined this command")


async def test_a_jobs_card_is_told_its_own_answer_not_an_earlier_one(execution_db, monkeypatch):
    from unittest.mock import AsyncMock

    from server.services import settings_service

    def window(f):                    # every window on the conversation: No to each card
        kind = f["type"].removeprefix("propose_")
        if f["type"].startswith("propose_"):
            approvals.answer({"type": f"cancel_{kind}", "call_id": f["call_id"],
                              "note": "not daily" if kind == "schedule" else ""})
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: window)
    job = approvals.JobConfirmations("c9", job_id="job-c9")
    assert await job.schedule("daily", "08:00") is False
    assert tool_loop._declined("user declined to schedule this task", "scheduling this task").endswith("not daily")
    assert await job.command("touch ~/Downloads/a", [], sandbox="retry") is False      # a plain card
    assert tool_loop._declined("user declined this command", "this command") == "user declined this command"
    assert await job.schedule("weekly", "Mon") is False
    monkeypatch.setattr(settings_service, "workspace_dir", AsyncMock(return_value=None))
    assert await job.workspace_write("write_file", "a.txt") is False                    # no card at all
    assert tool_loop._declined("user declined workspace write access", "writing") == \
        "user declined workspace write access"


async def test_a_scheduled_run_is_refused_a_plain_card_at_once(monkeypatch):
    """§A4 "scheduled runs never wait": with no card surface bound (nobody to ask), Hands' plain
    card is refused at once — no card, nothing in the Inbox, no wait."""
    sent = []
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: sent.append)
    monkeypatch.setattr(approvals, "TIMEOUT_S", 3)      # were it to wait, it would wait this long
    started = asyncio.get_running_loop().time()
    assert await approvals.ask("c", {"type": "propose_action", "call_id": "x6", "kind": "desktop_look",
                                     "target": "Notes", "detail": ""}) is False
    assert asyncio.get_running_loop().time() - started < 0.5
    assert sent == [] and approvals.all_pending() == [] and approvals.known_ids() == set()
    assert approvals.LAST_OUTCOME.get() == "declined"


async def test_a_plain_cards_wait_is_not_the_works_time(monkeypatch):
    """Hands' plain card in a job or a chat turn: answered after the work's own wall clock would
    have run out, the work goes on (its clock stood still meanwhile)."""
    from arslan import execution_budget
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: lambda f: None)
    budget = execution_budget.Budget(execution_budget.Limits(wall_seconds=0.3))
    timeout = asyncio.timeout(budget.remaining_seconds())
    asyncio.get_running_loop().call_later(0.6, approvals.answer, {"type": "confirm_action", "call_id": "x7"})
    async with timeout:
        with execution_budget.running_clock(budget, timeout), _a_surface():
            assert await approvals.ask("c", {"type": "propose_action", "call_id": "x7", "kind": "desktop_look",
                                             "target": "Notes", "detail": ""}) is True
    assert not timeout.expired()

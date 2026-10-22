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


async def test_a_card_nobody_answered_is_not_reported_as_a_refusal(execution_db, monkeypatch):
    """Decided through permissions.decide: the decision's own words say so."""
    from server.services import permissions
    monkeypatch.setattr(approvals, "TIMEOUT_S", 0.05)
    with permissions.asking_with(approvals.BroadcastAsker("c")):
        decision = await permissions.decide(permissions.Request(kind="app", target="com.apple.Notes",
                                                                title="Use Notes?"),
                                            permissions.Context(conversation_id="c"))
    assert not decision.allowed and approvals.LAST_OUTCOME.get() == "expired"
    text = tool_loop._declined("user declined this command", "this command")
    assert text.startswith("Nobody answered the card for Use Notes?") and "NOT a refusal" in text
    # Told it may ask again, the model asked again within two seconds (device, 2026-10-05).
    assert "Don't retry it in this turn" in text and "can be asked again" not in text


async def test_a_jobs_outside_card_nobody_answered_is_not_reported_as_a_refusal(execution_db, monkeypatch):
    """A job's card to leave the sandbox is decided through permissions.decide (S4a): nobody answered it."""
    monkeypatch.setattr(approvals, "TIMEOUT_S", 0.05)
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: lambda f: None)
    job = approvals.JobConfirmations("c10", job_id="job-c10")
    assert await job.command("touch ~/Downloads/a", [], sandbox="retry") is False
    assert approvals.LAST_OUTCOME.get() == "expired"
    text = tool_loop._declined("user declined this command", "this command")
    assert text.startswith("Nobody answered the card for Run `touch ~/Downloads/a` outside the sandbox?")
    assert "NOT a refusal" in text
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


async def test_a_refused_card_does_not_close_the_job_to_later_cards(execution_db, monkeypatch):
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
    assert await job.command("touch ~/Downloads/a", [], sandbox="retry") is False      # S4a: a decide card too
    told = tool_loop._declined("user declined this command", "this command")
    assert told.startswith("The user said no to: Run `touch ~/Downloads/a` outside the sandbox?")
    assert "not daily" not in told
    assert await job.schedule("weekly", "Mon") is False
    monkeypatch.setattr(settings_service, "workspace_dir", AsyncMock(return_value=None))
    assert await job.workspace_write("write_file", "a.txt") is False                    # no card at all
    assert tool_loop._declined("user declined workspace write access", "writing") == \
        "user declined workspace write access"

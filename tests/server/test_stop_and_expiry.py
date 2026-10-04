"""Seen on a real iPhone (2026-10-04): a task stopped from the phone left its command running
(`sleep 150` ran to the end, unseen), and a card that expired unanswered came back to the model as
"user declined", so Arslan told the user they had refused."""
import asyncio
import random
import subprocess

import pytest

from server.orchestrator import tool_loop
from server.services import approvals, terminal_exec


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


async def test_a_card_nobody_answered_is_not_reported_as_a_refusal(monkeypatch):
    monkeypatch.setattr(approvals, "TIMEOUT_S", 0.05)
    assert await approvals.ask("c", {"type": "propose_run_command", "call_id": "x1"}) is False
    assert approvals.LAST_OUTCOME.get() == "expired"
    text = tool_loop._declined("user declined this command", "this command")
    assert text.startswith("nobody answered") and "did not decline" in text
    # Told it may ask again, the model asked again within two seconds (device, 2026-10-05).
    assert "Do not ask for it again" in text and "can be asked again" not in text


async def test_after_one_unanswered_card_a_job_opens_no_more(monkeypatch):
    opened = []

    async def ask(conversation_id, frame):
        opened.append(frame["call_id"])
        approvals.LAST_OUTCOME.set("expired")
        return False
    monkeypatch.setattr(approvals, "ask", ask)
    job = approvals.JobConfirmations("c7")
    assert await job.command("touch ~/Downloads/a", [], sandbox="retry") is False
    assert await job.command("touch ~/Downloads/a", [], sandbox="outside", why="again") is False
    assert await job.schedule("daily", "08:00") is False
    assert len(opened) == 1, "the person is away: one card, not one per retry"
    assert approvals.LAST_OUTCOME.get() == "expired", "and the retries read as expired, not refused"


async def test_a_refused_card_does_not_close_the_job_to_later_cards(monkeypatch):
    opened = []

    async def ask(conversation_id, frame):
        opened.append(frame["call_id"])
        approvals.LAST_OUTCOME.set("declined")
        return False
    monkeypatch.setattr(approvals, "ask", ask)
    job = approvals.JobConfirmations("c8")
    await job.command("touch ~/Downloads/a", [], sandbox="retry")
    await job.command("touch ~/Downloads/b", [], sandbox="retry")
    assert len(opened) == 2, "a person who answered is there: a different request may still ask"


async def test_a_real_refusal_keeps_its_words(monkeypatch):
    monkeypatch.setattr(approvals, "TIMEOUT_S", 5)

    async def ask_and_tell():
        approved = await approvals.ask("c", {"type": "propose_run_command", "call_id": "x2"})
        return approved, approvals.LAST_OUTCOME.get(), tool_loop._declined("user declined this command", "this command")

    task = asyncio.create_task(ask_and_tell())
    await asyncio.sleep(0.01)
    assert approvals.answer({"type": "cancel_run_command", "call_id": "x2", "source": "phone"})
    assert await task == (False, "declined", "user declined this command")

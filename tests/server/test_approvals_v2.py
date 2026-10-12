"""0.1.61 §A4: cards wait 30 minutes; an answer carries a scope and a note; identical requests
share one card; the phone and the island answer once only; a job asks like a window."""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from server.services import approvals, permission_store, permissions, run_registry, settings_service


@pytest.fixture(autouse=True)
def _clean():
    approvals._reset_for_tests()
    yield
    approvals._reset_for_tests()


def frame(call_id="c1", dedupe="app\x1fcom.apple.Notes", options=("task", "conversation", "always")):
    return {"type": "propose_action", "call_id": call_id, "kind": "app", "target": "Notes",
            "detail": "", "options": list(options), "dedupe": dedupe}


def test_cards_wait_thirty_minutes():
    assert approvals.TIMEOUT_S == 1800


async def test_an_answer_carries_a_scope_the_card_offered_and_a_note_on_no(monkeypatch):
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    p = approvals.open_card("conv", frame())
    approvals.answer({"type": "confirm_action", "call_id": "c1", "scope": "conversation"})
    assert approvals.close_card(p)["scope"] == "conversation"
    q = approvals.open_card("conv", frame("c2", dedupe="x"))
    approvals.answer({"type": "confirm_action", "call_id": "c2", "scope": "forever"})
    assert approvals.close_card(q)["scope"] == "task"           # not offered → first option
    r = approvals.open_card("conv", frame("c3", dedupe="y"))
    approvals.answer({"type": "cancel_action", "call_id": "c3", "note": "use Bear instead"})
    d = approvals.close_card(r)
    assert (d["approved"], d["note"]) == (False, "use Bear instead")


async def test_legacy_remember_maps_to_a_scope(monkeypatch):
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    p = approvals.open_card("conv", frame(options=("once", "conversation", "always")))
    approvals.answer({"type": "confirm_action", "call_id": "c1", "remember": True})
    assert approvals.close_card(p)["scope"] == "always"


@pytest.mark.parametrize("source", ["phone", "island"])
async def test_phone_and_island_answers_are_once_only(monkeypatch, source):
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    p = approvals.open_card("conv", frame())
    approvals.answer({"type": "confirm_action", "call_id": "c1", "scope": "always", "source": source})
    assert approvals.close_card(p)["scope"] == "task"


async def test_identical_requests_share_one_card(monkeypatch):
    sent = []
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: sent.append)
    a = approvals.open_card("conv", frame("c1"))
    b = approvals.open_card("conv", frame("c2"))                # same dedupe key
    assert a is b and [f["call_id"] for f in sent] == ["c1"]
    approvals.answer({"type": "confirm_action", "call_id": "c1", "scope": "task"})
    assert approvals.close_card(a)["approved"] and approvals.close_card(b)["approved"]
    assert [f["type"] for f in sent].count("card_resolved") == 1


async def test_one_waiter_expiring_does_not_close_a_shared_card(monkeypatch):
    sent = []
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: sent.append)
    a = approvals.open_card("conv", frame("c1"))
    b = approvals.open_card("conv", frame("c2"))
    assert approvals.close_card(a)["by"] is None                # this waiter gave up
    assert "c1" in approvals.known_ids()                       # the card is still open for b
    approvals.answer({"type": "confirm_action", "call_id": "c1"})
    assert approvals.close_card(b)["approved"] is True
    assert [f["type"] for f in sent].count("card_resolved") == 1


async def test_decline_pending_answers_only_the_named_cards(monkeypatch):
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    mine = approvals.open_card("conv", frame("c1"), broadcast=False)
    other = approvals.open_card("conv", frame("c2", dedupe="z"))
    assert approvals.decline_pending({"c1"}, "actually, open Mail first") == 1
    d = approvals.close_card(mine)
    assert (d["approved"], d["note"], d["by"]) == (False, "actually, open Mail first", "mac")
    assert not other.future.done()


async def test_a_job_asks_like_a_window_and_stops_waiting_after_one_expiry(monkeypatch):
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    monkeypatch.setattr(approvals, "TIMEOUT_S", 0.05)
    asker = approvals.BroadcastAsker("conv")
    first = await asker(frame("c1"))
    assert first["by"] is None and asker.unanswered
    second = await asker(frame("c2", dedupe="other"))           # does not wait again
    assert second["by"] is None
    assert "c2" not in approvals.known_ids()


async def test_a_job_card_shows_its_options_and_records_the_scope(monkeypatch):
    sent = []
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: sent.append)
    asker = approvals.BroadcastAsker("conv")
    task = asyncio.ensure_future(asker(frame("c1")))
    await asyncio.sleep(0)
    assert sent[0]["background"] is True and sent[0]["options"] == ["task", "conversation", "always"]
    approvals.answer({"type": "confirm_action", "call_id": "c1", "scope": "conversation"})
    assert (await task)["scope"] == "conversation"


# ── the Inbox's answer, a job's cards on decide(), the job id, CARD_S (rulings 1-3) ──────────

async def test_the_inbox_answers_with_any_scope_the_card_offered_and_a_note(monkeypatch):
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    p = approvals.open_card("conv", frame("c1"), broadcast=False)
    assert approvals.answer_by_id("c1", True, source="inbox", scope="always")
    assert approvals.close_card(p)["scope"] == "always"         # the Inbox honours every choice
    q = approvals.open_card("conv", frame("c2", dedupe="q"), broadcast=False)
    assert approvals.answer_by_id("c2", False, source="inbox", note="  open Mail first ")
    assert approvals.close_card(q) == {"approved": False, "remember": False, "scope": None,
                                       "note": "open Mail first", "by": "inbox"}


class Windows:
    """Every window on the conversation, played by the test: it answers each card it is shown as
    told — ("yes", scope), ("no", note), or None for nobody — and keeps the cards."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.cards: list[dict] = []

    def __call__(self, sent: dict) -> None:
        if not sent["type"].startswith("propose_"):
            return                                              # card_resolved and the like
        self.cards.append(sent)
        reply = self.replies.pop(0)
        if reply is not None:
            verb, words = reply
            kind = sent["type"].removeprefix("propose_")
            approvals.answer({"type": f"{'confirm' if verb == 'yes' else 'cancel'}_{kind}",
                              "call_id": sent["call_id"],
                              **({"scope": words} if verb == "yes" else {"note": words})})


@pytest.fixture
def job_db(execution_db, monkeypatch):
    permission_store._reset_for_tests()
    monkeypatch.setattr(settings_service, "shell_confirm_policy", AsyncMock(return_value="ask_risky"))
    return execution_db


async def _ledger(maker) -> list:
    async with maker() as db:
        return list(reversed(await permission_store.recent(db)))       # oldest first


async def test_a_job_command_card_offers_the_windows_choices_and_is_recorded_for_its_job(job_db, monkeypatch):
    windows = Windows(("yes", "conversation"))
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: windows)
    assert await approvals.JobConfirmations("conv", job_id="job-1").command("rm old.txt", []) is True
    [card] = windows.cards
    assert card["type"] == "propose_run_command" and card["background"] is True
    assert card["options"] == ["once", "conversation", "always"] and card["always_label"] == "deletes files"
    # A job's grants are its conversation's: the next job in it is not asked again.
    assert await approvals.JobConfirmations("conv", job_id="job-2").command("rm old.txt", []) is True
    assert len(windows.cards) == 1
    assert [(r.job_id, r.kind, r.decided_by, r.scope) for r in await _ledger(job_db)] == [
        ("job-1", "command", "user", "conversation"), ("job-2", "command", "grant", "conversation")]


async def test_always_on_a_job_card_keeps_every_rule_with_its_own_label(job_db, monkeypatch):
    windows = Windows(("yes", "always"))
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: windows)
    assert await approvals.JobConfirmations("conv", job_id="job-1").command("rm -rf build", []) is True
    assert windows.cards[0]["always_label"] == "deletes files, recursive delete"
    async with job_db() as db:
        rules = {(r.target, r.label) for r in await permission_store.list_rules(db, "legacy_rule")}
    assert rules == {("delete", "deletes files"), ("hermes:recursive delete", "recursive delete")}
    # The standing answer holds in another conversation and job, and still writes its ledger row.
    assert await approvals.JobConfirmations("other", job_id="job-2").command("rm -rf build", []) is True
    assert len(windows.cards) == 1
    last = (await _ledger(job_db))[-1]
    assert (last.conversation_id, last.job_id, last.decided_by, last.scope) == ("other", "job-2", "rule", "always")


async def test_a_job_workspace_write_asks_through_decide_and_once_means_once(job_db, monkeypatch):
    windows = Windows(("yes", "once"), ("yes", "conversation"))
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: windows)
    job = approvals.JobConfirmations("conv", job_id="job-1")
    assert await job.workspace_write("write_file", "a.txt") is True
    assert await job.workspace_write("write_file", "b.txt") is True          # "once" held once: asked again
    assert await approvals.JobConfirmations("conv", job_id="job-2").workspace_write("write_file", "c.txt") is True
    assert [c["path"] for c in windows.cards] == ["a.txt", "b.txt"]        # the conversation grant covered c
    assert windows.cards[0]["options"] == ["once", "conversation"]
    assert [(r.job_id, r.decided_by, r.scope) for r in await _ledger(job_db)] == [
        ("job-1", "user", "once"), ("job-1", "user", "conversation"), ("job-2", "grant", "conversation")]


async def test_a_job_schedule_card_goes_through_decide_and_a_no_keeps_its_note(job_db, monkeypatch):
    windows = Windows(("no", "not every hour"))
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: windows)
    assert await approvals.JobConfirmations("conv", job_id="job-1").schedule("Brief", "every: 3600") is False
    [card] = windows.cards
    assert (card["type"], card["name"], card["options"]) == ("propose_schedule", "Brief", ["once", "conversation"])
    decision = permissions.LAST_DECISION.get()
    assert (decision.by, decision.note) == ("user", "not every hour")
    [row] = await _ledger(job_db)
    assert (row.job_id, row.kind, row.decision) == ("job-1", "schedule", "deny")


async def test_a_jobs_remote_and_sandbox_cards_stay_plain_cards(job_db, monkeypatch):
    windows = Windows(("yes", "always"), ("yes", "always"))
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: windows)
    job = approvals.JobConfirmations("conv", job_id="job-1")
    assert await job.command("git", ["status"], remote_host="box") is True
    assert await job.command("touch ~/Downloads/a", [], sandbox="retry") is True
    assert [c.get("remote_host") for c in windows.cards] == ["box", None]
    assert windows.cards[1]["sandbox"] == "retry"
    assert not any("options" in c for c in windows.cards)      # one answer each, nothing to remember


def test_hands_tools_still_imports_first_in_a_fresh_interpreter():
    """hands_tools.CARD_S follows approvals.TIMEOUT_S (test_tools_that_wait_for_the_user pins the
    two equal), so hands_tools imports approvals at the top: it must still import before anything
    else of the server, with no import cycle."""
    done = subprocess.run([sys.executable, "-c", "import server.registry.hands_tools"],
                          cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True,
                          timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]

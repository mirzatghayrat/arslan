"""0.1.61 §A4: cards wait 30 minutes; an answer carries a scope and a note; identical requests
share one card; the phone and the island answer once only; a job asks like a window."""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from server.db.models import PermissionGrant
from server.services import approvals, permission_store, permissions, run_registry, settings_service
from server.ws import protocol


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


@pytest.mark.parametrize("options", [("once", "conversation", "always"), ("task", "conversation", "always"),
                                     ("task", "conversation"), ("once",)])
async def test_a_yes_without_a_scope_gets_the_cards_first_choice_only(monkeypatch, options):
    """C2c: a yes with no scope it offered (a client older than 0.1.61 PR 2b, its old "remember"
    ticked or not) gets the card's first, narrowest choice: never widened to the conversation or
    Always, as `_legacy_scope` used to widen a ticked "remember"."""
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    for i, reply in enumerate([{"remember": True}, {"remember": False}, {}]):
        p = approvals.open_card("conv", frame(f"c{i}", dedupe=f"d{i}", options=options))
        approvals.answer({"type": "confirm_action", "call_id": f"c{i}", **reply})
        assert approvals.close_card(p)["scope"] == options[0], reply


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
    assert approvals.decline_pending({"c1"}, "actually, open Mail first", source="mac") == 1
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
    # S2a-2: `rm old.txt` is layer ③; with no sandbox around it the card is this time or this conversation.
    assert card["options"] == ["once", "conversation"] and not card.get("always_label")
    # A job's grants are its conversation's: the next job in it is not asked again.
    assert await approvals.JobConfirmations("conv", job_id="job-2").command("rm old.txt", []) is True
    assert len(windows.cards) == 1
    assert [(r.job_id, r.kind, r.decided_by, r.scope) for r in await _ledger(job_db)] == [
        ("job-1", "command", "user", "conversation"), ("job-2", "command", "grant", "conversation")]


async def test_always_on_a_job_rule_card_stores_nothing_and_the_next_job_is_asked(job_db, monkeypatch):
    """S2a-2: a rule card is layer ②, this time only: a stray "always" (the card never offered it)
    stores no rule, and the same command in the next job shows its card again."""
    windows = Windows(("yes", "always"), ("yes", "once"))
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: windows)
    assert await approvals.JobConfirmations("conv", job_id="job-1").command("git push origin main", []) is True
    assert windows.cards[0]["options"] == ["once"]
    async with job_db() as db:
        assert await permission_store.list_rules(db, "legacy_rule") == []
    assert await approvals.JobConfirmations("other", job_id="job-2").command("git push origin main", []) is True
    assert len(windows.cards) == 2


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


# ── pre-review rulings (2026-10-12): merge only identical asks; phone/island answer once only ──

async def _until(predicate, seconds=3.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while not predicate():
        assert loop.time() < deadline, "condition not reached"
        await asyncio.sleep(0.01)


def _shown(sent):
    return [f for f in sent if f["type"].startswith("propose_")]


ASKS = {
    "two commands under one rule": (lambda j: j.command("rm a.txt", []), lambda j: j.command("rm b.txt", [])),
    "two schedules, two names": (lambda j: j.schedule("Brief", "daily"), lambda j: j.schedule("Digest", "daily")),
    "two schedules, two times": (lambda j: j.schedule("Brief", "daily"), lambda j: j.schedule("Brief", "weekly")),
    "two writes, two paths": (lambda j: j.workspace_write("write_file", "a.txt"),
                              lambda j: j.workspace_write("write_file", "b.txt")),
    # The card shows the action too (review M2): writing a file is not editing it.
    "two writes, two actions": (lambda j: j.workspace_write("write_file", "a.txt"),
                                lambda j: j.workspace_write("edit_file", "a.txt")),
}


@pytest.mark.parametrize("asks", ASKS.values(), ids=ASKS.keys())
async def test_two_different_asks_never_share_a_card(job_db, monkeypatch, asks):
    """One answer must never approve what its card did not show. Seen in a probe (2026-10-12):
    `rm a.txt` and `rm b.txt` from two jobs (both under the rule "delete") were one card showing
    `rm a.txt`, and one "Once" ran both."""
    sent = []
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: sent.append)
    first = asyncio.ensure_future(asks[0](approvals.JobConfirmations("conv", job_id="job-a")))
    await _until(lambda: len(_shown(sent)) == 1)
    second = asyncio.ensure_future(asks[1](approvals.JobConfirmations("conv", job_id="job-b")))
    await _until(lambda: len(_shown(sent)) == 2 or any(p.waiters > 1 for p in approvals._pending.values()))
    cards = _shown(sent)
    assert len(cards) == 2, "the second ask joined the card of the first"
    kind = cards[0]["type"].removeprefix("propose_")
    approvals.answer({"type": f"confirm_{kind}", "call_id": cards[0]["call_id"], "scope": "once"})
    approvals.answer({"type": f"cancel_{kind}", "call_id": cards[1]["call_id"]})
    assert (await first, await second) == (True, False)


async def test_two_identical_asks_from_two_jobs_share_one_card_and_one_answer(job_db, monkeypatch):
    sent = []
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: sent.append)
    first = asyncio.ensure_future(approvals.JobConfirmations("conv", job_id="job-a").command("rm a.txt", []))
    await _until(lambda: len(_shown(sent)) == 1)
    second = asyncio.ensure_future(approvals.JobConfirmations("conv", job_id="job-b").command("rm a.txt", []))
    await _until(lambda: any(p.waiters == 2 for p in approvals._pending.values()))
    [card] = _shown(sent)
    approvals.answer({"type": "confirm_run_command", "call_id": card["call_id"], "scope": "once"})
    assert (await first, await second) == (True, True)
    assert [f["type"] for f in sent].count("card_resolved") == 1
    assert sorted((r.job_id, r.decided_by, r.scope) for r in await _ledger(job_db)) == [
        ("job-a", "user", "once"), ("job-b", "user", "once")]


@pytest.mark.parametrize("source", ["phone", "island"])
async def test_a_phone_or_island_answer_carries_no_remember(monkeypatch, source):
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    p = approvals.open_card("conv", frame(options=("once", "conversation", "always")))
    approvals.answer({"type": "confirm_action", "call_id": "c1", "remember": True, "scope": "always",
                      "source": source})
    d = approvals.close_card(p)
    assert (d["approved"], d["scope"], d["remember"]) == (True, "once", False)


@pytest.mark.parametrize("by", ["phone", "island"])
async def test_decide_takes_only_the_first_choice_from_a_phone_or_the_island(job_db, by):
    async def phone(frame):                       # any surface: decide clamps as well
        return {"approved": True, "scope": "always", "note": "", "by": by}
    with permissions.asking_with(phone):
        d = await permissions.decide(permissions.Request(kind="app", target="com.apple.Notes",
                                                         title="Use Notes?", always_label="Notes"),
                                     permissions.Context(conversation_id="conv", task_id="turn-1"))
    assert (d.allowed, d.scope) == (True, "task")
    async with job_db() as db:
        assert await permission_store.list_rules(db) == []
        grants = (await db.scalars(select(PermissionGrant))).all()
    assert [(g.task_id, g.target) for g in grants] == [("turn-1", "com.apple.Notes")]   # never the conversation


@pytest.mark.parametrize("source", ["phone", "island"])
@pytest.mark.parametrize("reply", [{"scope": "always"}, {"scope": "conversation"}, {"remember": True}],
                         ids=["always", "conversation", "remember"])
async def test_a_phone_or_island_yes_on_a_job_card_stores_no_rule_and_no_grant(job_db, monkeypatch,
                                                                                source, reply):
    def phone(f):
        if f["type"] == "propose_run_command":
            approvals.answer({"type": "confirm_run_command", "call_id": f["call_id"], "source": source,
                              **reply})
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: phone)
    assert await approvals.JobConfirmations("conv", job_id="job-1").command("rm old.txt", []) is True
    async with job_db() as db:
        assert await permission_store.list_rules(db) == []
        assert (await db.scalars(select(PermissionGrant))).all() == []
    [row] = await _ledger(job_db)
    assert (row.decided_by, row.scope) == ("user", "once")


# ── review fix round 1: merge guards, the job surface's waits, small rules, judge, provenance ──

async def test_identical_asks_in_two_conversations_get_two_cards(monkeypatch):
    sent = []
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: sent.append((cid, f["call_id"]))))
    a = approvals.open_card("conv-a", frame("c1"))
    b = approvals.open_card("conv-b", frame("c2"))             # an answer in A must never approve B
    assert a is not b and sent == [("conv-a", "c1"), ("conv-b", "c2")]


async def test_an_ask_after_the_answer_gets_a_card_of_its_own(monkeypatch):
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    a = approvals.open_card("conv", frame("c1"))
    approvals.answer({"type": "confirm_action", "call_id": "c1", "scope": "task"})
    b = approvals.open_card("conv", frame("c2"))               # the first waiter has not woken yet
    assert b is not a and not b.future.done()


async def test_a_card_an_identical_ask_joined_expires_for_every_waiter_at_the_time_it_showed(monkeypatch):
    """PR 2b plan review: the joiner waits only what is left of the card's time, not a fresh
    30 minutes — the card must not outlive the expiry it shows — and every waiter reads it as
    expired together. (A job that only gives up — it was stopped — still leaves the card to the
    others: `test_a_stopped_job_leaves_a_shared_card_to_the_other`.)"""
    sent = []
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: sent.append)
    monkeypatch.setattr(approvals, "TIMEOUT_S", 0.6)
    loop = asyncio.get_running_loop()
    started = loop.time()

    async def ask(call_id):
        decision = await approvals.BroadcastAsker("conv")(frame(call_id))
        return decision, loop.time() - started
    first = asyncio.ensure_future(ask("c1"))
    await asyncio.sleep(0.3)
    monkeypatch.setattr(approvals, "TIMEOUT_S", 5)              # a fresh wait would outlive the card
    second = asyncio.ensure_future(ask("c2"))
    await asyncio.sleep(0)
    assert approvals.waiters("c1") == 2
    (a, a_at), (b, b_at) = await first, await second
    assert (a["by"], b["by"], b["call_id"]) == (None, None, "c1")
    assert b_at < 1.0 and abs(a_at - b_at) < 0.15, (a_at, b_at)
    assert approvals.known_ids() == set()
    assert [f for f in sent if f["type"] == "card_resolved"] == [
        protocol.card_resolved("c1", "expired", None)]


async def test_a_step_of_the_system_clock_never_changes_how_long_a_card_waits(monkeypatch):
    """Review M1 (P6): a card's time runs on the monotonic clock, like the waits on it. The wall
    clock stepping back an hour must not stretch it; stepping forward must not end it."""
    import time as clock
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    p = approvals.open_card("conv", frame("c1"))
    real = clock.time
    monkeypatch.setattr(clock, "time", lambda: real() - 3600)
    assert approvals.remaining(p) <= approvals.TIMEOUT_S
    monkeypatch.setattr(clock, "time", lambda: real() + 3600)
    assert approvals.remaining(p) > approvals.TIMEOUT_S - 60
    assert approvals.open_card("conv", frame("c2")) is p           # still joined: not over
    monkeypatch.setattr(clock, "time", real)
    approvals.close_card(p)
    approvals.close_card(p)


async def test_no_answer_lands_after_the_time_a_card_showed(monkeypatch):
    """Review M2: between a card's expiry and its waiters waking, an answer is too late — from a
    window, the Inbox or typing — so every waiter reads it as expired, as the card said."""
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    monkeypatch.setattr(approvals, "TIMEOUT_S", 0.05)
    p = approvals.open_card("conv", frame("c1"))
    await asyncio.sleep(0.1)                                       # its time is up; nobody woke
    approvals.answer({"type": "confirm_action", "call_id": "c1", "scope": "task"})
    assert not p.future.done()
    assert approvals.answer_by_id("c1", True, source="inbox") is False      # "answered or expired"
    assert approvals.decline_pending({"c1"}, "too late", source="mac") == 0
    assert approvals.close_card(p)["by"] is None


async def test_an_ask_after_a_cards_time_is_up_gets_a_card_of_its_own(monkeypatch):
    """A card whose time is up but whose waiter has not woken yet is not joined: the new ask would
    read as expired without ever being shown."""
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    monkeypatch.setattr(approvals, "TIMEOUT_S", 0.05)
    a = approvals.open_card("conv", frame("c1"))
    await asyncio.sleep(0.1)
    b = approvals.open_card("conv", frame("c2"))
    assert b is not a and b.call_id == "c2" and a.waiters == 1


async def test_the_inbox_lists_a_card_until_the_time_its_first_ask_showed(monkeypatch):
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    a = approvals.open_card("conv", frame("c1"))
    monkeypatch.setattr(approvals, "TIMEOUT_S", 5)
    approvals.open_card("conv", frame("c2"))                   # joins: the card's time is unchanged
    [listed] = approvals.all_pending()
    assert listed["expires_at"] == a.opened_at + 1800


async def test_a_job_stopped_while_its_card_waits_leaves_no_card(monkeypatch):
    sent = []
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: sent.append)
    waiting = asyncio.ensure_future(approvals.BroadcastAsker("conv")(frame("c1")))
    await asyncio.sleep(0)
    assert [p["call_id"] for p in approvals.all_pending()] == ["c1"]
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert approvals.all_pending() == [] and approvals.known_ids() == set()
    assert (sent[-1]["type"], sent[-1]["outcome"]) == ("card_resolved", "expired")


async def test_a_stopped_job_leaves_a_shared_card_to_the_other(monkeypatch):
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    a = asyncio.ensure_future(approvals.BroadcastAsker("conv")(frame("c1")))
    await asyncio.sleep(0)
    b = asyncio.ensure_future(approvals.BroadcastAsker("conv")(frame("c2")))
    await asyncio.sleep(0)
    a.cancel()
    with pytest.raises(asyncio.CancelledError):
        await a
    assert "c1" in approvals.known_ids()
    approvals.answer({"type": "confirm_action", "call_id": "c1"})
    assert (await b)["approved"] is True and approvals.known_ids() == set()


def _cmd(shell: str, *, ask_all: bool = False):
    from server.services import terminal_policy
    return approvals._command_request(shell, sorted(terminal_policy.ask_rules(shell)), None, ask_all=ask_all)


def test_a_commands_target_says_whether_it_is_a_rule_set_or_one_text():
    """Review I3: `rules:<rules>` for a command that matched ask-rules, `text:<command>` for one
    that matched none — namespaces that never meet. S2a-2 adds `unsandboxed:*`, layer ③ with no
    sandbox around it."""
    assert _cmd("rm -rf ~/build").target == "rules:delete-outside"
    assert _cmd("git push origin main").target == "rules:git-push"
    assert _cmd("rm -rf build").target == "unsandboxed:*"
    assert _cmd("git-push").target == "unsandboxed:*"
    assert _cmd("git-push", ask_all=True).target == "text:git-push"
    assert _cmd("git status", ask_all=True).target == "text:git status"


async def test_this_conversation_on_a_command_named_like_a_rule_never_covers_that_rule(job_db):
    """Review P2b: in Careful mode, "In this conversation" on a card reading "Run `git-push`?" (a
    command that matched no rule) must not let `git push origin main` run with no card."""
    async def conversation(frame):
        return {"approved": True, "scope": "conversation", "note": "", "by": "mac"}

    async def declines(frame):
        return {"approved": False, "scope": None, "note": "", "by": "mac"}
    ctx = permissions.Context(conversation_id="conv")
    with permissions.asking_with(conversation):
        assert (await permissions.decide(_cmd("git-push"), ctx)).scope == "conversation"
    with permissions.asking_with(declines):
        assert (await permissions.decide(_cmd("git push origin main"), ctx)).by == "user"   # asked


@pytest.mark.parametrize("shell", ["rm -rf build", "git status"])
async def test_a_command_grant_is_found_again_under_its_own_target(job_db, shell):
    """Both forms round-trip through the store: the same command is covered next time, and the
    grant is kept under the namespaced target."""
    async def conversation(frame):
        return {"approved": True, "scope": "conversation", "note": "", "by": "mac"}
    ctx = permissions.Context(conversation_id="conv")
    with permissions.asking_with(conversation):
        await permissions.decide(_cmd(shell), ctx)
    async def no_card(frame):
        raise AssertionError("the grant must answer: no card")
    with permissions.asking_with(no_card):     # S1 (U14 a): a grant answers only where someone could be asked
        assert (await permissions.decide(_cmd(shell), ctx)).by == "grant"
    async with job_db() as db:
        targets = [g.target for g in (await db.scalars(select(PermissionGrant))).all()]
    assert targets == [_cmd(shell).target]


async def test_a_conversation_grant_outside_the_sandbox_never_covers_a_rule(job_db, monkeypatch):
    """S2a-2: `rm a.txt` (layer ③, no sandbox) allowed for the conversation must not wave
    `rm -rf ~/build` (delete-outside, layer ②) through: their targets never meet."""
    shown = []

    def window(f):
        if f["type"] == "propose_run_command":
            shown.append(f["command"])
            approvals.answer({"type": "confirm_run_command", "call_id": f["call_id"], "scope": "conversation"})
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: window)
    assert await approvals.JobConfirmations("conv", job_id="job-1").command("rm a.txt", []) is True
    assert await approvals.JobConfirmations("conv", job_id="job-2").command("rm -rf ~/build", []) is True
    assert shown == ["rm a.txt", "rm -rf ~/build"]


async def test_a_declined_plain_job_card_reads_declined(monkeypatch):
    def window(f):
        if f["type"].startswith("propose_"):
            approvals.answer({"type": "cancel_run_command", "call_id": f["call_id"]})
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: window)
    assert await approvals.JobConfirmations("c").command("touch ~/Downloads/a", [], sandbox="retry") is False
    assert approvals.LAST_OUTCOME.get() == "declined"                # expired is not declined, nor back


async def test_an_answer_by_nobody_never_allows(job_db):
    async def ghost(frame):
        return {"approved": True, "scope": "once", "note": "", "by": None}
    with permissions.asking_with(ghost):
        d = await permissions.decide(permissions.Request(kind="schedule", target="*", title="Schedule?"),
                                     permissions.Context(conversation_id="conv"))
    assert (d.allowed, d.by) == (False, "expired")


async def test_a_yes_has_no_note(monkeypatch):
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    p = approvals.open_card("conv", frame("c1"))
    approvals.answer({"type": "confirm_action", "call_id": "c1", "note": "only on a no"})
    assert approvals.close_card(p)["note"] == ""


async def test_decline_pending_leaves_a_card_someone_else_also_waits_on(monkeypatch):
    """Task 4 carry (M7): a message typed in a window declines only the cards every waiter of
    which is that window's; a card a job also waits on stays open for the job."""
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    shared = approvals.open_card("conv", frame("c1"), broadcast=False)    # the window's card...
    approvals.open_card("conv", frame("c9"))                               # ...a job joins it
    own = approvals.open_card("conv", frame("c2", dedupe="own"), broadcast=False)
    assert shared.waiters == 2
    assert approvals.decline_pending({"c1", "c2"}, "not that one", source="mac",
                                     mine={"c1": 1, "c2": 1}) == 1
    assert not shared.future.done() and own.future.done()
    assert approvals.decline_pending({"c1"}, "both of mine", source="mac", mine={"c1": 2}) == 1  # all its
    assert shared.future.result()["note"] == "both of mine"


async def test_a_card_declined_by_typing_on_the_phone_says_the_phone_answered(monkeypatch):
    """PR 2b plan review: a message typed on the phone during a phone turn declines its card, and
    every screen is told the phone answered — not the Mac."""
    sent = []
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: sent.append)
    p = approvals.open_card("conv", frame("c1"))                # a phone turn's card: on every screen
    assert approvals.decline_pending({"c1"}, "check the other repo", source="phone") == 1
    assert approvals.close_card(p)["by"] == "phone"
    assert sent[-1] == protocol.card_resolved("c1", "declined", "phone")
    q = approvals.open_card("conv", frame("c2", dedupe="q"))
    approvals.decline_pending({"c2"}, "x", source="somewhere")   # unknown, as in `answer`: the Mac
    assert approvals.close_card(q)["by"] == "mac"


async def test_decline_pending_skips_a_decided_card_and_cuts_the_note(monkeypatch):
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    p = approvals.open_card("conv", frame("c1"))
    approvals.answer({"type": "confirm_action", "call_id": "c1"})
    assert approvals.decline_pending({"c1"}, "too late", source="mac") == 0   # answered already: no raise
    q = approvals.open_card("conv", frame("c2", dedupe="q"))
    assert approvals.decline_pending({"c2"}, "n" * 600, source="mac") == 1
    assert len(approvals.close_card(q)["note"]) == 500
    approvals.close_card(p)


def _answering(shown: list, scope: str | None):
    """A card UI that says yes to every card it is shown — with this scope, or with none at all."""
    def ui(f):
        if f["type"].startswith("propose_"):
            shown.append(f)
            approvals.answer({"type": "confirm_" + f["type"].removeprefix("propose_"), "call_id": f["call_id"],
                              **({"scope": scope} if scope else {})})
    return ui


async def test_the_card_ui_s_in_this_conversation_holds_for_the_conversation(job_db, monkeypatch):
    """0.1.61 PR 2b: the UI sends the scope the user chose. "In this conversation" on a write card:
    a job writing three files asks once; a schedule allowed so in one job holds for the next."""
    shown: list = []
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: _answering(shown, "conversation"))
    job = approvals.JobConfirmations("conv", job_id="job-1")
    for name in ("a.txt", "b.txt", "c.txt"):
        assert await job.workspace_write("write_file", name) is True
    assert len(shown) == 1
    assert await job.schedule("Brief", "daily") is True
    assert await approvals.JobConfirmations("conv", job_id="job-2").schedule("Brief", "daily") is True
    assert [f["type"] for f in shown] == ["propose_workspace_write", "propose_schedule"]


async def test_a_yes_with_no_scope_on_a_write_card_holds_this_once_only(job_db, monkeypatch):
    """PR 2b removed the stop-gap that read a scope-less yes on a write or schedule card as "in this
    conversation": such a yes (a tab from before the update) is the card's first choice, once —
    narrower, never wider. Each write asks again."""
    shown: list = []
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: _answering(shown, None))
    job = approvals.JobConfirmations("conv", job_id="job-1")
    for name in ("a.txt", "b.txt"):
        assert await job.workspace_write("write_file", name) is True
    assert [f["type"] for f in shown] == ["propose_workspace_write", "propose_workspace_write"]


# A yes that carries no scope (re-review N1, then PR 2b): the card's first choice on every card,
# the phone and the island clamped to it first.
CARDS = {
    "write": (lambda cid: protocol.propose_workspace_write(cid, "/w", "write_file", "a.txt"), ["once", "conversation"]),
    "schedule": (lambda cid: protocol.propose_schedule(cid, "Brief", "daily"), ["once", "conversation"]),
    "command": (lambda cid: protocol.propose_run_command(cid, "rm", ["a"], reason="x"), ["once", "conversation", "always"]),
    "app": (lambda cid: protocol.propose_action(cid, "app", "Notes", ""), ["task", "conversation", "always"]),
    # A once-only kind (money, a takeover…): the card offers nothing but "once".
    "money": (lambda cid: protocol.propose_action(cid, "desktop_risky", "Mail · Pay", "") | {"perm_kind": "money"}, ["once"]),
}
#: What a bare yes, or a yes with a scope the card did not offer, becomes on each card: its first choice.
FIRST_CHOICE = {"command": "once", "app": "task", "write": "once", "schedule": "once", "money": "once"}
assert FIRST_CHOICE.keys() == CARDS.keys()


def _open(kind: str) -> approvals.Pending:
    build, options = CARDS[kind]
    return approvals.open_card("conv", {**build("c1"), "options": options, "dedupe": kind})


def _bare_yes(pending: approvals.Pending, source: str, **extra) -> None:
    """A yes with no scope and no "remember": what the island and the phone send (they never send a scope),
    and what a window or the Inbox sends when it is an old tab or a script; from a window, or by id from the Inbox."""
    if source == "inbox":
        approvals.answer_by_id(pending.call_id, True, source="inbox", **extra)
        return
    approvals.answer({"type": "confirm_" + pending.frame["type"].removeprefix("propose_"),
                      "call_id": pending.call_id, **({} if source == "mac" else {"source": source}), **extra})


@pytest.mark.parametrize("source", ["mac", "inbox"])
@pytest.mark.parametrize("kind,first", sorted(FIRST_CHOICE.items()))
async def test_a_bare_yes_on_any_card_is_its_first_choice(monkeypatch, source, kind, first):
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    p = _open(kind)
    _bare_yes(p, source)
    assert approvals.close_card(p)["scope"] == first


@pytest.mark.parametrize("source", ["phone", "island"])
@pytest.mark.parametrize("kind", ["write", "schedule"])
async def test_a_phone_or_island_yes_on_a_write_or_schedule_card_is_once(monkeypatch, source, kind):
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    p = _open(kind)
    _bare_yes(p, source)                                        # the clamp comes first
    d = approvals.close_card(p)
    assert (d["scope"], d["remember"]) == ("once", False)


@pytest.mark.parametrize("source", ["mac", "inbox"])
@pytest.mark.parametrize("kind,forged", [
    ("write", "always"), ("schedule", "always"), ("command", "task"), ("app", "once"), ("app", "forever"),
    # a once-only card offers nothing but "once": a forged wider scope stays "once"
    ("money", "always"), ("money", "conversation"), ("money", "task"),
])
async def test_an_unoffered_scope_on_any_card_is_its_first_choice(monkeypatch, source, kind, forged):
    """A scope the card did not offer is not "no scope": the card falls to its first choice, on every kind of card."""
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    p = _open(kind)
    _bare_yes(p, source, scope=forged)
    d = approvals.close_card(p)
    assert (d["scope"], d["remember"]) == (FIRST_CHOICE[kind], False)


@pytest.mark.parametrize("source", ["mac", "inbox"])
@pytest.mark.parametrize("kind", ["write", "schedule"])
async def test_a_yes_with_its_scope_on_a_write_or_schedule_card_keeps_it(monkeypatch, source, kind):
    """What PR 2b's window and Inbox send: the scope the user picked on the card."""
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    p = _open(kind)
    _bare_yes(p, source, scope="conversation")
    assert approvals.close_card(p)["scope"] == "conversation"


async def _judgments(maker, count: int, seconds: float = 5.0) -> list:
    """The shadow judgments, once `count` of them have their outcome (both are written later)."""
    from server.db.models import Judgment
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while True:
        async with maker() as db:
            rows = (await db.scalars(select(Judgment))).all()
        if (len([r for r in rows if r.outcome]) >= count) or loop.time() > deadline:
            await asyncio.sleep(0.3)                  # a stray extra row would have landed by now
            async with maker() as db:
                return (await db.scalars(select(Judgment))).all()
        await asyncio.sleep(0.05)


@pytest.fixture
def judge(monkeypatch):
    """The judge model, counted (no network)."""
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


async def test_a_jobs_cards_show_only_what_needs_asking_and_none_is_judged(job_db, judge, monkeypatch):
    """Review M1: a command a grant allows shows no card; a card nobody answered stops the job's
    later cards. C4: no card is shadow-judged any more: no model call, no judgments row."""
    windows = Windows(("yes", "conversation"), None)
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: windows)
    assert await approvals.JobConfirmations("conv", job_id="job-1").command("rm old.txt", []) is True
    assert await approvals.JobConfirmations("conv", job_id="job-2").command("rm old.txt", []) is True
    monkeypatch.setattr(approvals, "TIMEOUT_S", 0.05)
    # A rule, so the grant outside the sandbox does not cover it: a card, and nobody answers.
    away = approvals.JobConfirmations("conv", job_id="job-3")
    assert await away.command("git push origin main", []) is False
    assert await away.command("git push origin dev", []) is False    # the job stopped waiting: no card
    assert len(windows.cards) == 2
    assert await _judgments(job_db, 0) == [] and judge == []


async def test_a_merged_ask_shows_one_card_and_is_not_judged(job_db, judge, monkeypatch):
    sent = []
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: sent.append)
    first = asyncio.ensure_future(approvals.JobConfirmations("conv", job_id="job-a").command("rm a.txt", []))
    await _until(lambda: len(_shown(sent)) == 1)
    second = asyncio.ensure_future(approvals.JobConfirmations("conv", job_id="job-b").command("rm a.txt", []))
    await _until(lambda: any(p.waiters == 2 for p in approvals._pending.values()))
    [card] = _shown(sent)
    approvals.answer({"type": "confirm_run_command", "call_id": card["call_id"], "scope": "once"})
    assert (await first, await second) == (True, True)
    assert await _judgments(job_db, 0) == [] and judge == []          # C4: no shadow judgment


async def test_a_merged_ask_records_the_card_the_user_answered(job_db, monkeypatch):
    """Review M5: provenance (a grant's call_id, a rule's created_from) is the card shown, also
    for an ask that joined it — not the ask's own, never-shown call_id."""
    sent = []
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: sent.append)
    notes = permissions.Request(kind="app", target="com.apple.Notes", title="Use Notes?", always_label="Notes")

    async def job(job_id):
        with permissions.asking_with(approvals.BroadcastAsker("conv")):
            return await permissions.decide(notes, permissions.Context(conversation_id="conv", job_id=job_id))
    first = asyncio.ensure_future(job("job-a"))
    await _until(lambda: len(_shown(sent)) == 1)
    second = asyncio.ensure_future(job("job-b"))
    await _until(lambda: any(p.waiters == 2 for p in approvals._pending.values()))
    [card] = _shown(sent)
    approvals.answer({"type": "confirm_action", "call_id": card["call_id"], "scope": "task"})
    assert [(await first).scope, (await second).scope] == ["task", "task"]
    async with job_db() as db:
        grants = (await db.scalars(select(PermissionGrant))).all()
    assert sorted((g.task_id, g.call_id) for g in grants) == [("job-a", card["call_id"]),
                                                               ("job-b", card["call_id"])]


def test_hands_tools_still_imports_first_in_a_fresh_interpreter():
    """hands_tools.CARD_S follows approvals.TIMEOUT_S (test_tools_that_wait_for_the_user pins the
    two equal), so hands_tools imports approvals at the top: it must still import before anything
    else of the server, with no import cycle."""
    done = subprocess.run([sys.executable, "-c", "import server.registry.hands_tools"],
                          cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True,
                          timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]


# ── final-review fix wave: F4 ────────────────────────────────────────────────

async def test_two_asks_that_would_store_different_rules_get_two_cards(job_db, monkeypatch):
    """F4 (final review m1): two asks equal in everything their cards show, but one would store a
    second app's rule under "Always". They are not identical: each gets its own card, and "Always"
    on the first stores only its own rule."""
    sent = []
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: sent.append)
    notes = permissions.Request(kind="app", target="com.apple.Notes", title="Use Notes?",
                                always_label="Notes")
    wider = permissions.Request(kind="app", target="com.apple.Notes", title="Use Notes?",
                                always_label="Notes",
                                remember_as=(("app", "com.apple.Notes"), ("app", "com.apple.mail")))

    async def job(req, job_id):
        with permissions.asking_with(approvals.BroadcastAsker("conv")):
            return await permissions.decide(req, permissions.Context(conversation_id="conv", job_id=job_id))
    first = asyncio.ensure_future(job(notes, "job-a"))
    await _until(lambda: len(_shown(sent)) == 1)
    second = asyncio.ensure_future(job(wider, "job-b"))
    await _until(lambda: len(_shown(sent)) == 2 or any(p.waiters > 1 for p in approvals._pending.values()))
    cards = _shown(sent)
    assert len(cards) == 2, "the wider ask joined the card of the narrower one"
    approvals.answer({"type": "confirm_action", "call_id": cards[0]["call_id"], "scope": "always"})
    approvals.answer({"type": "cancel_action", "call_id": cards[1]["call_id"]})
    assert ((await first).allowed, (await second).allowed) == (True, False)
    async with job_db() as db:
        assert [r.target for r in await permission_store.list_rules(db, "app")] == ["com.apple.Notes"]

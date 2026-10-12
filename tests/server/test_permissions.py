"""0.1.61 §3/§A11: one decide() — money, rule, grant, card; nobody to ask means no."""
from __future__ import annotations

import contextlib
import json
import logging
import time
from pathlib import Path

import pytest
import sqlalchemy as sa

from server.db import session as db_session
from server.db.models import PermissionGrant
from server.services import approvals, permission_store, permissions, settings_service
from server.services.permissions import Context, Request
from server.ws import protocol


class Asker:
    """A card surface that answers as told and records the frames it was shown."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.frames: list[dict] = []

    async def __call__(self, frame):
        self.frames.append(frame)
        return self.answers.pop(0)


def yes(scope=None, note=""):
    return {"approved": True, "scope": scope, "note": note, "by": "mac"}


def no(note=""):
    return {"approved": False, "scope": None, "note": note, "by": "mac"}


EXPIRED = {"approved": False, "scope": None, "note": "", "by": None}
CTX = Context(conversation_id="conv-1", task_id="turn-1")


def app(bundle="com.apple.Notes"):
    return Request(kind="app", target=bundle, title="Use Notes?", always_label="Notes")


@pytest.fixture(autouse=True)
def _fresh(execution_db):                   # the fresh-database fixture Task 1's tests use
    permission_store._reset_for_tests()
    yield


async def test_options_follow_the_spec_table():
    assert permissions.options_for(app()) == ["task", "conversation", "always"]
    assert permissions.options_for(Request(kind="schedule", target="*", title="t")) == ["once", "conversation"]
    assert permissions.options_for(Request(kind="money", target="x", title="t", always_label="x")) == ["once"]
    assert permissions.options_for(Request(kind="destructive", target="x", title="t", always_label="x")) \
        == ["once", "conversation"]
    assert permissions.options_for(Request(kind="command", target="delete", title="t")) == ["once", "conversation"]
    assert permissions.options_for(Request(kind="command", target="delete", title="t",
                                           always_label="deletes files")) == ["once", "conversation", "always"]


async def test_a_card_answer_for_the_task_covers_the_next_step_of_that_task_only():
    asker = Asker(yes("task"))
    with permissions.asking_with(asker):
        first = await permissions.decide(app(), CTX)
        again = await permissions.decide(app(), CTX)
    assert (first.allowed, first.by, first.scope) == (True, "user", "task")
    assert (again.allowed, again.by, again.scope) == (True, "grant", "task")
    assert len(asker.frames) == 1
    frame = asker.frames[0]
    assert frame["options"] == ["task", "conversation", "always"]
    assert frame["always_label"] == "Notes" and frame["title"] == "Use Notes?"
    assert frame["expires_at"] > 0 and frame["call_id"]
    other_task = Asker(no())
    with permissions.asking_with(other_task):
        later = await permissions.decide(app(), Context(conversation_id="conv-1", task_id="turn-2"))
    assert later.allowed is False and len(other_task.frames) == 1


async def test_always_stores_a_rule_every_conversation_then_reads():
    with permissions.asking_with(Asker(yes("always"))):
        await permissions.decide(app(), CTX)
    with permissions.asking_with(Asker()):                     # no answers left: must not ask
        d = await permissions.decide(app(), Context(conversation_id="conv-9", task_id="t"))
    assert (d.allowed, d.by, d.scope) == (True, "rule", "always")


async def test_a_scope_the_card_did_not_offer_is_the_first_option():
    with permissions.asking_with(Asker(yes("always"))):
        d = await permissions.decide(Request(kind="schedule", target="*", title="t"), CTX)
    assert d.scope == "once"
    async with db_session.AsyncSessionLocal() as db:
        assert await permission_store.find_rule(db, "schedule", "*") is None


async def test_money_always_asks_even_after_yes():
    asker = Asker(yes("once"), yes("once"))
    pay = Request(kind="money", target="com.apple.AppStore", title="Buy this app?")
    with permissions.asking_with(asker):
        await permissions.decide(pay, CTX)
        await permissions.decide(pay, CTX)
    assert len(asker.frames) == 2
    assert asker.frames[0]["options"] == ["once"]


async def test_remember_as_stores_every_rule_a_command_matched():
    req = Request(kind="command", target="delete|hermes:recursive delete", title="Run rm -rf build?",
                  always_label="deletes files, recursive delete",
                  remember_as=(("legacy_rule", "delete"), ("legacy_rule", "hermes:recursive delete")))
    with permissions.asking_with(Asker(yes("always"))):
        await permissions.decide(req, CTX)
    async with db_session.AsyncSessionLocal() as db:
        rules = {r.target for r in await permission_store.list_rules(db, "legacy_rule")}
    assert rules == {"delete", "hermes:recursive delete"}


async def test_an_expired_card_is_not_a_refusal():
    with permissions.asking_with(Asker(EXPIRED)):
        d = await permissions.decide(app(), CTX)
    assert (d.allowed, d.by) == (False, "expired")
    assert "NOT a refusal" in d.model_text
    assert permissions.LAST_DECISION.get() is d
    assert approvals.LAST_OUTCOME.get() == "expired"
    async with db_session.AsyncSessionLocal() as db:
        [event] = await permission_store.recent(db)
    assert (event.decided_by, event.decision) == ("expired", "expired")


async def test_no_carries_the_users_words_to_the_model():
    with permissions.asking_with(Asker(no("use the Downloads copy instead"))):
        d = await permissions.decide(app(), CTX)
    assert (d.allowed, d.by, d.note) == (False, "user", "use the Downloads copy instead")
    assert "use the Downloads copy instead" in d.model_text


async def test_no_surface_means_no_at_once_and_is_recorded():
    d = await permissions.decide(Request(kind="schedule", target="*", title="Schedule “digest”?"),
                                 Context(conversation_id="conv-1"))
    assert (d.allowed, d.by) == (False, "policy")
    async with db_session.AsyncSessionLocal() as db:
        [event] = await permission_store.recent(db)
    assert (event.kind, event.decided_by, event.decision) == ("schedule", "policy", "deny")


async def test_every_decision_is_one_ledger_row_with_its_scope_and_wait():
    with permissions.asking_with(Asker(yes("conversation"))):
        await permissions.decide(app(), CTX)
        await permissions.decide(app(), CTX)
    async with db_session.AsyncSessionLocal() as db:
        events = list(reversed(await permission_store.recent(db)))
    assert [(e.decided_by, e.decision, e.scope) for e in events] == [
        ("user", "allow", "conversation"), ("grant", "allow", "conversation")]
    assert events[0].wait_ms is not None and events[1].wait_ms is None
    assert events[0].conversation_id == "conv-1" and events[0].mode == "standard"


async def test_decide_many_asks_once_for_the_apps_not_yet_allowed():
    with permissions.asking_with(Asker(yes("always"))):
        await permissions.decide(app("com.apple.Notes"), CTX)
    asker = Asker(yes("conversation"))
    reqs = [app("com.apple.Notes"), app("com.apple.reminders"), app("com.apple.mail")]
    with permissions.asking_with(asker):
        out = await permissions.decide_many(reqs, CTX, title="Use Reminders and Mail?")
    assert [d.by for d in out] == ["rule", "user", "user"]
    assert len(asker.frames) == 1 and "com.apple.Notes" not in asker.frames[0]["detail"]
    with permissions.asking_with(Asker()):
        assert not await permissions.would_ask(app("com.apple.mail"), CTX)
        assert await permissions.would_ask(app("com.apple.Safari"), CTX)


async def test_decide_many_hides_always_when_any_app_cannot_be_remembered():
    asker = Asker(yes("conversation"))
    reqs = [app("com.apple.Notes"),
            Request(kind="app", target="com.apple.systemevents", title="t", always_label="")]
    with permissions.asking_with(asker):
        await permissions.decide_many(reqs, CTX, title="Use Notes and System Events?")
    assert "always" not in asker.frames[0]["options"]


async def test_the_context_is_filled_from_the_running_turn(monkeypatch):
    from types import SimpleNamespace
    from server.services import personal_context
    monkeypatch.setattr(personal_context, "current",
                        lambda: SimpleNamespace(task_id="turn-x", run_id="turn-turn-x", query="tidy my notes"))
    asker = Asker(yes("task"))
    with permissions.asking_with(asker):
        await permissions.decide(app(), Context(conversation_id="conv-1"))
    async with db_session.AsyncSessionLocal() as db:
        assert await permission_store.find_grant(db, "conv-1", "turn-x", "app", "com.apple.Notes")


# ── Beyond the brief's cases: what the window, jobs, Hands and the API lean on ──────────────────


async def _grant_count() -> int:
    async with db_session.AsyncSessionLocal() as db:
        return (await db.execute(sa.select(sa.func.count()).select_from(PermissionGrant))).scalar_one()


class _OpenSessions:
    """Stands in for the session maker and counts the sessions open right now, so a test can see
    whether one is held across a card."""

    def __init__(self, maker):
        self.maker, self.open, self.opened = maker, 0, 0

    def __call__(self):
        return self._session()

    @contextlib.asynccontextmanager
    async def _session(self):
        async with self.maker() as db:
            self.open += 1
            self.opened += 1
            try:
                yield db
            finally:
                self.open -= 1


# The plan's scope table (§A4): which choices a card offers for which kind. Task 5's API refuses to
# create a rule for any kind that never offers "Always".
ONCE_ONLY = ["money", "app_risky", "capability", "other_agent", "system", "opaque", "remote", "takeover"]


@pytest.mark.parametrize("kind", ONCE_ONLY)
def test_these_kinds_offer_only_this_once(kind):
    req = Request(kind=kind, target="x", title="t", always_label="x")
    assert permissions.options_for(req) == ["once"]


@pytest.mark.parametrize("kind", ["destructive", "screen", "workspace_write", "schedule"])
def test_these_kinds_never_offer_always_even_with_a_label(kind):
    req = Request(kind=kind, target="x", title="t", always_label="x")
    assert permissions.options_for(req) == ["once", "conversation"]


@pytest.mark.parametrize("kind", ["app", "shortcut"])
def test_an_app_or_a_shortcut_asks_for_the_task_first(kind):
    req = Request(kind=kind, target="x", title="t", always_label="x")
    assert permissions.options_for(req) == ["task", "conversation", "always"]


@pytest.mark.parametrize("kind", ["command", "site", "mcp_tool", "folder"])
def test_the_other_kinds_ask_once_first_and_offer_always_with_a_label(kind):
    assert permissions.options_for(Request(kind=kind, target="x", title="t", always_label="x")) \
        == ["once", "conversation", "always"]
    assert permissions.options_for(Request(kind=kind, target="x", title="t")) \
        == ["once", "conversation"]


def test_a_request_can_hide_the_conversation_choice():
    assert permissions.options_for(Request(kind="command", target="x", title="t",
                                           always_label="x", conversation_ok=False)) \
        == ["once", "always"]
    assert permissions.options_for(Request(kind="app", target="x", title="t",
                                           conversation_ok=False)) == ["task"]


async def test_a_task_answer_with_no_task_to_scope_it_to_is_once_and_stores_no_grant():
    """No turn, no job and no running task. A grant written with an empty task id is a grant for
    the whole conversation: wider than the user said."""
    with permissions.asking_with(Asker(yes("task"), no())):
        d = await permissions.decide(app(), Context(conversation_id="conv-1"))
        again = await permissions.decide(app(), Context(conversation_id="conv-1"))
    assert (d.allowed, d.by, d.scope) == (True, "user", "once")
    assert again.allowed is False                      # nothing was remembered, so it asked again
    assert await _grant_count() == 0
    async with db_session.AsyncSessionLocal() as db:
        first = (await permission_store.recent(db))[-1]
    assert (first.decided_by, first.decision, first.scope, first.grant_id) == ("user", "allow", "once", None)


@pytest.mark.parametrize("scope", ["task", "conversation"])
async def test_an_answer_for_a_conversation_nobody_has_is_once_and_stores_no_grant(scope):
    with permissions.asking_with(Asker(yes(scope))):
        d = await permissions.decide(app(), Context(conversation_id=None, task_id="turn-1"))
    assert (d.allowed, d.scope) == (True, "once")
    assert await _grant_count() == 0


async def test_no_database_session_is_open_while_a_card_waits(monkeypatch):
    """A card waits up to 30 minutes. A session open that long can hold SQLite's write lock, and
    every other writer gives up after its 5 s busy timeout."""
    sessions = _OpenSessions(db_session.AsyncSessionLocal)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", sessions)
    open_during_cards = []

    async def asker(frame):
        open_during_cards.append(sessions.open)
        async with sessions.maker() as other:          # somebody else writes while the card waits
            await permission_store.add_rule(other, "app", "com.apple.Reminders")
            await other.commit()
        return yes("conversation")

    with permissions.asking_with(asker):
        await permissions.decide(app(), CTX)
        await permissions.decide_many([app("com.apple.mail"), app("com.apple.Safari")], CTX, title="t")
    assert open_during_cards == [0, 0]


@pytest.mark.parametrize("kind", ["money", "app_risky", "takeover"])
async def test_a_once_only_kind_asks_even_if_something_was_stored_for_it(kind):
    """Defence in depth: whatever put a rule or a grant there, these are a card every time."""
    async with db_session.AsyncSessionLocal() as db:
        await permission_store.add_rule(db, kind, "com.apple.AppStore")
        await permission_store.add_grant(db, "conv-1", "", kind, "com.apple.AppStore")
        await db.commit()
    req = Request(kind=kind, target="com.apple.AppStore", title="Buy this app?")
    asker = Asker(no())
    with permissions.asking_with(asker):
        d = await permissions.decide(req, CTX)
    assert (d.allowed, d.by) == (False, "user") and len(asker.frames) == 1
    assert await permissions.would_ask(req, CTX)


async def test_a_rule_is_read_before_a_grant():
    with permissions.asking_with(Asker(yes("conversation"))):
        await permissions.decide(app(), CTX)
    async with db_session.AsyncSessionLocal() as db:
        await permission_store.add_rule(db, "app", "com.apple.Notes")
        await db.commit()
    d = await permissions.decide(app(), CTX)
    assert (d.by, d.scope) == ("rule", "always")


async def test_a_rule_that_decides_is_counted_and_would_ask_counts_nothing():
    with permissions.asking_with(Asker(yes("always"))):
        await permissions.decide(app(), CTX)
    async with db_session.AsyncSessionLocal() as db:
        rows_before = len(await permission_store.recent(db))
    assert not await permissions.would_ask(app(), CTX)                  # a peek...
    async with db_session.AsyncSessionLocal() as db:
        rule = await permission_store.find_rule(db, "app", "com.apple.Notes")
        assert (rule.use_count, rule.last_used_at) == (0, None)         # ...counts no use
        assert len(await permission_store.recent(db)) == rows_before    # ...and writes no row
    await permissions.decide(app(), CTX)                                # a decision does both
    async with db_session.AsyncSessionLocal() as db:
        rule = await permission_store.find_rule(db, "app", "com.apple.Notes")
        assert (rule.use_count, rule.last_used_at is not None) == (1, True)
        newest = (await permission_store.recent(db))[0]
        assert (newest.decided_by, newest.rule_id) == ("rule", rule.id)


async def test_the_ledger_row_says_which_mode_was_on():
    async with db_session.AsyncSessionLocal() as db:
        await settings_service.update_settings(db, {"shell_confirm_policy": "ask_all"})
    with permissions.asking_with(Asker(yes("task"))):
        await permissions.decide(app(), CTX)
    async with db_session.AsyncSessionLocal() as db:
        [event] = await permission_store.recent(db)
    assert event.mode == "careful"


async def test_a_request_with_no_frame_of_its_own_is_a_propose_action_card():
    asker = Asker(no())
    with permissions.asking_with(asker):
        await permissions.decide(Request(kind="app", target="com.apple.Notes", title="Use Notes?",
                                         detail="look at the window"), CTX)
    frame = asker.frames[0]
    assert (frame["type"], frame["kind"], frame["target"], frame["detail"]) \
        == ("propose_action", "app", "com.apple.Notes", "look at the window")


async def test_the_callers_card_frame_is_kept_and_gains_the_permission_fields():
    frame = protocol.propose_run_command("call-77", "rm", ["-rf", "build"], reason="deletes files")
    req = Request(kind="command", target="delete", title="Run rm -rf build?", why="w" * 400,
                  always_label="deletes files", frame=frame)
    asker = Asker(yes("always"))
    with permissions.asking_with(asker):
        await permissions.decide(req, CTX)
    [shown] = asker.frames
    assert (shown["type"], shown["command"], shown["call_id"]) == ("propose_run_command", "rm", "call-77")
    # Identical asks share a card: the key is everything the card shows (ruling 2026-10-12, review
    # M2): kind, target, title, detail and the caller's frame without its call_id.
    assert shown["perm_kind"] == "command"
    assert json.loads(shown["dedupe"]) == ["command", "delete", "Run rm -rf build?", "",
                                           {k: v for k, v in frame.items() if k != "call_id"}]
    assert shown["why"] == "w" * 300
    assert "options" not in frame                      # the caller's own dict is left alone
    async with db_session.AsyncSessionLocal() as db:
        rule = await permission_store.find_rule(db, "command", "delete")
    assert (rule.label, rule.created_from) == ("deletes files", "call-77")


async def test_always_is_blank_on_a_card_that_does_not_offer_it():
    asker = Asker(yes("once"))
    with permissions.asking_with(asker):
        await permissions.decide(Request(kind="destructive", target="/tmp/x", title="Delete it?",
                                         always_label="/tmp/x"), CTX)
    assert asker.frames[0]["options"] == ["once", "conversation"]
    assert asker.frames[0]["always_label"] == ""


async def test_once_is_remembered_nowhere():
    asker = Asker(yes("once"), yes("once"))
    req = Request(kind="schedule", target="*", title="Schedule “digest”?")
    with permissions.asking_with(asker):
        first = await permissions.decide(req, CTX)
        second = await permissions.decide(req, CTX)
    assert (first.scope, second.scope) == ("once", "once") and len(asker.frames) == 2
    assert await _grant_count() == 0


async def test_a_grant_stays_in_its_own_conversation():
    with permissions.asking_with(Asker(yes("conversation"))):
        await permissions.decide(app(), CTX)
    elsewhere = Asker(no())
    with permissions.asking_with(elsewhere):
        d = await permissions.decide(app(), Context(conversation_id="conv-2", task_id="turn-1"))
    assert d.allowed is False and len(elsewhere.frames) == 1


async def test_a_job_reads_the_conversations_grants_and_uses_its_own_id_as_the_task():
    job = Context(conversation_id="conv-1", job_id="job-7")
    with permissions.asking_with(Asker(yes("conversation"))):
        await permissions.decide(app(), CTX)                 # the chat window
    with permissions.asking_with(Asker()):                   # a job started from that chat: no card
        covered = await permissions.decide(app(), job)
    assert (covered.by, covered.scope) == ("grant", "conversation")
    with permissions.asking_with(Asker(yes("task"))):
        await permissions.decide(app("com.apple.mail"), job)
    async with db_session.AsyncSessionLocal() as db:
        assert await permission_store.find_grant(db, "conv-1", "job-7", "app", "com.apple.mail")
        assert await permission_store.find_grant(db, "conv-1", "turn-1", "app", "com.apple.mail") is None
        newest = (await permission_store.recent(db))[0]
    assert (newest.job_id, newest.scope) == ("job-7", "task")


async def test_the_ledger_row_carries_the_ids_of_the_turn_that_asked(monkeypatch):
    from types import SimpleNamespace
    from server.services import personal_context
    monkeypatch.setattr(personal_context, "current",
                        lambda: SimpleNamespace(task_id="turn-x", run_id="turn-turn-x", query=""))
    with permissions.asking_with(Asker(yes("task"))):
        await permissions.decide(app(), Context(conversation_id="conv-1"))
    async with db_session.AsyncSessionLocal() as db:
        [event] = await permission_store.recent(db)
    assert (event.conversation_id, event.run_id, event.job_id) == ("conv-1", "turn-turn-x", None)


async def test_the_ledger_row_is_cut_to_size_and_an_odd_extra_is_still_stored():
    """Callers put what they like in `extra` (Hands: names, roles, labels). It is stored as
    JSON, cut to 1 KB, and never breaks the decision."""
    plain = Request(kind="app", target="com.apple.Notes", title="t", always_label="Notes",
                    detail="d" * 900, extra={"app": "Notes", "role": "button"})
    odd = Request(kind="app", target="com.apple.mail", title="t", always_label="Mail",
                  extra={"folder": Path("/tmp/inbox"), "n": 1})
    big = Request(kind="app", target="com.apple.Safari", title="t", always_label="Safari",
                  extra={"page": "p" * 5000})
    with permissions.asking_with(Asker(yes("task"), yes("task"), yes("task"))):
        decisions = [await permissions.decide(r, CTX) for r in (plain, odd, big)]
    assert all(d.allowed for d in decisions)
    async with db_session.AsyncSessionLocal() as db:
        events = {e.target: e for e in await permission_store.recent(db)}
    assert len(events["com.apple.Notes"].detail) == 500
    assert events["com.apple.Notes"].extra == {"app": "Notes", "role": "button"}
    assert events["com.apple.mail"].extra == {"folder": "/tmp/inbox", "n": 1}
    assert set(events["com.apple.Safari"].extra) == {"truncated"}
    assert len(events["com.apple.Safari"].extra["truncated"]) == 1024


async def test_a_note_is_trimmed_and_cut_to_500_characters():
    with permissions.asking_with(Asker(no("  " + "n" * 600 + "  "))):
        d = await permissions.decide(app(), CTX)
    assert d.note == "n" * 500


async def test_no_without_a_note_tells_the_model_not_to_ask_again():
    with permissions.asking_with(Asker(no())):
        d = await permissions.decide(app(), CTX)
    assert d.note == "" and "Use Notes?" in d.model_text and "Don't ask for it again" in d.model_text


async def test_no_surface_tells_the_model_it_was_not_done():
    d = await permissions.decide(Request(kind="schedule", target="*", title="Schedule “digest”?"),
                                 Context(conversation_id="conv-1"))
    assert "Schedule “digest”?" in d.model_text and "not done" in d.model_text


@pytest.mark.parametrize("answer, outcome", [(yes("task"), "approved"), (no(), "declined"),
                                             (EXPIRED, "expired")])
async def test_the_outcome_the_tool_loop_reads_follows_the_decision(answer, outcome):
    with permissions.asking_with(Asker(answer)):
        d = await permissions.decide(app(), CTX)
    assert approvals.LAST_OUTCOME.get() == outcome
    assert permissions.LAST_DECISION.get() is d


async def test_a_standing_answer_sets_the_outcome_too():
    with permissions.asking_with(Asker(yes("always"))):
        await permissions.decide(app(), CTX)
    approvals.LAST_OUTCOME.set("declined")
    d = await permissions.decide(app(), CTX)
    assert (approvals.LAST_OUTCOME.get(), permissions.LAST_DECISION.get()) == ("approved", d)


async def test_the_card_surface_is_bound_only_inside_its_with_block():
    asker = Asker(yes("once"))
    digest = Request(kind="schedule", target="*", title="Schedule “digest”?")
    with permissions.asking_with(asker):
        with permissions.asking_with(None):              # e.g. a scheduled run started from a window
            inner = await permissions.decide(digest, CTX)
        outer = await permissions.decide(digest, CTX)
    after = await permissions.decide(digest, CTX)
    assert (inner.by, outer.by, after.by) == ("policy", "user", "policy")
    assert len(asker.frames) == 1


async def test_record_standing_writes_the_row_a_callers_own_rule_check_would_have_missed():
    asker = Asker()
    with permissions.asking_with(asker):
        await permissions.record_standing(Request(kind="command", target="delete", title="t"), CTX)
    async with db_session.AsyncSessionLocal() as db:
        [event] = await permission_store.recent(db)
    assert (event.kind, event.target, event.decided_by, event.decision, event.scope) \
        == ("command", "delete", "rule", "allow", "always")
    assert asker.frames == []


@pytest.mark.parametrize("scope, by", [("task", "grant"), ("conversation", "grant"), ("always", "rule")])
async def test_one_answer_to_a_many_app_card_covers_every_app_shown(scope, by):
    reqs = [app("com.apple.Notes"), app("com.apple.mail")]
    with permissions.asking_with(Asker(yes(scope))):
        answered = await permissions.decide_many(reqs, CTX, title="Use Notes and Mail?")
    assert [(d.by, d.scope) for d in answered] == [("user", scope)] * 2
    with permissions.asking_with(Asker()):               # every app is allowed now: no card at all
        later = await permissions.decide_many(reqs, CTX, title="Use Notes and Mail?")
        assert await permissions.decide_many([], CTX, title="nothing") == []
    assert [(d.by, d.scope) for d in later] == [(by, scope)] * 2


async def test_a_no_to_a_many_app_card_refuses_only_the_apps_shown():
    with permissions.asking_with(Asker(yes("always"))):
        await permissions.decide(app("com.apple.Notes"), CTX)
    reqs = [app("com.apple.reminders"), app("com.apple.Notes"), app("com.apple.mail")]
    with permissions.asking_with(Asker(no("not those"))):
        out = await permissions.decide_many(reqs, CTX, title="Use Reminders and Mail?")
    assert [(d.allowed, d.by) for d in out] == [(False, "user"), (True, "rule"), (False, "user")]
    assert out[0].note == out[2].note == "not those"


async def test_decide_many_writes_a_row_for_each_standing_answer_and_one_for_the_card():
    with permissions.asking_with(Asker(yes("always"))):
        await permissions.decide(app("com.apple.Notes"), CTX)
    reqs = [app("com.apple.Notes"), app("com.apple.reminders"), app("com.apple.mail")]
    with permissions.asking_with(Asker(yes("conversation"))):
        await permissions.decide_many(reqs, CTX, title="Use Reminders and Mail?")
    async with db_session.AsyncSessionLocal() as db:
        rows = list(reversed(await permission_store.recent(db)))[1:]       # after the first card
    assert [(e.decided_by, e.scope) for e in rows] == [("rule", "always"), ("user", "conversation")]
    assert rows[0].rule_id is not None and rows[1].grant_id is not None
    assert rows[1].wait_ms is not None


async def test_the_card_frame_says_when_it_expires(monkeypatch):
    monkeypatch.setattr(approvals, "TIMEOUT_S", 1800)
    asker = Asker(no())
    before = time.time()
    with permissions.asking_with(asker):
        await permissions.decide(app(), CTX)
    expires_at = asker.frames[0]["expires_at"]
    assert before + 1800 <= expires_at <= time.time() + 1800


async def test_a_task_id_the_caller_gave_wins_over_the_running_turns(monkeypatch):
    from types import SimpleNamespace
    from server.services import personal_context
    monkeypatch.setattr(personal_context, "current",
                        lambda: SimpleNamespace(task_id="turn-x", run_id="turn-turn-x", query=""))
    with permissions.asking_with(Asker(yes("task"))):
        await permissions.decide(app(), Context(conversation_id="conv-1", task_id="turn-given"))
    async with db_session.AsyncSessionLocal() as db:
        assert await permission_store.find_grant(db, "conv-1", "turn-given", "app", "com.apple.Notes")
        assert await permission_store.find_grant(db, "conv-1", "turn-x", "app", "com.apple.Notes") is None


async def test_an_unreadable_setting_is_the_standard_mode(monkeypatch):
    async def broken(db):
        raise RuntimeError("settings table unreadable")
    monkeypatch.setattr(settings_service, "shell_confirm_policy", broken)
    with permissions.asking_with(Asker(yes("task"))):
        d = await permissions.decide(app(), CTX)
    assert d.allowed
    async with db_session.AsyncSessionLocal() as db:
        [event] = await permission_store.recent(db)
    assert event.mode == "standard"


async def test_a_ledger_that_cannot_be_written_does_not_break_a_refusal(monkeypatch):
    async def broken(db, **fields):
        raise RuntimeError("disk full")
    monkeypatch.setattr(permission_store, "record", broken)
    d = await permissions.decide(Request(kind="schedule", target="*", title="Schedule “digest”?"),
                                 Context(conversation_id="conv-1"))
    assert (d.allowed, d.by) == (False, "policy")
    await permissions.record_standing(Request(kind="command", target="delete", title="t"), CTX)


async def test_the_card_for_several_apps_is_one_frame_for_all_of_them():
    asker = Asker(no())
    with permissions.asking_with(asker):
        await permissions.decide_many([app("com.apple.reminders"), app("com.apple.mail")], CTX,
                                      title="Use Reminders and Mail?")
    [frame] = asker.frames
    assert (frame["type"], frame["kind"], frame["title"]) \
        == ("propose_action", "app", "Use Reminders and Mail?")
    assert "com.apple.reminders" in frame["detail"] and "com.apple.mail" in frame["detail"]
    assert "com.apple.reminders" in frame["dedupe"] and "com.apple.mail" in frame["dedupe"]
    assert frame["options"] == ["task", "conversation", "always"]


async def test_decide_many_hides_the_conversation_choice_when_any_app_forbids_it():
    asker = Asker(yes("task"))
    reqs = [app("com.apple.Notes"),
            Request(kind="app", target="com.apple.mail", title="t", always_label="Mail",
                    conversation_ok=False)]
    with permissions.asking_with(asker):
        await permissions.decide_many(reqs, CTX, title="Use Notes and Mail?")
    assert asker.frames[0]["options"] == ["task", "always"]


# ── Fix round 1: decide_many is one kind, each rule has its own label, and the minors ──────────


async def test_decide_many_needs_one_kind():
    """A card offers the choices of one kind. With an app first, a money step on the same card was
    offered "this conversation" and a money grant was stored."""
    pay = Request(kind="money", target="com.apple.AppStore", title="Buy this app?")
    asker = Asker()
    with permissions.asking_with(asker):
        with pytest.raises(ValueError, match="decide_many needs one kind"):
            await permissions.decide_many([app("com.apple.Notes"), pay], CTX, title="Use Notes and buy?")
    assert asker.frames == []                          # no card was shown...
    assert await _grant_count() == 0                   # ...nothing was remembered...
    async with db_session.AsyncSessionLocal() as db:
        assert await permission_store.recent(db) == []  # ...and no decision was written


async def test_decide_many_needs_one_kind_whatever_the_store_holds():
    """The check does not wait for the store: a mixed list whose app is already allowed is the same
    caller bug, and it must not work today only to fail the day the app is not allowed."""
    with permissions.asking_with(Asker(yes("always"))):
        await permissions.decide(app("com.apple.Notes"), CTX)
    pay = Request(kind="money", target="com.apple.AppStore", title="Buy this app?")
    with pytest.raises(ValueError, match="one kind"):
        await permissions.decide_many([app("com.apple.Notes"), pay], CTX, title="t")


async def test_the_combined_card_names_every_item_even_when_each_request_has_its_own_frame():
    def with_own_frame(bundle, name):
        return Request(kind="app", target=bundle, title=f"Use {name}?", detail=f"{name}: look only",
                       always_label=name,
                       frame=protocol.propose_action(f"own-{name}", "app", bundle, f"{name}: look only"))

    asker = Asker(no())
    with permissions.asking_with(asker):
        await permissions.decide_many([with_own_frame("com.apple.reminders", "Reminders"),
                                       with_own_frame("com.apple.mail", "Mail")], CTX,
                                      title="Use Reminders and Mail?")
    [frame] = asker.frames
    assert "Reminders: look only" in frame["detail"] and "Mail: look only" in frame["detail"]
    assert frame["title"] == "Use Reminders and Mail?"
    assert frame["call_id"] not in ("own-Reminders", "own-Mail")      # the card is the combined one


async def test_each_rule_a_many_app_card_stores_keeps_its_own_label():
    reqs = [Request(kind="app", target="com.apple.reminders", title="t", always_label="Reminders"),
            Request(kind="app", target="com.apple.mail", title="t", always_label="Mail")]
    asker = Asker(yes("always"))
    with permissions.asking_with(asker):
        await permissions.decide_many(reqs, CTX, title="Use Reminders and Mail?")
    assert asker.frames[0]["always_label"] == "Reminders, Mail"       # the card says both...
    async with db_session.AsyncSessionLocal() as db:
        rules = {r.target: r.label for r in await permission_store.list_rules(db, "app")}
    assert rules == {"com.apple.reminders": "Reminders", "com.apple.mail": "Mail"}   # ...each rule one


async def test_a_remember_as_entry_may_carry_its_own_label():
    req = Request(kind="command", target="delete|git-push", title="Run it?",
                  always_label="deletes files, publishes",
                  remember_as=(("legacy_rule", "delete", "deletes files"), ("legacy_rule", "git-push")))
    with permissions.asking_with(Asker(yes("always"))):
        await permissions.decide(req, CTX)
    async with db_session.AsyncSessionLocal() as db:
        rules = {r.target: r.label for r in await permission_store.list_rules(db, "legacy_rule")}
    # an entry with a label keeps it; one without falls back to the request's own
    assert rules == {"delete": "deletes files", "git-push": "deletes files, publishes"}


@pytest.mark.parametrize("answer, outcome", [(EXPIRED, "expired"), (no("later"), "declined")])
async def test_after_decide_many_the_outcome_is_the_cards_not_the_last_apps(answer, outcome):
    """The card's app comes first and an app allowed by a rule comes last: what a tool result reads
    must still be the card's answer."""
    with permissions.asking_with(Asker(yes("always"))):
        await permissions.decide(app("com.apple.Notes"), CTX)
    with permissions.asking_with(Asker(answer)):
        out = await permissions.decide_many([app("com.apple.reminders"), app("com.apple.Notes")], CTX,
                                            title="Use Reminders and Notes?")
    assert [d.allowed for d in out] == [False, True]
    assert approvals.LAST_OUTCOME.get() == outcome
    assert permissions.LAST_DECISION.get() is out[0]


@pytest.mark.parametrize("seconds, said", [(1800, "in 30 minutes."), (300, "in 5 minutes.")])
async def test_the_expiry_text_names_the_wait_the_card_really_had(monkeypatch, seconds, said):
    monkeypatch.setattr(approvals, "TIMEOUT_S", seconds)
    with permissions.asking_with(Asker(EXPIRED)):
        d = await permissions.decide(app(), CTX)
    assert said in d.model_text and "NOT a refusal" in d.model_text


async def test_a_ledger_that_cannot_be_written_does_not_take_back_a_standing_yes(monkeypatch, caplog):
    with permissions.asking_with(Asker(yes("always"), yes("conversation"))):
        await permissions.decide(app("com.apple.Notes"), CTX)                 # a rule
        await permissions.decide(app("com.apple.mail"), CTX)                  # a conversation grant

    async def broken(db, **fields):
        raise RuntimeError("database is locked")

    with monkeypatch.context() as patched, caplog.at_level(logging.WARNING):
        patched.setattr(permission_store, "record", broken)
        by_rule = await permissions.decide(app("com.apple.Notes"), CTX)
        by_grant = await permissions.decide(app("com.apple.mail"), CTX)
        many = await permissions.decide_many([app("com.apple.Notes"), app("com.apple.mail")], CTX, title="t")
    assert (by_rule.allowed, by_rule.by) == (True, "rule")
    assert (by_grant.allowed, by_grant.by) == (True, "grant")
    assert [(d.allowed, d.by) for d in many] == [(True, "rule"), (True, "grant")]
    assert "approval ledger write failed" in caplog.text
    async with db_session.AsyncSessionLocal() as db:                  # rolled back: the use is not counted
        rule = await permission_store.find_rule(db, "app", "com.apple.Notes")
        assert (rule.use_count, rule.last_used_at) == (0, None)
    await permissions.decide(app("com.apple.Notes"), CTX)             # the ledger is healthy again
    async with db_session.AsyncSessionLocal() as db:
        rule = await permission_store.find_rule(db, "app", "com.apple.Notes")
        assert rule.use_count == 1
        assert (await permission_store.recent(db))[0].decided_by == "rule"


async def test_would_ask_opens_one_session_and_reads_no_settings(monkeypatch):
    sessions = _OpenSessions(db_session.AsyncSessionLocal)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", sessions)
    assert await permissions.would_ask(app(), CTX)
    assert sessions.opened == 1                       # the lookup; the mode (a setting) would be a second


async def test_the_ledger_keeps_a_long_target_whole():
    """A many-app card's target is every bundle id joined: cutting it at 2000 characters cut an app in
    two. Only an absurd one (past 20 000) is cut."""
    many_apps = "\x1e".join(f"com.example.app{n:03d}" for n in range(250))
    absurd = "t" * 30_000
    with permissions.asking_with(Asker(yes("once"), yes("once"))):
        await permissions.decide(Request(kind="schedule", target=many_apps, title="t"), CTX)
        await permissions.decide(Request(kind="schedule", target=absurd, title="t"), CTX)
    async with db_session.AsyncSessionLocal() as db:
        newest, older = await permission_store.recent(db)
    assert len(many_apps) > 2000 and older.target == many_apps
    assert len(newest.target) == 20_000


@pytest.mark.parametrize("call", ["decide", "decide_many"])
async def test_a_decision_that_raises_leaves_no_stale_outcome(monkeypatch, call):
    permissions.LAST_DECISION.set(permissions.Decision(True, "rule", "always"))
    approvals.LAST_OUTCOME.set("approved")

    async def unreadable(db, kind, target):
        raise RuntimeError("store unreadable")

    monkeypatch.setattr(permission_store, "find_rule", unreadable)
    with pytest.raises(RuntimeError):
        if call == "decide":
            await permissions.decide(app(), CTX)
        else:
            await permissions.decide_many([app()], CTX, title="t")
    assert permissions.LAST_DECISION.get() is None
    assert approvals.LAST_OUTCOME.get() is None

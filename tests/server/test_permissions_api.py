"""0.1.61 §A4/§A5: the Inbox answers with a scope and a note; standing rules are listed and
withdrawn; what a scheduled run could not ask for is listed, with "Always allow" — which stores
exactly what "Always" on that card would have stored, and nothing a client names.

Cards are opened on the client's own loop (`portal.call`): a card's future belongs to the loop
that answers it, and the routes are served there."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import update

from server.db.models import ApprovalEvent, PermissionRule
from server.services import approvals, permission_store, permissions, run_registry, terminal_policy
from tests.server.conftest import build_ws_client


@pytest.fixture
def client(tmp_path, monkeypatch, portal):
    return build_ws_client(portal, tmp_path, monkeypatch, db_name="permissions_api.db")


@pytest.fixture(autouse=True)
def _clean():
    approvals._reset_for_tests()
    yield
    approvals._reset_for_tests()


def _open(client, conversation_id: str, frame: dict):
    return client.portal.call(approvals.open_card, conversation_id, frame)


def _close(client, pending) -> dict:
    return client.portal.call(approvals.close_card, pending)


def _decide(client, req: permissions.Request, conversation_id: str = "c", asker=None):
    async def run():
        with permissions.asking_with(asker):
            return await permissions.decide(req, permissions.Context(conversation_id=conversation_id))
    return client.portal.call(run)


async def _no_card(frame):
    raise AssertionError(f"a card was shown: {frame.get('title')}")


async def _declines(frame):
    return {"approved": False, "scope": None, "note": "", "by": "mac"}


def _cmd(shell: str) -> permissions.Request:
    return approvals._command_request(shell, sorted(terminal_policy.ask_rules(shell)), None)


def _app(target: str, name: str, *, high_reach: bool = False) -> permissions.Request:
    # Hands asks for a high-reach app (System Events, Terminal…) with no "Always" (§A4, §A11).
    return permissions.Request(kind="app", target=target, title=f"Use {name}?",
                               always_label="" if high_reach else name)


def _refused(client, query: str = "") -> list[dict]:
    return client.get(f"/api/v1/approvals/refused{query}").json()


def _allow(client, refused_id: int):
    return client.post("/api/v1/permissions/rules", json={"refused_id": refused_id})


def _rules(client) -> set[tuple[str, str, str]]:
    return {(r["kind"], r["target"], r["label"]) for r in client.get("/api/v1/permissions/rules").json()}


def _rule_rows(client) -> list[PermissionRule]:
    async def read():
        async with client.db_maker() as db:
            return await permission_store.list_rules(db)
    return client.portal.call(read)


def test_the_inbox_answers_with_a_scope_and_a_note(client, monkeypatch):
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    p = _open(client, "c", {"type": "propose_action", "call_id": "k1", "kind": "app",
                            "target": "Notes", "detail": "", "options": ["task", "conversation"]})
    r = client.post("/api/v1/approvals/k1/answer", json={"approve": True, "scope": "conversation"})
    assert r.status_code == 200 and _close(client, p)["scope"] == "conversation"
    q = _open(client, "c", {"type": "propose_action", "call_id": "k2", "kind": "app",
                            "target": "Mail", "detail": "", "options": ["task"], "dedupe": "m"})
    client.post("/api/v1/approvals/k2/answer", json={"approve": False, "note": "not Mail"})
    assert _close(client, q)["note"] == "not Mail"


def test_the_island_answers_once_only_through_the_api(client, monkeypatch):
    """The route passes its surface through: the island's yes is the card's first choice, whatever
    scope it sends (the clamp is approvals', never re-implemented here)."""
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: (lambda f: None))
    p = _open(client, "c", {"type": "propose_action", "call_id": "k3", "kind": "desktop_app",
                            "target": "Notes", "detail": "",
                            "options": ["task", "conversation", "always"]})
    r = client.post("/api/v1/approvals/k3/answer",
                    json={"approve": True, "source": "island", "scope": "always"})
    assert r.status_code == 200
    d = _close(client, p)
    assert (d["scope"], d["by"]) == ("task", "island")


def test_an_answer_with_a_scope_no_card_has_is_refused_by_the_schema(client):
    r = client.post("/api/v1/approvals/k4/answer", json={"approve": True, "scope": "forever"})
    assert r.status_code == 422


def test_rules_are_listed_created_and_withdrawn(client):
    _decide(client, _app("com.apple.Notes", "Notes"))
    [row] = _refused(client)
    r = _allow(client, row["id"])
    assert r.status_code == 200
    rule_id = r.json()["id"]
    [listed] = client.get("/api/v1/permissions/rules").json()
    assert {k: listed[k] for k in ("id", "kind", "target", "label", "last_used_at", "use_count")} == {
        "id": rule_id, "kind": "app", "target": "com.apple.Notes", "label": "Notes",
        "last_used_at": None, "use_count": 0}
    assert listed["created_at"]
    assert client.delete(f"/api/v1/permissions/rules/{rule_id}").json() == {"ok": True}
    assert client.get("/api/v1/permissions/rules").json() == []
    assert client.delete(f"/api/v1/permissions/rules/{rule_id}").status_code == 404


def test_a_rule_allowed_here_is_the_rule_decide_honours_and_withdrawing_it_asks_again(client):
    req = _app("com.apple.Notes", "Notes")
    _decide(client, req)
    rule_id = _allow(client, _refused(client)[0]["id"]).json()["id"]
    assert _decide(client, req, asker=_no_card).by == "rule"
    [listed] = client.get("/api/v1/permissions/rules").json()
    assert listed["use_count"] == 1 and listed["last_used_at"]
    client.delete(f"/api/v1/permissions/rules/{rule_id}")
    assert _decide(client, req).by == "policy"                  # no rule: a run with nobody to ask


@pytest.mark.parametrize("kind", ["money", "capability", "other_agent", "destructive", "takeover",
                                  "screen", "workspace_write", "schedule"])
def test_kinds_that_are_never_remembered_cannot_become_rules(client, kind):
    """Even with the words for "Always", a card of such a kind never offers it: its refused row
    offers no "Always allow", and asking for one anyway is refused."""
    _decide(client, permissions.Request(kind=kind, target="x", title="X?", always_label="x"))
    [row] = _refused(client)
    assert row["always_ok"] is False
    assert _allow(client, row["id"]).status_code == 409
    assert _rules(client) == set()


@pytest.mark.parametrize("kind,target", [("command", "rules:git-push"),
                                         ("legacy_rule", "hardline"), ("send", "*"),
                                         ("outside", "/"), ("nonsense", "x")])
def test_the_post_takes_a_refusal_and_nothing_a_client_names(client, kind, target):
    """Review I1 (P4): no kind, target or label from the client ever becomes a rule."""
    _decide(client, _app("com.apple.Notes", "Notes"))
    [row] = _refused(client)
    for body in ({"kind": kind, "target": target, "label": ""},
                 {"refused_id": row["id"], "kind": kind, "target": target, "label": ""}):
        assert client.post("/api/v1/permissions/rules", json=body).status_code == 422
    assert _rules(client) == set()


def test_an_unknown_refusal_is_404_and_a_row_that_is_not_a_policy_refusal_is_409(client):
    async def allows(frame):
        return {"approved": True, "scope": "once", "note": "", "by": "mac"}
    _decide(client, _app("com.apple.Notes", "Notes"), asker=_declines)
    _decide(client, _app("com.apple.Mail", "Mail"), asker=allows)

    async def ids():
        async with client.db_maker() as db:
            return [e.id for e in await permission_store.recent(db)]
    for event_id in client.portal.call(ids):
        assert _allow(client, event_id).status_code == 409
    assert _allow(client, 99_999).status_code == 404
    assert _rules(client) == set()


def test_always_allow_on_an_ordinary_refused_command_stores_exactly_its_rules(client):
    """A command's "Always" is a `legacy_rule` for every rule it matched, each in its card's words
    (§A9) — and the rule says which refusal it came from."""
    shell = "rm -rf build"
    rules = sorted(terminal_policy.ask_rules(shell))
    assert len(rules) == 3                          # delete, force-delete (PR 3a), recursive delete
    _decide(client, _cmd(shell))
    [row] = _refused(client)
    assert (row["kind"], row["target"], row["always_ok"]) == ("command", "rules:" + "|".join(rules), True)
    assert _allow(client, row["id"]).status_code == 200
    assert _rules(client) == {("legacy_rule", r, terminal_policy.describe(r)) for r in rules}
    assert {r.created_from for r in _rule_rows(client)} == {f"refused:{row['id']}"}

    async def standing():
        async with client.db_maker() as db:
            return terminal_policy.standing_allows(shell, await terminal_policy.always_allowed(db))
    assert client.portal.call(standing) is True                     # the card's own "Always"


def test_a_crafted_separator_in_a_command_makes_no_rule_nobody_saw(client):
    """Review P3: a model-written command carrying the many-app separator is one command, not a
    list — no rule for `git-push` can come of it."""
    crafted = _cmd("echo hi\x1egit-push")
    assert crafted.target == "text:echo hi\x1egit-push"
    _decide(client, crafted)
    [row] = _refused(client)
    assert row["always_ok"] is False and _allow(client, row["id"]).status_code == 409
    assert _rules(client) == set()
    assert _decide(client, _cmd("git push origin main"), asker=_declines).by == "user"   # asked


@pytest.mark.parametrize("req", [
    _cmd("git-push"),                                            # P2: no rule matched
    _app("com.apple.Terminal", "Terminal", high_reach=True),     # P1: a high-reach app
], ids=["rule-less command", "high-reach app"])
def test_a_refused_card_that_hid_always_offers_no_always_allow(client, req):
    """Review I2: what the card offered decides, not the kind alone."""
    assert "always" not in permissions.options_for(req)
    _decide(client, req)
    [row] = _refused(client)
    assert row["always_ok"] is False and _allow(client, row["id"]).status_code == 409
    assert _rules(client) == set()
    assert _decide(client, req, asker=_declines).by == "user"


def test_a_many_app_card_with_one_high_reach_app_offers_no_always_allow(client):
    reqs = [_app("com.apple.Notes", "Notes"), _app("com.apple.Terminal", "Terminal", high_reach=True)]

    async def refuse():
        return await permissions.decide_many(reqs, permissions.Context(conversation_id="c"),
                                             title="Use Notes and Terminal?")
    client.portal.call(refuse)
    [row] = _refused(client)
    assert row["always_ok"] is False and _allow(client, row["id"]).status_code == 409
    assert _rules(client) == set()


def test_always_allow_on_a_refused_many_app_row_makes_one_rule_per_app(client):
    """A many-app card's row joins its targets; "Always allow" on it is a rule for each app, each
    under its own words — so each app, asked alone or together, needs no card next time."""
    reqs = [_app("com.apple.Notes", "Notes"), _app("com.apple.reminders", "Reminders")]

    async def refuse_both():
        return await permissions.decide_many(reqs, permissions.Context(conversation_id="c"),
                                             title="Use Notes and Reminders?")
    assert [d.by for d in client.portal.call(refuse_both)] == ["policy", "policy"]
    [row] = _refused(client)
    assert row["always_ok"] is True and row["target"] == "com.apple.Notes\x1ecom.apple.reminders"
    r = _allow(client, row["id"])
    assert r.status_code == 200
    assert [(x["target"], x["label"]) for x in r.json()["rules"]] == [
        ("com.apple.Notes", "Notes"), ("com.apple.reminders", "Reminders")]
    assert _rules(client) == {("app", "com.apple.Notes", "Notes"),
                              ("app", "com.apple.reminders", "Reminders")}
    assert [d.by for d in client.portal.call(refuse_both)] == ["rule", "rule"]
    assert _decide(client, reqs[1], asker=_no_card).by == "rule"


def test_a_caller_cannot_put_an_always_set_into_a_refusal(client):
    """The reserved key of the ledger's `extra` is the server's: a request's own `extra` never
    supplies what "Always allow" stores."""
    req = permissions.Request(kind="app", target="com.apple.Terminal", title="Use Terminal?",
                              extra={"always": [["legacy_rule", "git-push", "x"]]})
    _decide(client, req)
    [row] = _refused(client)
    assert row["always_ok"] is False and _allow(client, row["id"]).status_code == 409
    assert _rules(client) == set()


@pytest.mark.parametrize("always", [
    [["schedule", "*", "every schedule"]],                      # a kind never remembered
    [["app", "com.apple.Notes", "Notes"], ["money", "*", "pay"]],   # one bad entry spoils the set
    [["app", "", "nothing"]], [["", "x", "x"]], [["app", "x"]], [["app", "x", 1]], ["app"], "app", [],
])
def test_a_refusal_whose_recorded_set_is_not_one_decide_writes_allows_nothing(client, always):
    """Fail closed on the ledger itself: a row whose "Always" set is not well formed, or names a
    kind never remembered, offers nothing and allows nothing."""
    async def seed():
        async with client.db_maker() as db:
            await permission_store.record(db, kind="app", target="x", mode="standard",
                                          decided_by="policy", decision="deny",
                                          conversation_id="c", extra={"always": always})
            await db.commit()
    client.portal.call(seed)
    [row] = _refused(client)
    assert row["always_ok"] is False and _allow(client, row["id"]).status_code == 409
    assert _rules(client) == set()


@pytest.mark.parametrize("decided_by,decision", [("user", "deny"), ("policy", "allow"),
                                                 ("rule", "allow"), ("expired", "expired"),
                                                 ("away", "deny"), ("away", "allow")])
def test_only_a_refusal_for_want_of_someone_to_ask_can_be_allowed(client, decided_by, decision):
    """Whatever a ledger row carries, "Always allow" is for what could not be asked alone: a policy
    refusal, or a card that never opened because the person was away (an expiry, F3). A card that
    was shown and ran out is not one."""
    async def seed():
        async with client.db_maker() as db:
            row = await permission_store.record(
                db, kind="app", target="com.apple.Notes", mode="standard", decided_by=decided_by,
                decision=decision, conversation_id="c",
                extra={"always": [["app", "com.apple.Notes", "Notes"]]})
            await db.commit()
            return row.id
    assert _allow(client, client.portal.call(seed)).status_code == 409
    assert _rules(client) == set()


def test_a_rules_label_is_its_own_and_only_a_migrated_one_falls_back_to_words(client):
    """Rules carried over from 0.1.60 have no label: they are listed as the card said them. Any
    other rule keeps its own label, an empty one included."""
    async def seed():
        async with client.db_maker() as db:
            await permission_store.add_rule(db, "legacy_rule", "delete", created_from="migration")
            await permission_store.add_rule(db, "legacy_rule", "upload", label="uploads, my words")
            await permission_store.add_rule(db, "app", "com.example.tool", created_from="card")
            await db.commit()
    client.portal.call(seed)
    labels = {r["target"]: r["label"] for r in client.get("/api/v1/permissions/rules").json()}
    assert labels == {"delete": terminal_policy.describe("delete"), "upload": "uploads, my words",
                      "com.example.tool": ""}
    assert labels["delete"] and labels["delete"] != "delete"


def test_a_stray_rule_for_a_kind_never_remembered_is_not_honoured(client):
    """Review M6: only a kind whose card offers "Always" has rules; a row for any other (written
    by hand, or by a bug) decides nothing."""
    async def seed():
        async with client.db_maker() as db:
            for kind in ("schedule", "screen", "workspace_write", "destructive"):
                await permission_store.add_rule(db, kind, "*", created_from="stray")
            await db.commit()
    client.portal.call(seed)
    for kind in ("schedule", "screen", "workspace_write", "destructive"):
        assert _decide(client, permissions.Request(kind=kind, target="*", title="X?")).by == "policy"


# ── what a run with nobody to ask could not do ────────────────────────────────

def test_policy_refusals_are_listed_for_the_inbox(client):
    _decide(client, permissions.Request(kind="schedule", target="*", title="Schedule digest?"))
    rows = _refused(client, "?hours=24")
    assert [(r["kind"], r["target"]) for r in rows] == [("schedule", "*")]
    assert set(rows[0]) >= {"id", "created_at", "conversation_id", "kind", "target", "detail"}
    assert rows[0]["conversation_id"] == "c"


def test_only_what_could_not_be_asked_is_listed(client):
    """A card the user declined, or one shown that nobody answered, is not "not done while you were
    away". A policy refusal is, and so is a card that never opened because an earlier one of its
    job or turn went unanswered (F3)."""
    async def nobody(frame):
        return {"approved": False, "scope": None, "note": "", "by": None}

    async def away(frame):
        return {"approved": False, "scope": None, "note": "", "by": None, "away": True}

    async def allows(frame):
        return {"approved": True, "scope": "once", "note": "", "by": "mac"}
    _decide(client, permissions.Request(kind="app", target="a", title="A?"), asker=_declines)
    _decide(client, permissions.Request(kind="app", target="b", title="B?"), asker=nobody)
    _decide(client, permissions.Request(kind="app", target="c", title="C?"), asker=allows)
    _decide(client, permissions.Request(kind="app", target="d", title="D?"))
    _decide(client, permissions.Request(kind="app", target="e", title="E?"), asker=away)
    assert [r["target"] for r in _refused(client)] == ["e", "d"]


def test_the_refused_list_looks_back_between_one_hour_and_a_week(client):
    for target in ("now", "two-hours", "two-days", "two-weeks"):
        _decide(client, permissions.Request(kind="app", target=target, title=f"{target}?"))

    async def age():
        async with client.db_maker() as db:
            for target, hours in (("two-hours", 2), ("two-days", 48), ("two-weeks", 336)):
                await db.execute(update(ApprovalEvent).where(ApprovalEvent.target == target).values(
                    created_at=datetime.utcnow() - timedelta(hours=hours)))
            await db.commit()
    client.portal.call(age)

    def seen(query: str) -> set[str]:
        return {r["target"] for r in _refused(client, query)}
    assert seen("") == {"now", "two-hours"}                      # 24 hours by default
    assert seen("?hours=0") == {"now"}                           # at least one hour
    assert seen("?hours=72") == {"now", "two-hours", "two-days"}
    assert seen("?hours=10000") == {"now", "two-hours", "two-days"}   # at most a week


def test_the_same_refusal_again_and_again_is_one_entry_with_its_count(client):
    """Review M7 (P5): a schedule hitting one boundary every 15 minutes is one entry, not 670."""
    req = _app("com.apple.Notes", "Notes")
    for _ in range(5):
        _decide(client, req)
    _decide(client, _app("com.apple.Mail", "Mail"))

    async def stamp():
        async with client.db_maker() as db:
            return [(e.id, e.created_at) for e in await permission_store.recent(db)
                    if e.target == "com.apple.Notes"]
    notes = client.portal.call(stamp)                            # newest first
    rows = _refused(client)
    assert [(r["target"], r["count"]) for r in rows] == [("com.apple.Mail", 1), ("com.apple.Notes", 5)]
    latest, first = notes[0], notes[-1]
    assert rows[1]["id"] == latest[0]
    assert rows[1]["created_at"] == latest[1].isoformat() + "Z"
    assert rows[1]["first_at"] == first[1].isoformat() + "Z"


def test_the_refused_list_shows_at_most_a_hundred_entries_newest_first(client):
    async def refuse_many():
        for i in range(105):
            await permissions.decide(_app(f"app.{i:03}", f"App {i}"),
                                     permissions.Context(conversation_id="c"))
    client.portal.call(refuse_many)
    rows = _refused(client)
    assert [r["target"] for r in rows] == [f"app.{i:03}" for i in range(104, 4, -1)]


def test_an_entry_allowed_since_is_no_longer_listed(client):
    """Review M7 (P7): once "Always allow" made its rules, nothing is waiting any more — and a
    withdrawn rule brings it back."""
    _decide(client, _app("com.apple.Notes", "Notes"))
    _decide(client, _app("com.apple.Mail", "Mail"))
    notes = next(r for r in _refused(client) if r["target"] == "com.apple.Notes")
    rule_id = _allow(client, notes["id"]).json()["id"]
    assert [r["target"] for r in _refused(client)] == ["com.apple.Mail"]
    client.delete(f"/api/v1/permissions/rules/{rule_id}")
    assert {r["target"] for r in _refused(client)} == {"com.apple.Notes", "com.apple.Mail"}


# ── Final-review fix wave: what "Always allow" will store (F2); while the person was away (F3) ──

def test_a_refused_entry_says_what_always_allow_will_store(client):
    """F2 (final review I2, probe P3): one refused command can stand for several standing rules,
    each for every matching command, everywhere. The entry lists them in the card's words before
    the click: exactly what `POST {refused_id}` stores."""
    shell = "rm -rf build && git push origin main"
    rules = sorted(terminal_policy.ask_rules(shell))
    assert len(rules) == 4                          # PR 3a: `rm -rf` also matches force-delete
    _decide(client, _cmd(shell))
    [row] = _refused(client)
    assert row["always"] == [{"kind": "legacy_rule", "target": rule,
                              "label": terminal_policy.describe(rule)} for rule in rules]
    assert all(entry["label"] for entry in row["always"])
    stored = _allow(client, row["id"]).json()["rules"]
    assert [{k: rule[k] for k in ("kind", "target", "label")} for rule in stored] == row["always"]


@pytest.mark.parametrize("req", [
    _cmd("git-push"),
    _app("com.apple.Terminal", "Terminal", high_reach=True),
    permissions.Request(kind="money", target="com.shop.app", title="Pay?", always_label="Shop"),
], ids=["rule-less command", "high-reach app", "money"])
def test_an_entry_whose_card_hid_always_lists_nothing_to_store(client, req):
    _decide(client, req)
    [row] = _refused(client)
    assert (row["always_ok"], row["always"]) == (False, [])


def test_a_jobs_card_after_one_went_unanswered_is_listed_and_always_allow_makes_its_rules(
        client, monkeypatch):
    """F3 (final review I3, probe P4; §A4: once one card of a job expires, its later cards "are
    refused at once as 'waiting for you' and listed in the Inbox the same way"). The row is an
    expiry, never a denial, and "Always allow" on it stores what "Always" on its card would have."""
    from server.services import judgment
    monkeypatch.setattr(judgment, "shadow", lambda *args, **kwargs: None)
    monkeypatch.setattr(judgment, "record_outcome_later", lambda *args, **kwargs: None)
    monkeypatch.setattr(approvals, "TIMEOUT_S", 0.05)
    opened = []
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: lambda f: (
        opened.append(f["call_id"]) if f["type"].startswith("propose_") else None))
    job = approvals.JobConfirmations("c", job_id="job-1")
    assert client.portal.call(job.command, "rm -rf build", []) is False          # shown; nobody answers
    assert client.portal.call(job.command, "git push origin main", []) is False  # the person is away
    assert len(opened) == 1, "the job's later card never opened"
    [row] = _refused(client)                         # the card that was shown and ran out is not listed
    assert (row["kind"], row["target"], row["conversation_id"]) == ("command", "rules:git-push", "c")
    assert row["always_ok"] is True
    assert row["always"] == [{"kind": "legacy_rule", "target": "git-push",
                              "label": terminal_policy.describe("git-push")}]
    assert _allow(client, row["id"]).status_code == 200
    assert _rules(client) == {("legacy_rule", "git-push", terminal_policy.describe("git-push"))}
    assert {r.created_from for r in _rule_rows(client)} == {f"refused:{row['id']}"}
    assert _refused(client) == []                    # allowed since: nothing is waiting any more

    async def ledger():
        async with client.db_maker() as db:
            return [(e.job_id, e.decided_by, e.decision)
                    for e in reversed(await permission_store.recent(db))]
    # Both are expiries; neither is the user's "no".
    assert client.portal.call(ledger) == [("job-1", "expired", "expired"), ("job-1", "away", "expired")]

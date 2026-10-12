"""0.1.61 §A4/§A5: the Inbox answers with a scope and a note; standing rules are listed and
withdrawn; what a scheduled run could not ask for is listed, with "Always allow".

Cards are opened on the client's own loop (`portal.call`): a card's future belongs to the loop
that answers it, and the routes are served there."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import update

from server.db.models import ApprovalEvent
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
    r = client.post("/api/v1/permissions/rules", json={"kind": "app", "target": "com.apple.Notes",
                                                       "label": "Notes"})
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


def test_a_rule_made_here_is_the_rule_decide_honours_and_withdrawing_it_asks_again(client):
    req = permissions.Request(kind="app", target="com.apple.Notes", title="Use Notes?")
    rule_id = client.post("/api/v1/permissions/rules",
                          json={"kind": "app", "target": "com.apple.Notes", "label": "Notes"}).json()["id"]
    assert _decide(client, req).by == "rule"
    [listed] = client.get("/api/v1/permissions/rules").json()
    assert listed["use_count"] == 1 and listed["last_used_at"]
    client.delete(f"/api/v1/permissions/rules/{rule_id}")
    assert _decide(client, req).by == "policy"                  # no rule: a run with nobody to ask


@pytest.mark.parametrize("kind", ["money", "capability", "other_agent", "destructive", "takeover"])
def test_kinds_that_are_never_remembered_cannot_become_rules(client, kind):
    assert client.post("/api/v1/permissions/rules",
                       json={"kind": kind, "target": "x", "label": "x"}).status_code == 400
    assert client.get("/api/v1/permissions/rules").json() == []


@pytest.mark.parametrize("target", ["", "   ", "x" * 2001, "com.apple.Notes\x1e"])
def test_a_rule_needs_a_target_of_at_most_2000_characters(client, target):
    assert client.post("/api/v1/permissions/rules",
                       json={"kind": "app", "target": target, "label": "x"}).status_code == 400
    assert client.get("/api/v1/permissions/rules").json() == []


def test_a_migrated_legacy_rule_is_listed_in_words(client):
    """Rules carried over from 0.1.60 have no label: they are listed as the card said them."""
    async def seed():
        async with client.db_maker() as db:
            await permission_store.add_rule(db, "legacy_rule", "delete", created_from="migration")
            await permission_store.add_rule(db, "legacy_rule", "upload", label="uploads, my words")
            await db.commit()
    client.portal.call(seed)
    labels = {r["target"]: r["label"] for r in client.get("/api/v1/permissions/rules").json()}
    assert labels == {"delete": terminal_policy.describe("delete"), "upload": "uploads, my words"}
    assert labels["delete"] and labels["delete"] != "delete"


# ── what a run with nobody to ask could not do ────────────────────────────────

def test_policy_refusals_are_listed_for_the_inbox(client):
    _decide(client, permissions.Request(kind="schedule", target="*", title="Schedule digest?"))
    rows = client.get("/api/v1/approvals/refused?hours=24").json()
    assert [(r["kind"], r["target"]) for r in rows] == [("schedule", "*")]
    assert set(rows[0]) >= {"id", "created_at", "conversation_id", "kind", "target", "detail"}
    assert rows[0]["conversation_id"] == "c"


def test_only_policy_refusals_are_listed(client):
    """A card the user declined, or one nobody answered, is not "not done while you were away"."""
    async def declines(frame):
        return {"approved": False, "scope": None, "note": "", "by": "mac"}

    async def nobody(frame):
        return {"approved": False, "scope": None, "note": "", "by": None}

    async def allows(frame):
        return {"approved": True, "scope": "once", "note": "", "by": "mac"}
    _decide(client, permissions.Request(kind="app", target="a", title="A?"), asker=declines)
    _decide(client, permissions.Request(kind="app", target="b", title="B?"), asker=nobody)
    _decide(client, permissions.Request(kind="app", target="c", title="C?"), asker=allows)
    _decide(client, permissions.Request(kind="app", target="d", title="D?"))
    assert [r["target"] for r in client.get("/api/v1/approvals/refused").json()] == ["d"]


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
        return {r["target"] for r in client.get(f"/api/v1/approvals/refused{query}").json()}
    assert seen("") == {"now", "two-hours"}                      # 24 hours by default
    assert seen("?hours=0") == {"now"}                           # at least one hour
    assert seen("?hours=72") == {"now", "two-hours", "two-days"}
    assert seen("?hours=10000") == {"now", "two-hours", "two-days"}   # at most a week


def test_always_allow_on_a_refused_many_app_row_makes_one_rule_per_app(client):
    """A many-app card's row joins its targets; "Always allow" on it is a rule for each app, each
    under its own words — so each app, asked alone or together, needs no card next time."""
    reqs = [permissions.Request(kind="app", target=t, title=f"Use {name}?", always_label=name)
            for t, name in (("com.apple.Notes", "Notes"), ("com.apple.reminders", "Reminders"))]

    async def refuse_both():
        return await permissions.decide_many(reqs, permissions.Context(conversation_id="c"),
                                             title="Use Notes and Reminders?")
    assert [d.by for d in client.portal.call(refuse_both)] == ["policy", "policy"]
    [row] = client.get("/api/v1/approvals/refused").json()
    assert row["always_ok"] is True and row["target"] == "com.apple.Notes\x1ecom.apple.reminders"
    r = client.post("/api/v1/permissions/rules",
                    json={"kind": row["kind"], "target": row["target"], "label": "Notes\x1eReminders"})
    assert r.status_code == 200
    assert [(x["target"], x["label"]) for x in r.json()["rules"]] == [
        ("com.apple.Notes", "Notes"), ("com.apple.reminders", "Reminders")]
    listed = {(x["kind"], x["target"], x["label"]) for x in client.get("/api/v1/permissions/rules").json()}
    assert listed == {("app", "com.apple.Notes", "Notes"), ("app", "com.apple.reminders", "Reminders")}
    assert [d.by for d in client.portal.call(refuse_both)] == ["rule", "rule"]
    assert _decide(client, reqs[1]).by == "rule"


def test_a_joined_target_without_a_label_for_each_keeps_each_target_as_its_label(client):
    r = client.post("/api/v1/permissions/rules",
                    json={"kind": "app", "target": "com.apple.Notes\x1ecom.apple.reminders",
                          "label": "Notes, Reminders"})
    assert [(x["target"], x["label"]) for x in r.json()["rules"]] == [
        ("com.apple.Notes", "com.apple.Notes"), ("com.apple.reminders", "com.apple.reminders")]


def test_a_refused_row_of_a_kind_never_remembered_offers_no_always_allow(client):
    _decide(client, permissions.Request(kind="schedule", target="*", title="Schedule digest?"))
    _decide(client, permissions.Request(kind="app", target="com.apple.Notes", title="Use Notes?"))
    rows = {r["kind"]: r for r in client.get("/api/v1/approvals/refused").json()}
    assert (rows["schedule"]["always_ok"], rows["app"]["always_ok"]) == (False, True)
    assert client.post("/api/v1/permissions/rules",
                       json={"kind": "schedule", "target": "*", "label": ""}).status_code == 400
    assert client.get("/api/v1/permissions/rules").json() == []

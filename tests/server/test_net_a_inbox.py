"""NET-a, Codex round 1 F7: a site the proxy refused where nobody could be asked is listed where everything that could
not be asked is listed, and the Inbox's "In this conversation" stores what the card's own answer stores.

- With nobody to ask (a scheduled run), NET-a's card goes where every card goes there (`permissions.decide_many`):
  refused by policy, one ledger row, which GET /approvals/refused lists with the sites it names (`sites`); a
  scheduled task's run makes its task wait on you (progress.waiting_on_user). A background job's card that never
  opened (the person away) is listed the same way.
- POST /permissions/grants {refused_id} answers that card from the Inbox through the card's own path
  (`decide_many` on the same requests): the same `network:<host>` grant for the entry's own conversation, and the
  same ledger row as a click on the card. The client names only the row: nothing but a listed row of NET-a's card
  gives a grant.
- An entry leaves the list once its sites are allowed. A scheduled run's stays, with nothing left to allow there: a
  run with nobody to ask reads no grant (S1).
The proxy admitting the site afterwards, where someone can be asked: tests/server/sbx/test_net_a_proxy.py.
"""
from datetime import datetime

import pytest

from server.db.models import ApprovalEvent, ScheduledTask
from server.services import approvals, net_policy, permission_store, progress
from tests.server.test_net_a_gate import REFUSED, _after_outside_content, _Asker, _Exec

CURL = "curl -s https://collect.evil.example/in"
SITE = "network:collect.evil.example"


@pytest.fixture(autouse=True)
def _fresh():
    net_policy._reset_for_tests()
    approvals._reset_for_tests()
    yield
    net_policy._reset_for_tests()
    approvals._reset_for_tests()


@pytest.fixture
async def api(execution_db, monkeypatch, tmp_path):
    """The Inbox's two routes, over the test's database."""
    import httpx
    from fastapi import FastAPI

    from server import auth
    from server.api.approvals import router as approvals_router
    from server.api.permissions import router as permissions_router
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-net-a-token")
    app = FastAPI()
    app.include_router(permissions_router, prefix="/api/v1")
    app.include_router(approvals_router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                 headers={"Authorization": "Bearer synthetic-net-a-token"}) as http:
        yield http


async def _listed(api, conversation: str) -> list[dict]:
    got = await api.get("/api/v1/approvals/refused", params={"conversation_id": conversation})
    assert got.status_code == 200, got.text
    return [entry for entry in got.json() if entry["kind"] == "network"]


async def _refused_alone(monkeypatch, conversation: str = "c1", sites=("collect.evil.example",)) -> dict:
    """A run with nobody to ask in `conversation`, refused `sites` at the proxy."""
    _, result = await _after_outside_content(monkeypatch, CURL, executor=_Exec({**REFUSED, "net_refused": [*sites]}),
                                             conversation=conversation)
    return result


async def test_with_nobody_to_ask_a_refused_site_is_listed_with_what_in_this_conversation_allows(execution_db, api,
                                                                                                monkeypatch):
    await _refused_alone(monkeypatch)
    [entry] = await _listed(api, "c1")
    assert (entry["target"], entry["unattended"], entry["sites"]) == (SITE, True, ["collect.evil.example"])
    assert CURL in entry["detail"] and entry["always_ok"] is False and entry["always"] == []
    await _refused_alone(monkeypatch)                                      # refused again: the same entry, counted
    [again] = await _listed(api, "c1")
    assert again["count"] == 2 and again["sites"] == ["collect.evil.example"]


async def test_a_scheduled_tasks_refused_site_makes_its_task_wait_on_you(execution_db, monkeypatch):
    async with execution_db() as db:
        db.add(ScheduledTask(id=5, name="weather", prompt="p", schedule_kind="interval", interval_s=3600, enabled=True,
                             consecutive_failures=0, conversation_id="scheduled-weather"))
        await db.commit()
        assert (await progress.waiting_on_user(db)).scheduled == set()
    await _refused_alone(monkeypatch, "scheduled-weather")
    async with execution_db() as db:
        assert (await progress.waiting_on_user(db)).scheduled == {5}


async def test_in_this_conversation_from_the_inbox_stores_what_the_cards_answer_stores(execution_db, api,
                                                                                      monkeypatch):
    await _refused_alone(monkeypatch)                                      # c1: nobody to ask, listed
    await _after_outside_content(monkeypatch, CURL, asker=_Asker(), executor=_Exec(REFUSED),
                                 conversation="c2")                         # c2: the card, "In this conversation"
    [entry] = await _listed(api, "c1")
    made = await api.post("/api/v1/permissions/grants", json={"refused_id": entry["id"]})
    assert made.status_code == 200, made.text
    async with execution_db() as db:
        inbox = await permission_store.find_grant(db, "c1", None, "network", SITE)
        card = await permission_store.find_grant(db, "c2", None, "network", SITE)
        answers = {r.conversation_id: r for r in await permission_store.recent(db)
                   if r.kind == "network" and r.decided_by == "user"}
        assert await permission_store.find_rule(db, "network", SITE) is None              # never "Always"
    assert made.json()["grants"] == [{"id": inbox.id, "target": SITE}]
    assert (inbox.task_id, inbox.kind, inbox.target) == (card.task_id, card.kind, card.target) == ("", "network", SITE)
    assert ({cid: (r.decision, r.scope, r.target, r.grant_id is not None) for cid, r in answers.items()}
            == {cid: ("allow", "conversation", SITE, True) for cid in ("c1", "c2")})
    assert answers["c1"].grant_id == inbox.id and inbox.call_id == f"refused:{entry['id']}"
    # A scheduled run's entry stays listed (S1: a run with nobody to ask still reads no grant), with nothing to allow
    [after] = await _listed(api, "c1")
    assert after["id"] == entry["id"] and after["sites"] == []


async def test_a_job_card_that_never_opened_is_listed_and_leaves_the_list_once_its_sites_are_allowed(
        execution_db, api, monkeypatch):
    away = approvals.BroadcastAsker("c1")
    away.unanswered = True                                                 # an earlier card of the job went unanswered
    await _after_outside_content(monkeypatch, CURL, asker=away,
                                 executor=_Exec({**REFUSED, "net_refused": ["collect.evil.example", "drop.evil.example"]}))
    [entry] = await _listed(api, "c1")
    assert (entry["unattended"], entry["unopened"]) == (False, True)
    assert entry["sites"] == ["collect.evil.example", "drop.evil.example"]          # one card asked about both
    made = await api.post("/api/v1/permissions/grants", json={"refused_id": entry["id"]})
    assert made.status_code == 200, made.text
    assert [g["target"] for g in made.json()["grants"]] == [SITE, "network:drop.evil.example"]
    assert await _listed(api, "c1") == []                                  # allowed: nothing waits any more
    async with execution_db() as db:
        for site in (SITE, "network:drop.evil.example"):
            assert await permission_store.find_grant(db, "c1", None, "network", site) is not None


def _row(**fields) -> ApprovalEvent:
    row = dict(created_at=datetime.utcnow(), conversation_id="c1", kind="network", target=SITE, detail="curl",
               mode="standard", decided_by="policy", decision="deny")
    return ApprovalEvent(**{**row, **fields})


async def test_a_card_that_was_shown_and_went_unanswered_is_answered_the_same_way(execution_db, api):
    async with execution_db() as db:
        db.add(_row(decided_by="expired", decision="expired"))            # INB8: listed too
        await db.commit()
    [entry] = await _listed(api, "c1")
    assert (entry["unattended"], entry["unopened"], entry["sites"]) == (False, False, ["collect.evil.example"])
    assert (await api.post("/api/v1/permissions/grants", json={"refused_id": entry["id"]})).status_code == 200
    assert await _listed(api, "c1") == []


async def test_only_a_listed_row_of_net_as_card_gives_a_grant_and_only_for_its_own_conversation(execution_db, api):
    rows = {"declined": _row(decided_by="user"),                           # the user said no on the card: not listed
            "every site": _row(target="network:*"),                        # S2a-1's card (and verify's, a Shortcut's)
            "another kind": _row(kind="send", target="mail:team"),
            "no conversation": _row(conversation_id=None),
            "another spelling": _row(target="network:Collect.Evil.Example"),
            "a site and every site": _row(target=f"{SITE}\x1enetwork:*"),
            "a site and something else": _row(target=f"{SITE}\x1email:team")}
    async with execution_db() as db:
        db.add_all(rows.values())
        await db.commit()
    assert (await api.post("/api/v1/permissions/grants", json={"refused_id": 9999})).status_code == 404
    for name, row in rows.items():
        got = await api.post("/api/v1/permissions/grants", json={"refused_id": row.id})
        assert got.status_code == 409, (name, got.text)
    named = await api.post("/api/v1/permissions/grants", json={"refused_id": rows["every site"].id, "target": SITE})
    assert named.status_code == 422                                        # a client names the row, nothing else
    listed = {e["target"]: e["sites"] for e in (await api.get("/api/v1/approvals/refused")).json()}
    assert listed["network:*"] == [] and listed["mail:team"] == []
    async with execution_db() as db:
        assert await permission_store.list_conversation_grants(db) == []

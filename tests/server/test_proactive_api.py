"""0.1.47 proactivity API: behind the token, honest status codes, and nothing here
acts on the world except `accept`, which only hands the goal to the job runner."""
from __future__ import annotations

import importlib
from datetime import datetime
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import server.db.session as db_session
from server.api import proactive as proactive_api
from server.db.models import Base
from server.services import background_jobs, proactive_detectors as det, proactive_service as svc
from arslan.proactive_policy import Candidate, Evidence, ProactiveConfig
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

AUTH = {"Authorization": "Bearer test-token"}
NOW = datetime(2026, 9, 30, 12, 0)


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_API_TOKEN", "test-token")
    monkeypatch.setenv("ARSLAN_DB_PATH", str(tmp_path / "p.db"))
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))
    import server.config as config

    importlib.reload(config)
    engine = db_session.build_engine(f"sqlite+aiosqlite:///{tmp_path / 'p.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))
    from server.main import create_app

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test", headers=AUTH) as c:
        yield c
    await engine.dispose()


async def make_item(n=1, **over):
    base = dict(kind="web_change", fingerprint=f"fp:{n}", source_key=f"watch:{n}", title_key="title.web_change",
                evidence=(Evidence("web.changed", {"n": 2}, quote="Price: 9"),), goal="Look at it")
    base.update(over)
    await svc.ingest([det.Found(Candidate(**base))], now_utc=NOW, now_local=NOW, config=ProactiveConfig(notify=False))


async def first_id(client, scope="open"):
    return (await client.get("/api/v1/proactive/items", params={"scope": scope})).json()["items"][0]["id"]


# ── auth ─────────────────────────────────────────────────────────────────────

async def test_no_token_no_access_on_any_route(client):
    """Behavioural, and derived from the router so a route added later is covered without anyone
    remembering. (Not an identity check on `require_auth`: other tests reload the auth module, so
    the function this file sees can legitimately differ from the one the router captured.)"""
    assert proactive_api.router.routes, "router is empty"
    anonymous = AsyncClient(transport=client._transport, base_url="http://test")
    async with anonymous:
        for route in proactive_api.router.routes:
            path = route.path.replace("{item_id}", "1").replace("{watch_id}", "1")
            for method in route.methods - {"HEAD", "OPTIONS"}:
                r = await anonymous.request(method, f"/api/v1{path}", json={})
                assert r.status_code in (401, 403), (method, path, r.status_code)


# ── items ────────────────────────────────────────────────────────────────────

async def test_inbox_lists_items_as_keys_and_evidence_never_bare_prose(client):
    await make_item()
    body = (await client.get("/api/v1/proactive/items")).json()
    [item] = body["items"]
    assert item["title_key"] == "title.web_change" and item["evidence"][0] == {
        "key": "web.changed", "params": {"n": 2}, "quote": "Price: 9"}
    assert (await client.get("/api/v1/proactive/summary")).json() == {"open": 1, "unread": 1, "high": 0,
                                                                          "approvals": 0, "memory": 0}


async def test_scope_is_validated(client):
    assert (await client.get("/api/v1/proactive/items", params={"scope": "everything"})).status_code == 422
    assert (await client.get("/api/v1/proactive/items", params={"limit": 0})).status_code == 422


async def test_seen_clears_the_unread_count(client):
    await make_item()
    item_id = await first_id(client)
    assert (await client.post("/api/v1/proactive/items/seen", json={"ids": [item_id]})).status_code == 200
    assert (await client.get("/api/v1/proactive/summary")).json()["unread"] == 0
    assert (await client.post("/api/v1/proactive/items/seen", json={"ids": list(range(201))})).status_code == 422


async def test_accept_starts_a_job_then_conflicts_then_404s(client, monkeypatch):
    started = []

    async def start(conversation_id, goal, criteria):
        started.append((conversation_id, goal))
        return SimpleNamespace(job_id="job-7")

    monkeypatch.setattr(background_jobs, "start", start)
    monkeypatch.setattr(svc, "model_configured", _yes)
    await make_item()
    item_id = await first_id(client)
    r = await client.post(f"/api/v1/proactive/items/{item_id}/accept", json={"conversation_id": "conv-1"})
    assert r.status_code == 200 and r.json() == {"job_id": "job-7", "conversation_id": "conv-1"}
    again = await client.post(f"/api/v1/proactive/items/{item_id}/accept", json={"conversation_id": "conv-1"})
    assert again.status_code == 409 and again.json()["detail"] == {"code": "already_handled"}
    assert (await client.post("/api/v1/proactive/items/999/accept", json={})).status_code == 404
    assert started == [("conv-1", "Look at it")]


async def test_accept_with_no_model_says_so_and_keeps_the_item(client):
    await make_item()
    item_id = await first_id(client)
    r = await client.post(f"/api/v1/proactive/items/{item_id}/accept", json={"conversation_id": "c"})
    assert r.status_code == 422 and r.json()["detail"] == {"code": "no_model"}
    assert (await client.get("/api/v1/proactive/items")).json()["items"][0]["status"] == "new"


async def test_accept_without_anywhere_to_report_is_a_422_not_a_crash(client, monkeypatch):
    await make_item()
    r = await client.post(f"/api/v1/proactive/items/{await first_id(client)}/accept", json={})
    assert r.status_code == 422 and r.json()["detail"] == {"code": "invalid_conversation"}


async def test_unknown_body_fields_are_refused(client):
    await make_item()
    item_id = await first_id(client)
    for path, body in ((f"/api/v1/proactive/items/{item_id}/accept", {"conversation_id": "c", "goal": "do evil"}),
                       (f"/api/v1/proactive/items/{item_id}/snooze", {"days": 1, "x": 1}),
                       (f"/api/v1/proactive/items/{item_id}/dismiss", {"mute": None, "x": 1})):
        assert (await client.post(path, json=body)).status_code == 422, path


async def test_the_goal_cannot_be_chosen_by_the_caller(client, monkeypatch):
    """accept runs the stored goal and nothing else: there is no way to smuggle a different one in."""
    started = []

    async def start(conversation_id, goal, criteria):
        started.append(goal)
        return SimpleNamespace(job_id="j")

    monkeypatch.setattr(background_jobs, "start", start)
    monkeypatch.setattr(svc, "model_configured", _yes)
    await make_item(goal="Stored goal")
    await client.post(f"/api/v1/proactive/items/{await first_id(client)}/accept", json={"conversation_id": "c"})
    assert started == ["Stored goal"]


async def test_snooze_and_dismiss_codes(client):
    await make_item(1)
    await make_item(2)
    a, b = [i["id"] for i in (await client.get("/api/v1/proactive/items")).json()["items"]]
    assert (await client.post(f"/api/v1/proactive/items/{a}/snooze", json={"days": 400})).status_code == 422
    assert (await client.post(f"/api/v1/proactive/items/{a}/snooze", json={"days": 3})).status_code == 200
    assert (await client.post(f"/api/v1/proactive/items/{a}/snooze", json={"days": 3})).status_code == 200   # re-snooze is fine
    assert (await client.post(f"/api/v1/proactive/items/{b}/dismiss", json={"mute": "nonsense"})).status_code == 422
    assert (await client.post(f"/api/v1/proactive/items/{b}/dismiss", json={"mute": "kind"})).status_code == 200
    assert (await client.post(f"/api/v1/proactive/items/{b}/dismiss", json={})).status_code == 409
    assert (await client.get("/api/v1/proactive/mutes")).json() == {"mutes": ["kind:web_change"]}
    assert (await client.delete("/api/v1/proactive/mutes", params={"key": "kind:web_change"})).status_code == 200
    assert (await client.get("/api/v1/proactive/mutes")).json() == {"mutes": []}


# ── config ───────────────────────────────────────────────────────────────────

async def test_config_round_trip_and_refusals(client):
    assert (await client.get("/api/v1/proactive/config")).json()["diagnosis_daily_usd"] == 0
    r = await client.put("/api/v1/proactive/config", json={"brief_enabled": True, "diagnosis_daily_usd": 0.5})
    assert r.status_code == 200 and r.json()["brief_enabled"] is True
    assert (await client.get("/api/v1/proactive/config")).json()["diagnosis_daily_usd"] == 0.5
    for bad in ({"diagnosis_daily_usd": 99}, {"quiet_start": "soon"}, {"nonsense": True}):
        r = await client.put("/api/v1/proactive/config", json=bad)
        assert r.status_code == 422 and r.json()["detail"] == {"code": "invalid_config"}, bad
    assert (await client.get("/api/v1/proactive/config")).json()["diagnosis_daily_usd"] == 0.5


# ── watches ──────────────────────────────────────────────────────────────────

async def test_watch_lifecycle(client):
    r = await client.post("/api/v1/proactive/watches", json={"kind": "web", "target": "https://example.com/p", "interval_s": 3600})
    assert r.status_code == 201
    watch = r.json()
    assert watch["label"] == "example.com" and watch["enabled"] is True
    r = await client.patch(f"/api/v1/proactive/watches/{watch['id']}", json={"interval_s": 7200, "notify": False})
    assert r.json()["interval_s"] == 7200 and r.json()["notify"] is False
    assert (await client.patch(f"/api/v1/proactive/watches/{watch['id']}", json={"target": "https://evil.example/"})).status_code == 422
    assert (await client.patch(f"/api/v1/proactive/watches/{watch['id']}", json={"interval_s": 5})).status_code == 422
    assert (await client.patch("/api/v1/proactive/watches/999", json={})).status_code == 404
    assert len((await client.get("/api/v1/proactive/watches")).json()["watches"]) == 1
    assert (await client.delete(f"/api/v1/proactive/watches/{watch['id']}")).status_code == 200
    assert (await client.get("/api/v1/proactive/watches")).json() == {"watches": []}


@pytest.mark.parametrize("body, code", [
    ({"kind": "web", "target": "http://example.com/"}, "invalid_url"),
    ({"kind": "web", "target": "https://example.com/", "interval_s": 10}, "invalid_interval"),
    ({"kind": "rss", "target": "https://example.com/"}, "invalid_kind"),
    ({"kind": "folder", "target": "/tmp"}, "outside_workspace"),   # 0.1.48: there is always a workspace
])
async def test_watch_refusals_say_why(client, body, code):
    r = await client.post("/api/v1/proactive/watches", json=body)
    assert r.status_code == 422 and r.json()["detail"] == {"code": code}


# ── scan ─────────────────────────────────────────────────────────────────────

async def test_scan_now_runs_even_when_off_and_reports_counts(client, monkeypatch):
    async def detector(ctx):
        return [det.Found(Candidate(kind="web_change", fingerprint="scan:1", source_key="watch:9", title_key="title.web_change",
                                    evidence=(Evidence("web.changed"),), goal="g"))]

    for name in det.DETECTORS:
        monkeypatch.setitem(det.DETECTORS, name, (lambda ctx: _none()) if name != "job_followups" else detector)
    await client.put("/api/v1/proactive/config", json={"enabled": False})
    r = await client.post("/api/v1/proactive/scan")
    assert r.status_code == 200 and r.json() == {"created": 1, "rejected": {}}
    assert (await client.post("/api/v1/proactive/scan")).json() == {"created": 0, "rejected": {"duplicate": 1}}


async def _none():
    return []


async def _yes():
    return True

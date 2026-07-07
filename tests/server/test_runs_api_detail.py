"""Tests for the run-detail P2 fields, manual redact endpoints, and the
run_debug_retention_days setting exposed via REST (Task 7 of the run-inspector plan)."""
from __future__ import annotations

import pytest

from server.db import session as db_session
from server.db.models import Run


@pytest.fixture(autouse=True)
def _redact_uses_test_db(client, monkeypatch):
    """run_redact.{redact_run,redact_all} open sessions via db_session.AsyncSessionLocal
    directly (not the get_session dependency), so point that module-level session
    factory at the same isolated per-test engine the `client` fixture already uses."""
    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)


NEW_RUN_FIELDS = (
    "model", "provider", "tokens_in", "tokens_out", "tokens_estimated",
    "error_kind", "error_text", "system_prompt", "injected_kb",
)


async def _seed_run(client, **overrides) -> int:
    defaults = dict(
        conversation_id="c1", spawn_name="Mermer", user_message="x",
        status="scored", task_tokens=42, total_ms=1500,
        overall_score=8.0, overall_badge="good",
        model="gpt-4o", provider="openai", tokens_in=100, tokens_out=50,
        tokens_estimated=False, error_kind=None, error_text=None,
        system_prompt="you are a helpful assistant", injected_kb="some kb text",
    )
    defaults.update(overrides)
    async with client.db_maker() as db:
        run = Run(**defaults)
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return run.id


async def test_run_detail_returns_new_fields(client):
    run_id = await _seed_run(client)

    resp = await client.get(f"/api/v1/runs/{run_id}")
    assert resp.status_code == 200
    body = resp.json()["run"]
    for f in NEW_RUN_FIELDS:
        assert f in body
    assert body["model"] == "gpt-4o"
    assert body["provider"] == "openai"
    assert body["tokens_in"] == 100
    assert body["tokens_out"] == 50
    assert body["tokens_estimated"] is False
    assert body["system_prompt"] == "you are a helpful assistant"
    assert body["injected_kb"] == "some kb text"


async def test_run_detail_new_fields_default_none(client):
    async with client.db_maker() as db:
        run = Run(conversation_id="c1", spawn_name="Mermer", user_message="x",
                  status="scored", task_tokens=0, total_ms=100,
                  overall_score=8.0, overall_badge="good")
        db.add(run)
        await db.commit()
        await db.refresh(run)
        run_id = run.id

    body = (await client.get(f"/api/v1/runs/{run_id}")).json()["run"]
    assert body["model"] is None
    assert body["provider"] is None
    assert body["tokens_in"] is None
    assert body["tokens_out"] is None
    assert body["tokens_estimated"] is False
    assert body["error_kind"] is None
    assert body["error_text"] is None
    assert body["system_prompt"] is None
    assert body["injected_kb"] is None


async def test_redact_run_endpoint(client):
    run_id = await _seed_run(client)

    resp = await client.post(f"/api/v1/runs/{run_id}/redact")
    assert resp.status_code == 200
    assert resp.json() == {"redacted": True}

    body = (await client.get(f"/api/v1/runs/{run_id}")).json()["run"]
    assert body["system_prompt"] is None
    assert body["injected_kb"] is None
    # non-sensitive fields untouched
    assert body["model"] == "gpt-4o"


async def test_redact_run_endpoint_missing_run_is_noop(client):
    resp = await client.post("/api/v1/runs/9999/redact")
    assert resp.status_code == 200
    assert resp.json() == {"redacted": True}


async def test_redact_all_endpoint(client):
    id1 = await _seed_run(client, conversation_id="c1")
    id2 = await _seed_run(client, conversation_id="c2")

    resp = await client.post("/api/v1/runs/redact-all")
    assert resp.status_code == 200
    assert resp.json() == {"redacted": 2}

    for rid in (id1, id2):
        body = (await client.get(f"/api/v1/runs/{rid}")).json()["run"]
        assert body["system_prompt"] is None
        assert body["injected_kb"] is None


async def test_settings_roundtrip_retention_days(client):
    resp = await client.put("/api/v1/settings", json={"run_debug_retention_days": 7})
    assert resp.status_code == 200
    assert resp.json()["run_debug_retention_days"] == 7

    resp2 = await client.get("/api/v1/settings")
    assert resp2.status_code == 200
    assert resp2.json()["run_debug_retention_days"] == 7


async def test_settings_retention_days_defaults_30(client):
    resp = await client.get("/api/v1/settings")
    assert resp.status_code == 200
    assert resp.json()["run_debug_retention_days"] == 30

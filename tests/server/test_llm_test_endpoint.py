"""Tests for LLM connection-test endpoints.

Covers:
  POST /settings/test-llm            — raw fields (provider, model, base_url, api_key)
  POST /settings/provider-configs/{id}/test  — test a saved config by id

Network calls are always stubbed via monkeypatch on LLMAdapter.chat so no
real API keys or HTTP connections are needed.
"""
from __future__ import annotations

import pytest
from arslan.models import LLMResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ok_response() -> LLMResponse:
    return LLMResponse(content="pong", tool_calls=[], usage={})


# ---------------------------------------------------------------------------
# POST /settings/test-llm
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_llm_success(client, monkeypatch):
    """Stubbed-success adapter → {ok: true, latency_ms is set}."""

    async def _fake_chat(self, system, user, **kwargs):  # noqa: ARG001
        return _make_ok_response()

    monkeypatch.setattr("arslan.llm.adapter.LLMAdapter.chat", _fake_chat)

    r = await client.post("/api/v1/settings/test-llm", json={
        "provider": "deepseek",
        "model": "deepseek-chat",
        "base_url": "",
        "api_key": "sk-real1234abcd",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["error"] is None
    assert isinstance(body["latency_ms"], int)
    assert body["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_test_llm_adapter_raises(client, monkeypatch):
    """Stubbed failure (exception) → {ok: false, error non-empty}, NOT a 500."""

    async def _bad_chat(self, system, user, **kwargs):  # noqa: ARG001
        raise RuntimeError("invalid api key")

    monkeypatch.setattr("arslan.llm.adapter.LLMAdapter.chat", _bad_chat)

    r = await client.post("/api/v1/settings/test-llm", json={
        "provider": "openai",
        "model": "gpt-4o",
        "base_url": "",
        "api_key": "sk-badkey1111xxxx",
    })
    assert r.status_code == 200  # must NOT 500
    body = r.json()
    assert body["ok"] is False
    assert body["error"]  # non-empty string
    assert body["latency_ms"] is None


@pytest.mark.asyncio
async def test_test_llm_masked_key(client, monkeypatch):
    """Masked key → {ok: false, error mentions 'real'} without attempting a call."""
    called = []

    async def _chat_should_not_be_called(self, system, user, **kwargs):
        called.append(True)
        return _make_ok_response()

    monkeypatch.setattr("arslan.llm.adapter.LLMAdapter.chat", _chat_should_not_be_called)

    r = await client.post("/api/v1/settings/test-llm", json={
        "provider": "openai",
        "model": "gpt-4o",
        "base_url": "",
        "api_key": "sk-...abcd",  # masked shape
    })
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "real" in (body["error"] or "").lower()
    assert called == []  # adapter.chat must NOT have been called


@pytest.mark.asyncio
async def test_test_llm_empty_key(client, monkeypatch):
    """Empty api_key → {ok: false, error mentions 'real'} without attempting a call."""
    called = []

    async def _chat_should_not_be_called(self, system, user, **kwargs):
        called.append(True)
        return _make_ok_response()

    monkeypatch.setattr("arslan.llm.adapter.LLMAdapter.chat", _chat_should_not_be_called)

    r = await client.post("/api/v1/settings/test-llm", json={
        "provider": "openai",
        "model": "gpt-4o",
        "base_url": "",
        "api_key": "",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "real" in (body["error"] or "").lower()
    assert called == []


# ---------------------------------------------------------------------------
# POST /settings/provider-configs/{id}/test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_saved_config_success(client, monkeypatch):
    """Saved config exists + stubbed-success adapter → {ok: true}."""

    async def _fake_chat(self, system, user, **kwargs):  # noqa: ARG001
        return _make_ok_response()

    monkeypatch.setattr("arslan.llm.adapter.LLMAdapter.chat", _fake_chat)

    # Seed a provider config
    r = await client.post("/api/v1/settings/provider-configs", json={
        "label": "Test DeepSeek", "provider": "deepseek", "model": "deepseek-chat",
        "base_url": "", "api_key": "sk-real9999zzzz",
    })
    assert r.status_code == 200
    cid = r.json()["id"]

    r2 = await client.post(f"/api/v1/settings/provider-configs/{cid}/test")
    assert r2.status_code == 200
    body = r2.json()
    assert body["ok"] is True
    assert body["error"] is None
    assert isinstance(body["latency_ms"], int)


@pytest.mark.asyncio
async def test_test_saved_config_unknown_id(client):
    """Unknown config id → 404."""
    r = await client.post("/api/v1/settings/provider-configs/99999/test")
    assert r.status_code == 404

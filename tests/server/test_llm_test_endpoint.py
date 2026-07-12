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
async def test_test_llm_empty_key_proceeds_to_connection_test(client, monkeypatch):
    """D3 empty-key unification: an empty api_key is a legitimate config
    (keyless local servers: LM Studio, vLLM, ollama) — the raw test endpoint
    must run test_connection and return ITS result, consistent with the
    saved-config test path. Only masked keys are rejected up front."""
    calls: list[dict] = []

    async def _fake_test_connection(*, provider, model, base_url, api_key):
        calls.append({"provider": provider, "model": model,
                      "base_url": base_url, "api_key": api_key})
        return {"ok": True, "error": None, "latency_ms": 12}

    monkeypatch.setattr("server.api.settings.test_connection", _fake_test_connection)

    r = await client.post("/api/v1/settings/test-llm", json={
        "provider": "custom",
        "model": "my-model",
        "base_url": "http://localhost:1234/v1",
        "api_key": "",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["error"] is None
    assert body["latency_ms"] == 12
    assert calls == [{"provider": "custom", "model": "my-model",
                      "base_url": "http://localhost:1234/v1", "api_key": ""}]


@pytest.mark.asyncio
async def test_test_llm_masked_key_never_reaches_test_connection(client, monkeypatch):
    """Masked keys stay rejected BEFORE test_connection (the GET→PUT echo
    guard) — only the empty-key branch was relaxed by D3."""
    calls = []

    async def _fake_test_connection(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "error": None, "latency_ms": 1}

    monkeypatch.setattr("server.api.settings.test_connection", _fake_test_connection)

    r = await client.post("/api/v1/settings/test-llm", json={
        "provider": "openai",
        "model": "gpt-4o",
        "base_url": "",
        "api_key": "sk-...abcd",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "real" in (body["error"] or "").lower()
    assert calls == []


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


# ---------------------------------------------------------------------------
# test_connection — 401/403 friendly error (Provider P3)
# ---------------------------------------------------------------------------


def _raise_http_status(status: int):
    import httpx

    async def _chat(self, system, user, **kwargs):  # noqa: ARG001
        request = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
        response = httpx.Response(status, request=request)
        raise httpx.HTTPStatusError(f"HTTP {status}", request=request, response=response)

    return _chat


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_test_connection_auth_status_maps_to_friendly_error(monkeypatch, status):
    """A keyless test against a key-requiring server (401/403) must explain
    "this server wants an API key" instead of dumping the raw exception."""
    from server.services.llm_test import test_connection

    monkeypatch.setattr("arslan.llm.adapter.LLMAdapter.chat", _raise_http_status(status))
    result = await test_connection("custom", "m", "http://localhost:1234/v1", "")
    assert result["ok"] is False
    assert result["latency_ms"] is None
    assert "API key" in result["error"]
    assert str(status) in result["error"]


@pytest.mark.asyncio
async def test_test_connection_other_http_status_keeps_generic_error(monkeypatch):
    """Everything except 401/403 keeps the raw error message (unchanged path)."""
    from server.services.llm_test import test_connection

    monkeypatch.setattr("arslan.llm.adapter.LLMAdapter.chat", _raise_http_status(500))
    result = await test_connection("custom", "m", "http://localhost:1234/v1", "")
    assert result["ok"] is False
    assert "API key" not in result["error"]
    assert "500" in result["error"]

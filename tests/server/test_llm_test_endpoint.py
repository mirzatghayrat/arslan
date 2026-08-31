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


# ---------------------------------------------------------------------------
# The test button must give the SAME diagnosis as a real turn
#
# test_connection() had its own crude 401/403 branch that answered "该服务器要求
# API key" for every refusal in those statuses. For an OpenRouter key whose CAP
# is exhausted (403 "key limit exceeded") that sentence is not merely vague, it
# points the wrong way: it sends someone to replace a key that is perfectly
# valid. llm_errors.explain() already draws that distinction for the chat path
# (#67) — these tests pin the test button to the same explanation, so the two
# surfaces can never disagree about the same failure again.
# ---------------------------------------------------------------------------

def _http_error(status: int, body: str):
    """An HTTPStatusError shaped like the one providers/openai_provider raises:
    the provider's own body text carried into the message, which is what
    str(exc) — and therefore explain() — actually sees."""
    import httpx
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(status, request=request, text=body)
    return httpx.HTTPStatusError(f"{status} error: {body}", request=request, response=response)


@pytest.mark.parametrize(
    ("status", "body", "expect_fragment", "must_not_contain"),
    [
        # The case that sent the user hunting for a new key: the key is valid,
        # its CAP is spent. 403 — the status the old branch swallowed.
        (403, '{"error":{"message":"Key limit exceeded","code":403}}',
         "额度上限", "要求 API key"),
        # Same fault, the other status providers use for it.
        (402, '{"error":{"message":"key limit exceeded"}}',
         "额度上限", "要求 API key"),
        # A region block is not an auth problem either — 403 again.
        (403, '{"error":{"message":"Model not available in your region"}}',
         "地区", "要求 API key"),
        # A genuinely invalid key still reads as a key problem.
        (401, '{"error":{"message":"Invalid API key provided"}}',
         "key", None),
    ],
)
@pytest.mark.asyncio
async def test_the_reason_matches_the_real_fault(
    client, monkeypatch, status, body, expect_fragment, must_not_contain
):
    async def _fail(self, system, user, **kwargs):  # noqa: ARG001
        raise _http_error(status, body)

    monkeypatch.setattr("arslan.llm.adapter.LLMAdapter.chat", _fail)

    r = await client.post("/api/v1/settings/test-llm", json={
        "provider": "custom", "model": "x",
        "base_url": "https://openrouter.ai/api/v1", "api_key": "sk-or-abc123",
    })
    assert r.status_code == 200
    error = r.json()["error"] or ""
    assert r.json()["ok"] is False
    assert expect_fragment in error, f"got: {error}"
    if must_not_contain:
        # The load-bearing half: a wrong-direction answer is worse than a vague
        # one, because acting on it costs the user a key rotation for nothing.
        assert must_not_contain not in error, f"misdiagnosed as an auth fault: {error}"


@pytest.mark.asyncio
async def test_a_request_that_never_left_is_not_blamed_on_the_key(client, monkeypatch):
    """A proxy/VPN failure must not read as a key refusal — the same ordering
    rule llm_errors applies for the chat path."""
    import httpx

    async def _fail(self, system, user, **kwargs):  # noqa: ARG001
        raise httpx.ConnectError("[SSL] record layer failure (_ssl.c:1010)")

    monkeypatch.setattr("arslan.llm.adapter.LLMAdapter.chat", _fail)

    r = await client.post("/api/v1/settings/test-llm", json={
        "provider": "custom", "model": "x",
        "base_url": "https://openrouter.ai/api/v1", "api_key": "sk-or-abc123",
    })
    error = r.json()["error"] or ""
    assert "没能连上" in error, f"got: {error}"
    # NB: the correct message mentions the key in order to RULE IT OUT ("不是 key
    # 的问题"), so absence-of-"key" would be the wrong assertion. What must not
    # appear is the auth verdict — the one that sends someone to replace a key.
    assert "拒绝了 API key" not in error, f"blamed the key for a transport fault: {error}"
    assert "要求 API key" not in error, f"blamed the key for a transport fault: {error}"

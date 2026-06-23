"""Tests for POST /api/v1/orchestrator/title — conversation auto-titling.

All LLM calls are stubbed via monkeypatch on arslan.llm.adapter.LLMAdapter.chat
so no real network calls are made.

Pattern: seed a provider config first (so build_adapter can construct an adapter
with a non-empty api_key), then monkeypatch LLMAdapter.chat to stub the network.
"""
from __future__ import annotations

import pytest
from arslan.models import LLMResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(content: str | None) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=[], usage={})


async def _seed_provider(client, monkeypatch) -> None:
    """Seed a provider config and patch AsyncSessionLocal to the test DB.

    build_adapter() opens its own session via AsyncSessionLocal directly
    (bypassing FastAPI DI), so we must point it at the same test DB that
    the client fixture uses.
    """
    import server.db.session as db_session

    # Patch AsyncSessionLocal so build_adapter reads from the test DB
    monkeypatch.setattr(db_session, "AsyncSessionLocal", client.db_maker)

    r = await client.post("/api/v1/settings/provider-configs", json={
        "label": "Test", "provider": "deepseek", "model": "deepseek-chat",
        "base_url": "", "api_key": "sk-test1234abcd",
    })
    assert r.status_code == 200, f"seed failed: {r.text}"


# ---------------------------------------------------------------------------
# Endpoint tests (async, uses `client` fixture from conftest.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_title_clean_response(client, monkeypatch):
    """Stubbed chat returns a clean title → endpoint echoes it unchanged."""
    await _seed_provider(client, monkeypatch)

    async def _fake_chat(self, system, user, **kwargs):  # noqa: ARG001
        return _make_response("GitHub Capability Inquiry")

    monkeypatch.setattr("arslan.llm.adapter.LLMAdapter.chat", _fake_chat)

    r = await client.post("/api/v1/orchestrator/title", json={
        "first_message": "Can you help me with GitHub?",
    })
    assert r.status_code == 200
    assert r.json()["title"] == "GitHub Capability Inquiry"


@pytest.mark.asyncio
async def test_title_junk_cleaned(client, monkeypatch):
    """Stubbed chat returns junk-wrapped content → cleaned before returning."""
    await _seed_provider(client, monkeypatch)

    async def _fake_chat(self, system, user, **kwargs):  # noqa: ARG001
        return _make_response('"  GitHub 能力咨询。\n\n"')

    monkeypatch.setattr("arslan.llm.adapter.LLMAdapter.chat", _fake_chat)

    r = await client.post("/api/v1/orchestrator/title", json={
        "first_message": "GitHub 有哪些功能？",
        "first_reply": "GitHub 是一个代码托管平台...",
    })
    assert r.status_code == 200
    title = r.json()["title"]
    # No surrounding quotes, no newlines, no trailing period
    assert '"' not in title
    assert "\n" not in title
    assert not title.endswith("。")
    assert "GitHub" in title


@pytest.mark.asyncio
async def test_title_llm_raises_returns_fallback(client, monkeypatch):
    """When LLM raises, endpoint returns 200 with a non-empty fallback title."""
    await _seed_provider(client, monkeypatch)

    async def _bad_chat(self, system, user, **kwargs):  # noqa: ARG001
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr("arslan.llm.adapter.LLMAdapter.chat", _bad_chat)

    r = await client.post("/api/v1/orchestrator/title", json={
        "first_message": "What is the meaning of life?",
    })
    assert r.status_code == 200
    title = r.json()["title"]
    assert isinstance(title, str)
    assert len(title) > 0


@pytest.mark.asyncio
async def test_title_llm_returns_none_uses_fallback(client, monkeypatch):
    """When LLM returns content=None, endpoint falls back to first_message."""
    await _seed_provider(client, monkeypatch)

    async def _none_chat(self, system, user, **kwargs):  # noqa: ARG001
        return _make_response(None)

    monkeypatch.setattr("arslan.llm.adapter.LLMAdapter.chat", _none_chat)

    r = await client.post("/api/v1/orchestrator/title", json={
        "first_message": "Hello world test",
    })
    assert r.status_code == 200
    title = r.json()["title"]
    assert isinstance(title, str)
    assert len(title) > 0


# ---------------------------------------------------------------------------
# Unit tests for generate_title directly (cleanup + fallback logic)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_title_unit_clean(monkeypatch):
    """Unit: generate_title cleans junk from LLM output."""
    from server.services.titler import generate_title

    async def _fake_chat(self, system, user, **kwargs):  # noqa: ARG001
        return _make_response('"  Test Title Here.\n\nExtra line"')

    monkeypatch.setattr("arslan.llm.adapter.LLMAdapter.chat", _fake_chat)

    # We need a real DB for build_adapter; monkeypatch build_adapter directly instead
    from server.services import llm_factory
    from arslan.llm.adapter import LLMAdapter

    async def _fake_build_adapter(role=None):  # noqa: ARG001
        return LLMAdapter("openai", "gpt-4o", api_key="fake")

    monkeypatch.setattr(llm_factory, "build_adapter", _fake_build_adapter)

    result = await generate_title("some question")
    assert '"' not in result
    assert "\n" not in result
    # Trailing period should be stripped
    assert not result.endswith(".")


@pytest.mark.asyncio
async def test_generate_title_unit_fallback(monkeypatch):
    """Unit: generate_title falls back to first_message when LLM raises."""
    from server.services.titler import generate_title
    from server.services import llm_factory
    from arslan.llm.adapter import LLMAdapter

    async def _bad_chat(self, system, user, **kwargs):  # noqa: ARG001
        raise ValueError("no key")

    async def _fake_build_adapter(role=None):  # noqa: ARG001
        return LLMAdapter("openai", "gpt-4o", api_key="fake")

    monkeypatch.setattr(llm_factory, "build_adapter", _fake_build_adapter)
    monkeypatch.setattr("arslan.llm.adapter.LLMAdapter.chat", _bad_chat)

    result = await generate_title("What is the capital of France?")
    assert isinstance(result, str)
    assert len(result) > 0
    # Fallback is derived from first_message
    assert "France" in result or len(result) <= 24 + 3  # truncated with ellipsis or direct


@pytest.mark.asyncio
async def test_generate_title_unit_cap_length(monkeypatch):
    """Unit: generate_title caps title at 48 chars."""
    from server.services.titler import generate_title
    from server.services import llm_factory
    from arslan.llm.adapter import LLMAdapter

    long_title = "A" * 100

    async def _fake_chat(self, system, user, **kwargs):  # noqa: ARG001
        return _make_response(long_title)

    async def _fake_build_adapter(role=None):  # noqa: ARG001
        return LLMAdapter("openai", "gpt-4o", api_key="fake")

    monkeypatch.setattr(llm_factory, "build_adapter", _fake_build_adapter)
    monkeypatch.setattr("arslan.llm.adapter.LLMAdapter.chat", _fake_chat)

    result = await generate_title("some question")
    assert len(result) <= 48

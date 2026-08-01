"""The fitness matrix, measured against the wire rather than against the source.

A hand-maintained compatibility table is decoration within one release: nobody
notices when the code moves out from under it. So the load-bearing test here
captures the ACTUAL HTTP body each provider builds — through a mock transport,
with no network — and fails if the table disagrees with what is sent.

That is also how the entries were produced in the first place. Reading
anthropic_provider.py tells you what someone meant; capturing the request tells
you that `tools` is not in it.
"""
from __future__ import annotations

import json

import httpx
import pytest

from server.services import capability_fitness as fit


def _capture(provider, reply: dict, tools: list[dict]) -> dict:
    """Run one chat() against a mock transport and return the request body."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content or b"{}"))
        return httpx.Response(200, json=reply)

    original = httpx.AsyncClient.__init__

    def patched(self, *a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return original(self, *a, **kw)

    httpx.AsyncClient.__init__ = patched
    try:
        import asyncio

        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            provider.chat([{"role": "user", "content": "hi"}], tools=tools))
    except Exception:  # noqa: BLE001 — a shape mismatch in the fake reply is fine;
        pass           # the request was already captured before any parsing.
    finally:
        httpx.AsyncClient.__init__ = original
    return seen


TOOLS = [{"type": "function",
          "function": {"name": "web_search", "description": "search",
                       "parameters": {"type": "object", "properties": {}}}}]


def _openai():
    from arslan.llm.providers.openai_provider import OpenAIProvider
    return OpenAIProvider(model="gpt", api_key="k", base_url="http://x/v1"), \
        {"choices": [{"message": {"content": "ok"}}], "usage": {}}


def _anthropic():
    from arslan.llm.providers.anthropic_provider import AnthropicProvider
    return AnthropicProvider(model="claude", api_key="k"), \
        {"content": [{"type": "text", "text": "ok"}], "usage": {}}


def _gemini():
    from arslan.llm.providers.gemini_provider import GeminiProvider
    return GeminiProvider(model="gemini", api_key="k"), \
        {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}


@pytest.mark.parametrize("name,factory", [
    ("openai", _openai), ("anthropic", _anthropic), ("gemini", _gemini)])
def test_the_table_matches_what_goes_on_the_wire(name, factory):
    """The anti-rot assertion, and the reason this file exists.

    If a provider starts sending tools, this fails and the table must be
    updated — which is the correct direction: the matrix should never claim a
    capability works before the transport does, and should never keep claiming
    it is broken after somebody fixes it."""
    provider, reply = factory()
    body = _capture(provider, reply, TOOLS)
    on_the_wire = any(k in body for k in ("tools", "toolConfig", "tool_config"))

    claimed = fit.NATIVE_TOOL_CALLS[name]
    assert (claimed == fit.SUPPORTED) == on_the_wire, (
        f"the matrix says {name} is {claimed}, but the request body "
        f"{'contains' if on_the_wire else 'does not contain'} tool definitions. "
        f"body keys: {sorted(body)}")


def test_the_capture_really_sees_a_request():
    """(0) pre-assertion. If the mock transport were never reached, every body
    would be empty, "no tools on the wire" would be trivially true, and the
    parametrised test above would confirm the matrix against nothing."""
    provider, reply = _openai()
    body = _capture(provider, reply, TOOLS)
    assert body, "no request was captured — the transport patch did not take"
    assert body.get("model") == "gpt"


# ---------------------------------------------------------------------------
# The honesty rules
# ---------------------------------------------------------------------------

def test_an_unknown_provider_is_unverified_not_assumed_fine():
    """The default that this whole module exists to change."""
    assert fit.tool_calling_state("some-new-provider") == fit.UNVERIFIED
    assert fit.tool_calling_state(None) == fit.UNVERIFIED
    assert fit.tool_calling_state("") == fit.UNVERIFIED


def test_unverified_says_nobody_checked_rather_than_naming_a_limit():
    reason = fit.tool_calling_reason("some-new-provider")
    assert "nobody has checked" in reason


def test_the_reason_blames_arslan_not_the_users_model():
    """A user told "your model does not support tools" goes shopping for a
    different subscription to fix OUR gap. The affected provider's models can
    call tools perfectly well; Arslan does not send them.

    Anthropic left this list in G1 — it now transmits tools, so it has no reason
    string any more. A reason exists to explain something that will NOT run;
    keeping a stale one would surface it beside a capability that now does."""
    for provider in ("gemini",):
        reason = fit.tool_calling_reason(provider)
        assert "Arslan" in reason, reason
        assert "will not be called" in reason


def test_capabilities_are_annotated_and_never_left_blank():
    caps = [{"key": "playwright"}, {"key": "some-skill", "needs_tool_calls": False}]
    # gemini, not anthropic: this test is about the MECHANISM (never leave a
    # capability unannotated), so it needs a provider that genuinely still drops
    # tools. Anthropic was that example until G1 made it work.
    out = fit.assess("gemini", caps)
    assert {c["key"]: c["fitness"] for c in out} == {
        "playwright": fit.UNSUPPORTED,
        # a prompt-injected skill does not need the tool transport, so the gap
        # does not apply to it — marking everything unsupported would be its own
        # dishonesty
        "some-skill": fit.SUPPORTED,
    }
    assert all("fitness" in c for c in out)


def test_a_working_provider_gets_no_scary_note():
    """The discriminating twin: a matrix that flagged everything would pass
    every test above while making the library useless."""
    out = fit.assess("openai", [{"key": "playwright"}])
    assert out[0]["fitness"] == fit.SUPPORTED
    assert out[0]["fitness_reason"] is None
    assert fit.tool_calling_reason("openai") is None


# ---------------------------------------------------------------------------
# The endpoint. A module nobody calls is not honesty, it is a file.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_registry_endpoint_reports_the_gap(monkeypatch):
    """Integration half: the fitness has to reach the page.

    Asserted through the real endpoint because the shape that keeps catching me
    is a correct helper with no caller."""
    from server.api import registry as registry_api
    from server.services import settings_service

    async def fake_settings(session):
        # see above — the endpoint test needs a provider with a live gap
        return {"llm_provider": "gemini"}

    monkeypatch.setattr(settings_service, "get_settings", fake_settings)

    class _Result:
        def scalars(self):
            class _S:
                def all(self_inner):
                    return []
            return _S()

    class _Session:
        async def execute(self, *a, **k):
            return _Result()

    out = await registry_api.get_registry(session=_Session())
    assert out.tool_calling == fit.UNSUPPORTED
    assert out.tool_calling_note and "Arslan" in out.tool_calling_note


@pytest.mark.asyncio
async def test_the_endpoint_says_unverified_when_the_provider_is_unreadable(monkeypatch):
    """A settings read that fails must not silently render as "fine"."""
    from server.api import registry as registry_api
    from server.services import settings_service

    async def boom(session):
        raise RuntimeError("no settings")

    monkeypatch.setattr(settings_service, "get_settings", boom)

    class _Result:
        def scalars(self):
            class _S:
                def all(self_inner):
                    return []
            return _S()

    class _Session:
        async def execute(self, *a, **k):
            return _Result()

    out = await registry_api.get_registry(session=_Session())
    assert out.tool_calling == fit.UNVERIFIED

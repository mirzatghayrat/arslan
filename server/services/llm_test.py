"""LLM connection-test helper.

Called by both /settings/test-llm (raw fields) and
/settings/provider-configs/{id}/test (saved config).

Returns ``{ok: bool, error: str | None, latency_ms: int | None}``.
"""
from __future__ import annotations

import time

import httpx

from arslan.llm.adapter import LLMAdapter
from arslan.llm.presets import expand_preset

# Smallest possible ping prompt — one token of output is enough.
_PING_SYSTEM = "Reply with one word."
_PING_USER = "ping"

# Seconds before we give up waiting for the provider.
_TIMEOUT_S = 15.0


async def test_connection(
    provider: str,
    model: str,
    base_url: str,
    api_key: str,
) -> dict:
    """Make a minimal chat call and return a result dict.

    This function MUST NOT raise — all exceptions are caught and returned as
    ``{ok: False, error: "…", latency_ms: None}``.
    """
    import asyncio

    # Expand a preset name (e.g. "deepseek") into concrete provider/model/base_url.
    real_provider, real_model, real_base_url = expand_preset(provider, model, base_url)

    adapter = LLMAdapter(real_provider, real_model, api_key=api_key, base_url=real_base_url)

    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(
            adapter.chat(_PING_SYSTEM, _PING_USER),
            timeout=_TIMEOUT_S,
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return {"ok": True, "error": None, "latency_ms": latency_ms}
    except Exception as exc:  # noqa: BLE001
        # Order matters, most-specific first.
        #
        # (1) With NO key configured, a 401/403 really does mean "this endpoint
        # wants an API key" (P3's case: a keyless test against LiteLLM with auth
        # on). This has to outrank the generic explanation below, which would
        # otherwise tell someone to go replace a key that does not exist.
        if (not api_key
                and isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code in (401, 403)):
            status = exc.response.status_code
            return {"ok": False, "error": f"该服务器要求 API key(HTTP {status})",
                    "latency_ms": None}

        # (2) Otherwise give the SAME explanation the chat path gives (#67). The
        # old code guessed from the status alone and answered every 401/403 with
        # "this server wants an API key" — but a 403 is "key limit exceeded" as
        # often as it is "bad key", and answering the first with the second sends
        # someone to rotate a key that was never the problem. A test button that
        # disagrees with the turn it is meant to predict is worse than none.
        #
        # Imported here, not at module scope: server.orchestrator's package init
        # is heavy and this module is pulled in eagerly by the settings API.
        from server.orchestrator import llm_errors

        explained = llm_errors.explain(str(exc))
        if explained:
            return {"ok": False, "error": explained, "latency_ms": None}
        return {"ok": False, "error": str(exc) or "connection failed", "latency_ms": None}

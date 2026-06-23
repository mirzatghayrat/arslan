"""LLM connection-test helper.

Called by both /settings/test-llm (raw fields) and
/settings/provider-configs/{id}/test (saved config).

Returns ``{ok: bool, error: str | None, latency_ms: int | None}``.
"""
from __future__ import annotations

import time

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
        return {"ok": False, "error": str(exc) or "connection failed", "latency_ms": None}

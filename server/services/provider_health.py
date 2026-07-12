"""Provider-P4: tri-state connectivity probe for saved provider configs.

Settings-only surface (same rule as model_catalog): imported from
server/api/settings.py and tests only — probes fire on explicit Settings
interactions, never from the chat path and never on a background schedule
(spec decision D4: no polling).

States:
- "reachable_models":  the provider answered with a non-empty model list.
- "reachable_no_list": HTTP-reachable but no usable list — an empty list, or
  an HTTP error status (401/404/405/500…). NOT "broken": many gateways gate
  /models harder than /chat, so chat may still work fine.
- "unreachable":       connection-level failure (refused / DNS / timeout).
"""
from __future__ import annotations

import asyncio
import time
from urllib.parse import urlparse

import httpx

from server.services import model_catalog

LOCAL_TIMEOUT_S = 3.0    # localhost daemons answer instantly or not at all
REMOTE_TIMEOUT_S = 8.0

_OLLAMA_DEFAULT_BASE = "http://localhost:11434"


def _effective_base(provider: str, base_url: str) -> str:
    """Mirror fetch_models' blank-base_url defaults so the timeout is chosen
    for the host the probe will ACTUALLY hit (native defaults are remote;
    ollama's default daemon is local)."""
    if base_url:
        return base_url
    if provider == "anthropic":
        return model_catalog._ANTHROPIC_DEFAULT_BASE
    if provider == "gemini":
        return model_catalog._GEMINI_DEFAULT_BASE
    if provider == "ollama":
        return _OLLAMA_DEFAULT_BASE
    return base_url


def _timeout_for(provider: str, base_url: str) -> float:
    host = urlparse(_effective_base(provider, base_url)).hostname or ""
    is_local = host in {h.strip("[]") for h in model_catalog.LOCAL_HOSTS}
    return LOCAL_TIMEOUT_S if is_local else REMOTE_TIMEOUT_S


async def probe(provider: str, base_url: str, api_key: str, *,
                transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """Probe one provider config via its model-list endpoint. Never raises.

    ``provider`` is the CONFIG-level key, ``base_url`` the already-expanded
    base URL (expand_preset), ``api_key`` the decrypted key. ``transport`` is
    a test seam (httpx.MockTransport).

    Returns ``{"state": str, "latency_ms": int | None, "detail": str | None}``.
    """
    timeout = _timeout_for(provider, base_url)
    start = time.monotonic()
    try:
        models = await asyncio.wait_for(
            model_catalog.fetch_models(provider, base_url, api_key, transport=transport),
            timeout=timeout)
    except httpx.HTTPStatusError as exc:
        # The server ANSWERED (401/403/404/405/500…) — HTTP-reachable, just no
        # usable list. Chat may still work; the detail carries the status.
        return {"state": "reachable_no_list", "latency_ms": None,
                "detail": f"HTTP {exc.response.status_code}"}
    except Exception as exc:  # noqa: BLE001 — connection error / timeout / parse
        detail = str(exc) or type(exc).__name__  # str(TimeoutError()) is ""
        return {"state": "unreachable", "latency_ms": None, "detail": detail}
    latency_ms = int((time.monotonic() - start) * 1000)
    if models:
        return {"state": "reachable_models", "latency_ms": latency_ms, "detail": None}
    return {"state": "reachable_no_list", "latency_ms": latency_ms, "detail": None}

"""Provider-P2: dynamic model catalog — fetch real model lists from providers.

Settings-only surface: this module may ONLY be imported from server/api/settings.py
(and its own tests). The chat path (server/orchestrator/, arslan/) must never touch
it — model discovery is a Settings-open concern, never a per-message one (round iron
rule, enforced by tests/server/test_model_catalog.py::test_chat_path_never_imports_model_catalog).

Cache policy (model_catalog_cache, one row per provider config):
- fresh  (< TTL_FRESH_S):    serve cache, no network.
- warm   (< TTL_STALE_OK_S): settings-open serves cache; explicit refresh refetches.
  EXCEPTION: local hosts (ollama & friends) refetch eagerly past TTL_FRESH_S — the
  local daemon's tag list changes with every `ollama pull` and costs nothing to list.
- cold   (>= TTL_STALE_OK_S): refetch.
- fingerprint(provider|base_url|api_key) mismatch: cache invalid (config was edited).
- fetch failure: serve stale cache when one exists, else the static seed
  (arslan.llm.catalog) marked source="static" — the UI stays usable offline.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from arslan.llm import catalog
from arslan.llm.presets import expand_preset
from server.db.models import ModelCatalogCache, ProviderConfig
from server.services import provider_config_service

TTL_FRESH_S = 300          # <5min: serve cache, no network
TTL_STALE_OK_S = 86400     # <24h: settings-open does NOT auto-refetch; beyond it, does
LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")

_TIMEOUT_S = 10.0          # overall per-fetch budget
_OLLAMA_SHOW_TIMEOUT_S = 5.0  # per /api/show call (one slow model must not eat the budget)
_GEMINI_MAX_PAGES = 10

# api.openai.com serves embeddings/audio/image models on /models too — they are not
# chat models and would poison the picker. Substring deny-list (openai.com only).
_OPENAI_NON_CHAT = ("embedding", "tts", "whisper", "dall-e", "moderation",
                    "audio", "realtime", "image", "transcribe")

_CAPABILITY_KEYS = ("tools", "vision", "reasoning")


def _info(model_id: str, *, display_name: str | None = None,
          context_window: int | None = None,
          capabilities: list[str] | None = None,
          source: str = "api") -> dict:
    caps = [c for c in (capabilities or []) if c in _CAPABILITY_KEYS]
    return {"id": model_id, "display_name": display_name,
            "context_window": context_window, "capabilities": caps,
            "source": source}


def _fingerprint(provider: str, base_url: str, api_key: str) -> str:
    return hashlib.sha256(
        f"{provider}|{base_url}|{api_key}".encode()).hexdigest()[:16]


def _is_local_host(base_url: str) -> bool:
    host = urlparse(base_url).hostname or ""
    return host in {h.strip("[]") for h in LOCAL_HOSTS}


# ---------------------------------------------------------------------------
# Per-provider fetchers — raise on network/parse errors (the cache layer catches)
# ---------------------------------------------------------------------------


async def _fetch_anthropic(client: httpx.AsyncClient, api_key: str) -> list[dict]:
    resp = await client.get(
        "https://api.anthropic.com/v1/models",
        params={"limit": 1000},
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"})
    resp.raise_for_status()
    out = []
    for entry in resp.json().get("data", []):
        # The models API does not expose per-model caps reliably; all current
        # Claude chat models take tools + images. Context window only if present.
        out.append(_info(entry["id"],
                         display_name=entry.get("display_name"),
                         context_window=entry.get("context_window"),
                         capabilities=["tools", "vision"]))
    return out


async def _fetch_gemini(client: httpx.AsyncClient, api_key: str) -> list[dict]:
    out: list[dict] = []
    page_token: str | None = None
    # NOTE: key goes in the x-goog-api-key header (repo idiom, see
    # arslan/llm/providers/gemini_provider.py) — never in the URL/query string,
    # where it would leak into logs. Google accepts both.
    for _ in range(_GEMINI_MAX_PAGES):
        params: dict[str, str | int] = {"pageSize": 50}
        if page_token:
            params["pageToken"] = page_token
        resp = await client.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params=params, headers={"x-goog-api-key": api_key})
        resp.raise_for_status()
        payload = resp.json()
        for entry in payload.get("models", []):
            if "generateContent" not in entry.get("supportedGenerationMethods", []):
                continue
            model_id = entry.get("name", "")
            model_id = model_id.removeprefix("models/")
            caps = ["tools"]
            if entry.get("thinking"):
                caps.append("reasoning")
            out.append(_info(model_id,
                             display_name=entry.get("displayName"),
                             context_window=entry.get("inputTokenLimit"),
                             capabilities=caps))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return out


async def _fetch_ollama(client: httpx.AsyncClient, base_url: str) -> list[dict]:
    root = (base_url or "http://localhost:11434").rstrip("/")
    root = root.removesuffix("/v1")
    tags = await client.get(f"{root}/api/tags")
    tags.raise_for_status()
    out = []
    for entry in tags.json().get("models", []):
        name = entry.get("name", "")
        caps: list[str] = []
        ctx: int | None = None
        try:
            show = await client.post(f"{root}/api/show", json={"model": name},
                                     timeout=_OLLAMA_SHOW_TIMEOUT_S)
            show.raise_for_status()
            detail = show.json()
            raw_caps = detail.get("capabilities") or []
            caps = [c for c in ("tools", "vision") if c in raw_caps]
            for key, value in (detail.get("model_info") or {}).items():
                if key.endswith(".context_length") and isinstance(value, int):
                    ctx = value
                    break
        except Exception:  # noqa: BLE001 — one broken /api/show must not fail the batch
            caps, ctx = [], None
        out.append(_info(name, capabilities=caps, context_window=ctx))
    return out


async def _fetch_openai_compat(client: httpx.AsyncClient, base_url: str,
                               api_key: str) -> list[dict]:
    # The chat path appends /chat/completions to this same base, so /models is
    # the consistent sibling.
    url = f"{base_url.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    resp = await client.get(url, headers=headers)
    resp.raise_for_status()
    is_openai_com = (urlparse(url).hostname or "") == "api.openai.com"
    out = []
    for entry in resp.json().get("data", []):
        model_id = entry.get("id", "")
        if is_openai_com and any(t in model_id for t in _OPENAI_NON_CHAT):
            continue
        # Presence-based rich fields (OpenRouter ships them; plain OpenAI-compat
        # servers don't) — keyed on the entry shape, never on the provider name.
        caps: list[str] = []
        if "tools" in (entry.get("supported_parameters") or []):
            caps.append("tools")
        ctx = entry.get("context_length")
        out.append(_info(model_id, capabilities=caps,
                         context_window=ctx if isinstance(ctx, int) else None))
    return out


async def fetch_models(provider: str, base_url: str, api_key: str, *,
                       transport: httpx.AsyncBaseTransport | None = None) -> list[dict]:
    """Fetch the live model list for one provider config. Raises on failure.

    ``provider`` is the CONFIG-level key (deepseek/ollama/anthropic/…), not the
    expanded protocol name; ``base_url`` is the already-expanded real base URL.
    ``transport`` is a test seam (httpx.MockTransport).
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT_S, transport=transport) as client:
        if provider == "anthropic":
            return await _fetch_anthropic(client, api_key)
        if provider == "gemini":
            return await _fetch_gemini(client, api_key)
        if provider == "ollama":
            return await _fetch_ollama(client, base_url)
        return await _fetch_openai_compat(client, base_url, api_key)


# ---------------------------------------------------------------------------
# Cache layer
# ---------------------------------------------------------------------------


def _static_fallback(provider: str, error: str) -> dict:
    return {
        "models": [
            {"id": m, "display_name": None, "context_window": None,
             "capabilities": [], "source": "static"}
            for m in catalog.models_for(provider)
        ],
        "fetched_at": None, "stale": True, "error": error, "source": "static",
    }


def _from_cache(row: ModelCatalogCache, *, stale: bool, error: str | None) -> dict:
    return {"models": json.loads(row.models),
            "fetched_at": row.fetched_at.isoformat(),
            "stale": stale, "error": error, "source": "api"}


async def get_models(db: AsyncSession, config_id: int, *, refresh: bool = False) -> dict:
    """Return the model list for one provider config, cache-first.

    Raises LookupError when the config does not exist (the API layer maps it to 404).
    Never raises on network failure — degrades to stale cache, then static seed.
    """
    row = await db.get(ProviderConfig, config_id)
    if row is None:
        raise LookupError(f"provider config {config_id} not found")
    api_key = provider_config_service._safe(row.api_key)
    _, _, base_url = expand_preset(row.provider, row.model, row.base_url or "")
    fp = _fingerprint(row.provider, base_url, api_key)

    cache_row = (await db.execute(select(ModelCatalogCache).where(
        ModelCatalogCache.provider_config_id == config_id))).scalar_one_or_none()
    valid_cache = cache_row if (cache_row is not None and cache_row.fingerprint == fp) else None
    age_s = ((datetime.utcnow() - valid_cache.fetched_at).total_seconds()
             if valid_cache is not None else None)

    must_fetch = (
        refresh
        or valid_cache is None
        or age_s > TTL_STALE_OK_S
        # local providers (ollama & friends) refresh eagerly on settings-open:
        # the tag list changes with every `ollama pull` and listing is free.
        or (_is_local_host(base_url) and age_s > TTL_FRESH_S)
    )
    if not must_fetch:
        return _from_cache(valid_cache, stale=False, error=None)

    try:
        models = await fetch_models(row.provider, base_url, api_key)
    except Exception as exc:  # noqa: BLE001 — degrade, never 500 the Settings page
        if valid_cache is not None:
            return _from_cache(valid_cache, stale=True, error=str(exc))
        return _static_fallback(row.provider, str(exc))

    now = datetime.utcnow()
    if cache_row is None:
        cache_row = ModelCatalogCache(provider_config_id=config_id, fingerprint=fp,
                                      fetched_at=now, models=json.dumps(models))
        db.add(cache_row)
    else:
        cache_row.fingerprint = fp
        cache_row.fetched_at = now
        cache_row.models = json.dumps(models)
    await db.commit()
    return {"models": models, "fetched_at": now.isoformat(),
            "stale": False, "error": None, "source": "api"}

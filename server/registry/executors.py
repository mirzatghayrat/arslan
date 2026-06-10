"""Server-side executors for wired tools. One class per tool, keyed registry.

Adding a tool later = implement Executor + add to EXECUTORS + set the registry
row's status to "wired" in seed_catalog.
"""
from __future__ import annotations

import httpx
import trafilatura

from server.db.session import AsyncSessionLocal
from server.registry.search_providers import get_provider
from server.services import settings_service

_EXTRACT_CHAR_LIMIT = 12_000
_FETCH_TIMEOUT = 20.0


async def _search_provider():
    """Build the configured provider, or None when no key is set."""
    async with AsyncSessionLocal() as db:
        key = await settings_service.get_decrypted(db, "search_api_key")
        name = (await settings_service.get_settings(db)).get("search_provider", "")
    if not key:
        return None
    return get_provider(name, api_key=key)


async def _fetch_text(url: str) -> str:
    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        html = resp.text
    extracted = trafilatura.extract(html)
    return extracted or ""


class WebSearchExecutor:
    key = "web_search"

    async def execute(self, args: dict) -> dict:
        query = (args.get("query") or "").strip()
        if not query:
            return {"ok": False, "error": "missing 'query'"}
        provider = await _search_provider()
        if provider is None:
            return {"ok": False,
                    "error": "web search is not configured (no API key set)"}
        try:
            results = await provider.search(query, num_results=int(args.get("num_results") or 5))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"search failed: {exc}"}
        return {"ok": True, "results": results}


class WebExtractExecutor:
    key = "web_extract"

    async def execute(self, args: dict) -> dict:
        url = (args.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            return {"ok": False, "error": "missing or invalid 'url'"}
        try:
            text = await _fetch_text(url)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"fetch failed: {exc}"}
        if not text:
            return {"ok": False, "error": "no extractable text"}
        return {"ok": True, "url": url, "text": text[:_EXTRACT_CHAR_LIMIT]}


EXECUTORS = {e.key: e for e in (WebSearchExecutor(), WebExtractExecutor())}

"""Server-side executors for wired tools. One class per tool, keyed registry.

Adding a tool later = implement Executor + add to EXECUTORS + set the registry
row's status to "wired" in seed_catalog.

Server executors return {ok, ...} dicts — distinct from the CLI package's ArslanTool/ToolResult protocol.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

import httpx
import trafilatura

from server.db.session import AsyncSessionLocal
from server.registry.search_providers import get_provider
from server.services import settings_service

logger = logging.getLogger(__name__)

_EXTRACT_CHAR_LIMIT = 12_000
_FETCH_TIMEOUT = 20.0


def _is_private_host(url: str) -> bool:
    """SSRF guard: spawn-supplied URLs must not reach loopback/private/link-local
    hosts (incl. cloud metadata 169.254.169.254 and Arslan's own API)."""
    host = urlparse(url).hostname or ""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True  # unresolvable -> refuse
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return True
    return False


def _categorize_exc(exc: Exception) -> str:
    """Map httpx/other exceptions to coarse error category strings."""
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"http {exc.response.status_code}"
    if isinstance(exc, httpx.HTTPError):
        return "network error"
    return "unexpected error"


async def _search_provider():
    """Build the configured provider, or None when no key is set."""
    async with AsyncSessionLocal() as db:
        key = await settings_service.get_decrypted(db, "search_api_key")
        name = (await settings_service.get_settings(db)).get("search_provider", "")
    if not key:
        return None
    return get_provider(name, api_key=key)


async def _fetch_text(url: str) -> str:
    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT, follow_redirects=True) as client:  # NOTE: redirects can still bounce to private hosts; must-fix-before-public-release
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
        try:
            num_results = int(args.get("num_results") or 5)
        except (TypeError, ValueError):
            return {"ok": False, "error": "invalid 'num_results'"}
        provider = await _search_provider()
        if provider is None:
            return {"ok": False,
                    "error": "web search is not configured (no API key set)"}
        try:
            results = await provider.search(query, num_results=num_results)
        except Exception as exc:  # noqa: BLE001
            category = _categorize_exc(exc)
            logger.warning("web_search failed: %s", exc, exc_info=True)
            return {"ok": False, "error": f"search failed: {category}"}
        return {"ok": True, "results": results}


class WebExtractExecutor:
    key = "web_extract"

    async def execute(self, args: dict) -> dict:
        url = (args.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            return {"ok": False, "error": "missing or invalid 'url'"}
        if _is_private_host(url):
            return {"ok": False, "error": "url resolves to a private or internal address"}
        try:
            text = await _fetch_text(url)
        except Exception as exc:  # noqa: BLE001
            category = _categorize_exc(exc)
            logger.warning("web_extract failed for %s: %s", url, exc, exc_info=True)
            return {"ok": False, "error": f"fetch failed: {category}"}
        if not text:
            return {"ok": False, "error": "no extractable text"}
        return {"ok": True, "url": url, "text": text[:_EXTRACT_CHAR_LIMIT]}


EXECUTORS = {e.key: e for e in (WebSearchExecutor(), WebExtractExecutor())}

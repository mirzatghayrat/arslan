"""DeepSeek native web search: one Messages call on the Anthropic-compatible
endpoint with the web_search_20250305 server tool (0.1.49).

Lives with the model providers, not with the web search scrapers: the request
goes to the chat endpoint the user configured, with the chat key, exactly like
a chat turn — so it uses the model transport (loopback-aware, no redirects),
while arbitrary web destinations stay on net_pin (server/registry).
"""
from __future__ import annotations

from typing import Any

import httpx

from arslan.llm.locality import loopback_endpoint


async def native_search(base_url: str, api_key: str, query: str, *, model: str,
                        max_uses: int, max_tokens: int) -> dict[str, Any]:
    body = {"model": model, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": f"Perform a web search for the query: {query}"}]}],
            "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": max_uses}]}
    headers = {"x-api-key": api_key, "Authorization": f"Bearer {api_key}",
               "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
    async with httpx.AsyncClient(trust_env=not loopback_endpoint(base_url), follow_redirects=False) as client:
        resp = await client.post(f"{base_url.rstrip('/')}/messages", json=body, headers=headers,
                                 timeout=httpx.Timeout(90.0, connect=15.0))
    resp.raise_for_status()
    return resp.json()

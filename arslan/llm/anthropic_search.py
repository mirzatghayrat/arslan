"""Anthropic's server-side web search: one short Messages call with the web_search server tool (0.1.63 D5).

Lives with the model providers, beside deepseek_search.py, for the same reason: the request goes to the
Anthropic endpoint this conversation's turn already uses, with its key, so it takes the model transport
(loopback-aware, no redirects), while arbitrary web destinations stay on net_pin (server/registry).
Only an endpoint `LLMAdapter.anthropic_first_party()` accepts gets here: Claude on api.anthropic.com or a
listed verbatim proxy to it (the K1b rule). Another Anthropic-protocol host may not run server tools.
"""
from __future__ import annotations

from typing import Any

import httpx

from arslan.llm.locality import loopback_endpoint

#: The basic tool version, on purpose. Results come back as structured web_search_tool_result blocks, which
#: is all this one-shot search reads. web_search_20260209 adds dynamic filtering (Claude runs code over the
#: results first), which changes what comes back and adds a code step this search has no use for.
TOOL_TYPE = "web_search_20250305"
ANTHROPIC_VERSION = "2023-06-01"


async def native_search(base_url: str, api_key: str, query: str, *, model: str,
                        max_uses: int, max_tokens: int) -> dict[str, Any]:
    body = {"model": model, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": f"Perform a web search for the query: {query}"}]}],
            "tools": [{"type": TOOL_TYPE, "name": "web_search", "max_uses": max_uses}],
            # Haiku 5.5 thinks by default (adaptive). A one-shot search has nothing to reason about, and thinking
            # would spend the small max_tokens before the search. "disabled" is accepted at the default effort.
            "thinking": {"type": "disabled"}}
    headers = {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION, "Content-Type": "application/json"}
    async with httpx.AsyncClient(trust_env=not loopback_endpoint(base_url), follow_redirects=False) as client:
        resp = await client.post(f"{base_url.rstrip('/')}/messages", json=body, headers=headers,
                                 timeout=httpx.Timeout(90.0, connect=15.0))
    resp.raise_for_status()
    return resp.json()

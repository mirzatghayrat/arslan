"""Swappable web-search providers (spec §9.2): Tavily default, never hard-wired."""
from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

_TIMEOUT = 15.0


class SearchProvider(ABC):
    name: str = ""

    @abstractmethod
    async def search(self, query: str, num_results: int = 5) -> list[dict]:
        """Return [{title, url, snippet}, ...]."""


class TavilyProvider(SearchProvider):
    name = "tavily"
    _URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def search(self, query: str, num_results: int = 5) -> list[dict]:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                self._URL,
                json={"api_key": self._api_key, "query": query,
                      "max_results": num_results},
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""),
             "snippet": r.get("content", "")}
            for r in (data.get("results") or [])[:num_results]
        ]


_PROVIDERS: dict[str, type[SearchProvider]] = {"tavily": TavilyProvider}
_DEFAULT = "tavily"


def get_provider(name: str, *, api_key: str) -> SearchProvider:
    key = (name or _DEFAULT).strip().lower()
    cls = _PROVIDERS.get(key)
    if cls is None:
        raise ValueError(f"unknown search provider: {name}")
    return cls(api_key=api_key)

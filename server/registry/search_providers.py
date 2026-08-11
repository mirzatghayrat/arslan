"""Swappable web-search providers. One of them needs no key, and it is the default.

🔴 WHY `requires_key` LIVES ON THE PROVIDER. It used to live in the caller, as
`if not key: return None` evaluated BEFORE the provider was chosen — which made a
keyless provider unreachable by construction, not merely unimplemented. Whether a key
is needed is a fact about the provider, so it is stated by the provider.

THE DEFAULT IS THE KEYLESS ONE. A fresh install that has not signed up anywhere must
still be able to search: "download it and it works" is the promise, and search is the
capability most visibly broken without it. Tavily remains available and better; it is
an upgrade, not a prerequisite.

🔴 AND THE FALLBACK IS HONEST ABOUT ITSELF. It scrapes an HTML endpoint that offers no
contract, can be throttled, and can change shape without notice. That is acceptable
for a fallback and unacceptable as a silent substitute, so it sets
``best_effort = True`` and every result carries the provider that served it. A degraded
answer the user cannot distinguish from a good one is the same silence this whole line
of work exists to remove.
"""
from __future__ import annotations

import html
import re
from abc import ABC, abstractmethod
from urllib.parse import urlparse


from server.registry import net_pin

_TIMEOUT = 15.0


class SearchProvider(ABC):
    name: str = ""
    #: Does this provider need an API key? Defaults to True so a provider that forgets
    #: to say fails toward "ask the user" rather than toward a call that cannot work.
    requires_key: bool = True
    #: True when this provider's destination comes from Settings rather than a
    #: constant here. Kept separate from requires_key because "you have not entered
    #: an address" and "you have not entered a key" need different sentences — one
    #: of them would send the user shopping for a key they never needed.
    requires_base_url: bool = False
    #: True when results come from scraping rather than a supported API. Surfaced to
    #: the user AND to the model, both of which can act on "this may be throttled".
    best_effort: bool = False

    @abstractmethod
    async def search(self, query: str, num_results: int = 5) -> list[dict]:
        """Return [{title, url, snippet}, ...].

        Transport/HTTP errors propagate as raw httpx exceptions; executors are the designated catcher.
        """


class TavilyProvider(SearchProvider):
    name = "tavily"
    requires_key = True
    _URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str, **_: object) -> None:
        # **_ absorbs base_url: the factory hands the same arguments to every provider
        # so that "which provider takes an address" is written once, on the provider,
        # rather than a second time as a branch in get_provider.
        self._api_key = api_key

    async def search(self, query: str, num_results: int = 5) -> list[dict]:
        # allow_host is NOT passed: this destination is a constant in this file, so it
        # has no business carrying the private-network exemption that belongs to an
        # address the user typed.
        resp = await net_pin.pinned_request(
            "POST", self._URL,
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


class DuckDuckGoHtmlProvider(SearchProvider):
    """The zero-key fallback: DuckDuckGo's HTML endpoint, parsed.

    IMPLEMENTED HERE RATHER THAN VIA ``ddgs``, and the reason is not dependency
    minimalism. ``ddgs`` pulls ``primp`` — a Rust HTTP client — so its requests would
    bypass every control in ``net_pin``: the resolve-once pinning, the non-public
    address refusal, the per-hop redirect re-pinning. Adding a search path that our own
    network boundary cannot see, in the same round that puts a user-supplied SearXNG
    address on that boundary, is the wrong trade. (It also keeps two binary extensions
    out of the frozen macOS bundle, which is a real but secondary saving.)

    Measured before being built on: the endpoint answers 200 with parseable results.
    It has no contract, so the parser is written to return FEWER results rather than
    wrong ones, and the provider marks itself best_effort so nothing downstream mistakes
    it for a supported API.
    """

    name = "duckduckgo"
    requires_key = False
    best_effort = True
    _URL = "https://html.duckduckgo.com/html/"
    # A browser UA: the endpoint serves a different, unparseable page to obvious bots.
    _UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
    _RESULT = re.compile(
        r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
    _SNIPPET = re.compile(
        r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', re.S)

    def __init__(self, api_key: str = "", **_: object) -> None:
        self._api_key = api_key      # accepted and ignored: it needs none

    @staticmethod
    def _text(fragment: str) -> str:
        return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()

    async def search(self, query: str, num_results: int = 5) -> list[dict]:
        # Redirects are still followed, but now one hop at a time and re-pinned at
        # each — stricter than the follow_redirects=True this replaces, not looser.
        # allow_host stays None for the same reason as Tavily: constant destination.
        resp = await net_pin.pinned_request("POST", self._URL, data={"q": query},
                                            headers={"User-Agent": self._UA})
        resp.raise_for_status()
        return self.parse(resp.text, num_results)

    @classmethod
    def parse(cls, body: str, num_results: int = 5) -> list[dict]:
        """HTML in, results out — a PURE function, deliberately.

        Extracted from `search` so its behaviour when the page changes shape can be
        tested directly. While it lived inside the request, the only way to observe
        it was through a mocked response, which tests the mock as much as the parser;
        and the thing worth pinning here is not "today's HTML parses" — that stays
        green on the day the parser dies, because the fixture was written the same
        day as the parser. What matters is that an unrecognised shape yields NOTHING
        rather than something plausible and wrong.
        """
        titles = cls._RESULT.findall(body)
        snippets = cls._SNIPPET.findall(body)
        out: list[dict] = []
        for i, (href, title_html) in enumerate(titles[:num_results]):
            url = html.unescape(href)
            # The endpoint sometimes wraps targets in its own redirector; a result we
            # cannot resolve to a real URL is dropped rather than handed on broken.
            if url.startswith("//"):
                url = "https:" + url
            if not url.startswith(("http://", "https://")):
                continue
            out.append({
                "title": cls._text(title_html),
                "url": url,
                "snippet": cls._text(snippets[i]) if i < len(snippets) else "",
            })
        return out


class SearXNGProvider(SearchProvider):
    """A self-hosted SearXNG instance, at whatever address the user typed.

    JSON ONLY. A SearXNG whose ``search.formats`` omits ``json`` answers with HTML,
    and parsing that would yield a perfectly plausible zero results — which reads as
    "nothing matched" when the truth is "this instance never answered the question".
    The quieter untruth is the worse one here, so a non-JSON answer raises and the
    message names the line of settings.yml to change.

    NO FALLBACK, deliberately. People self-host SearXNG so their queries do not leave
    their network. Quietly switching to DuckDuckGo would send the query they hid to a
    third party, and provenance labelling only says so afterwards — by which time it
    has gone. Availability loses to the reason the feature exists.

    NO AUTHENTICATION in this round: LAN instances typically have none. An instance
    behind basic auth or a token cannot be used yet, and that is written in the docs
    rather than left to be discovered as a confusing failure.
    """

    name = "searxng"
    requires_key = False
    requires_base_url = True

    def __init__(self, base_url: str = "", api_key: str = "", **_: object) -> None:
        self.base_url = (base_url or "").rstrip("/")
        # The exemption names THIS host and nothing else. Parsed once here so the
        # per-request call cannot be handed something the user did not configure.
        self._host = urlparse(self.base_url).hostname or ""

    async def search(self, query: str, num_results: int = 5) -> list[dict]:
        resp = await net_pin.pinned_request(
            "GET", f"{self.base_url}/search",
            params={"q": query, "format": "json"},
            headers={"Accept": "application/json"},
            # 🔴 The one call in this file that passes it, and it passes the host the
            # user typed — never a value derived from anything the model produced.
            allow_host=self._host,
        )
        resp.raise_for_status()
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ValueError(
                "the instance answered, but not with JSON — add `json` to "
                "`search.formats` in its settings.yml"
            ) from exc
        if not isinstance(payload, dict) or "results" not in payload:
            raise ValueError(
                "the instance answered with JSON that has no `results` — check that "
                "`search.formats` in its settings.yml includes `json`"
            )
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""),
             "snippet": r.get("content", "")}
            for r in (payload.get("results") or [])[:num_results]
        ]


#: Registered providers. The keyless fallback is the default so a fresh install works.
_PROVIDERS: dict[str, type[SearchProvider]] = {
    "duckduckgo": DuckDuckGoHtmlProvider,
    "tavily": TavilyProvider,
    "searxng": SearXNGProvider,
}
_FALLBACK = "duckduckgo"
_DEFAULT = _FALLBACK


def get_provider(name: str, *, api_key: str = "", base_url: str = "") -> SearchProvider:
    key = (name or _DEFAULT).strip().lower()
    cls = _PROVIDERS.get(key)
    if cls is None:
        raise ValueError(f"unknown search provider: {name}")
    # base_url is passed to every provider and ignored by the ones with a constant
    # destination (their **_ swallows it). Making it conditional on the provider name
    # would put a second copy of "which provider uses an address" in the factory.
    return cls(api_key=api_key, base_url=base_url)


def list_providers() -> list[str]:
    """Registered keys for the Settings dropdown. The keyless default comes first."""
    return [_FALLBACK] + sorted(k for k in _PROVIDERS if k != _FALLBACK)


# net_pin carries every outbound request in this file. It was imported as a placeholder
# for a while, which meant the module said it was hardened and the code was not.
__all__ = ["SearchProvider", "TavilyProvider", "DuckDuckGoHtmlProvider",
           "SearXNGProvider", "get_provider", "list_providers", "net_pin"]

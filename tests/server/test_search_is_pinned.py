"""Search has no bare HTTP client any more.

The previous round's spec predicted this exactly: a hard-coded destination made the
unpinned client tolerable, and a user-typed SearXNG address makes it a hole. These
tests hold the wiring in place so the provider that lands next cannot quietly be the
one that reopens it.
"""
from __future__ import annotations

import inspect

import httpx
import pytest

from server.registry import net_pin, search_providers


def test_no_search_provider_builds_its_own_client():
    """🔴 A source-level assertion, which is normally the wrong tool — but this one
    asserts an ABSENCE, and an absence has no behaviour to observe. The behavioural
    half is test_pinning_is_the_same_on_both_paths.py; this half stops a fresh
    provider from being written with its own client in the first place."""
    src = inspect.getsource(search_providers)
    assert "httpx.AsyncClient(" not in src, (
        "a provider that builds its own client bypasses every control in net_pin"
    )


@pytest.fixture
def record(monkeypatch):
    calls: list[dict] = []

    async def fake(method, url, **kw):
        calls.append({"method": method, "url": url, **kw})
        # The request has to be attached or `raise_for_status()` raises RuntimeError
        # about the missing request instead of doing its job — a fixture failure that
        # reads exactly like a provider failure.
        return httpx.Response(200, json={"results": []},
                              request=httpx.Request(method, url))

    monkeypatch.setattr(net_pin, "pinned_request", fake)
    return calls


async def test_tavily_goes_through_the_pinned_path_without_the_exemption(record):
    await search_providers.TavilyProvider(api_key="k").search("hello")
    assert record, "Tavily did not go through pinned_request at all"
    assert record[0].get("allow_host") is None, (
        "a constant destination must not carry the private-network exemption"
    )
    assert record[0]["method"] == "POST"


async def test_duckduckgo_goes_through_the_pinned_path_without_the_exemption(record):
    await search_providers.DuckDuckGoHtmlProvider().search("hello")
    assert record, "DuckDuckGo did not go through pinned_request at all"
    assert record[0].get("allow_host") is None, (
        "a constant destination must not carry the private-network exemption"
    )
    assert record[0]["method"] == "POST"


def test_the_module_no_longer_claims_net_pin_is_only_a_placeholder():
    """The import used to be annotated as reserved for a future provider, which meant
    the file described itself as hardened while every request bypassed it. Absence
    again — there is no behaviour that distinguishes an honest comment."""
    src = inspect.getsource(search_providers)
    assert "will use when" not in src

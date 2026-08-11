"""SearXNG: JSON only, and a dead instance fails loudly instead of leaking the query.

🔴 WHY THERE IS NO FALLBACK, since "fall back to DuckDuckGo" is the obvious design
and it is wrong here. People self-host SearXNG so their queries do not leave the
network. Quietly switching providers would send the query they deliberately hid to a
third party; provenance labelling only tells them afterwards, and by then it has
gone. Availability loses to the reason the feature exists.
"""
from __future__ import annotations

import httpx
import pytest

from server.registry import net_pin, search_providers

BASE = "http://192.168.1.10:8080"


def _stub(monkeypatch, response, record: dict | None = None):
    async def fake(method, url, **kw):
        if record is not None:
            record.update({"method": method, "url": url, **kw})
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(net_pin, "pinned_request", fake)


def _resp(status=200, *, json=None, text=None, headers=None):
    return httpx.Response(status, json=json, text=text, headers=headers,
                          request=httpx.Request("GET", BASE))


def test_it_needs_no_key():
    assert search_providers.SearXNGProvider(base_url=BASE).requires_key is False


async def test_it_asks_for_json_and_carries_the_exemption(monkeypatch):
    rec: dict = {}
    _stub(monkeypatch, _resp(json={"results": []}), rec)
    await search_providers.SearXNGProvider(base_url=BASE).search("hello")

    assert rec["params"]["format"] == "json"
    assert rec["params"]["q"] == "hello"
    assert rec["allow_host"] == "192.168.1.10", (
        "the exemption must name the configured host and travel per call"
    )


async def test_results_are_normalised_to_the_shared_shape(monkeypatch):
    _stub(monkeypatch, _resp(json={"results": [
        {"title": "T1", "url": "https://a.test", "content": "C1"},
        {"title": "T2", "url": "https://b.test", "content": "C2"},
    ]}))
    out = await search_providers.SearXNGProvider(base_url=BASE).search("hello",
                                                                      num_results=1)
    assert len(out) == 1
    assert out[0] == {"title": "T1", "url": "https://a.test", "snippet": "C1"}


async def test_the_model_cannot_move_the_destination(monkeypatch):
    """A private URL inside the QUERY is just text. The destination comes from
    Settings, and this is the assertion that says so out loud."""
    rec: dict = {}
    _stub(monkeypatch, _resp(json={"results": []}), rec)
    await search_providers.SearXNGProvider(base_url=BASE).search(
        "http://10.0.0.1/admin password")

    assert rec["url"].startswith(BASE)
    assert rec["allow_host"] == "192.168.1.10"


async def test_a_dead_instance_raises_and_never_falls_back(monkeypatch):
    _stub(monkeypatch, httpx.ConnectError("no route to host"))

    called: list[str] = []

    async def ddg(self, query, num_results=5):
        called.append(query)
        return [{"title": "from duckduckgo"}]

    monkeypatch.setattr(search_providers.DuckDuckGoHtmlProvider, "search", ddg)

    with pytest.raises(Exception):
        await search_providers.SearXNGProvider(base_url=BASE).search("hello")
    assert not called, (
        "falling back would send a query the user hid on their own network to a "
        "third party"
    )


async def test_html_instead_of_json_raises_rather_than_returning_nothing(monkeypatch):
    """An instance without `json` in search.formats answers with HTML. Parsing that to
    zero results would read as "nothing matched" — a different, quieter untruth than
    "this instance never answered the question"."""
    _stub(monkeypatch, _resp(text="<html>searxng</html>",
                             headers={"content-type": "text/html"}))
    with pytest.raises(Exception) as exc:
        await search_providers.SearXNGProvider(base_url=BASE).search("hello")
    assert "search.formats" in str(exc.value), (
        "the error has to name the line of settings.yml to change, or it sends people "
        "to re-check an address that was never wrong"
    )


async def test_a_non_200_is_surfaced_not_swallowed(monkeypatch):
    """🔴 The body is VALID JSON with a valid `results` key, on purpose.

    The first version of this test sent 403 with the body "forbidden". It passed —
    but because parsing that as JSON raised, not because the status was checked.
    Deleting raise_for_status() left it green, which a mutation showed. A 403 that
    still parses leaves the status check as the only thing that can fail.
    """
    _stub(monkeypatch, _resp(403, json={"results": [{"title": "leaked"}]}))
    with pytest.raises(Exception):
        await search_providers.SearXNGProvider(base_url=BASE).search("hello")


async def test_a_trailing_slash_in_the_configured_url_does_not_double_up(monkeypatch):
    rec: dict = {}
    _stub(monkeypatch, _resp(json={"results": []}), rec)
    await search_providers.SearXNGProvider(base_url=BASE + "/").search("hello")
    assert "//search" not in rec["url"].replace("http://", "")


def test_it_is_registered_in_the_dropdown():
    assert "searxng" in search_providers.list_providers()


class TestSelectedButNotConfigured:
    """SearXNG chosen, address blank.

    🔴 This must not reuse the "no API key" sentence. SearXNG needs no key, so that
    wording sends the user to buy or find something they never needed — the exact
    shape of wrong advice the ResolvedProvider reason field was introduced to end
    (its docstring records that a month went missing to it).
    """

    async def test_it_has_its_own_reason(self, monkeypatch):
        from server.registry import executors

        async def cfg():
            return executors.SearchConfig(name="searxng", key="", key_state="unset",
                                          base_url="   ")

        monkeypatch.setattr(executors, "_read_search_config", cfg)
        resolved = await executors._search_provider()

        assert resolved.provider is None
        assert resolved.reason == "no-base-url"

    async def test_the_message_says_address_and_says_no_key_is_needed(self):
        from server.registry import executors

        msg = executors._SEARCH_UNAVAILABLE["no-base-url"]
        assert "address" in msg.lower() or "url" in msg.lower()
        assert "no key" in msg.lower(), (
            "it has to say a key is not the missing piece, or the reader assumes it is"
        )
        assert msg != executors._SEARCH_UNAVAILABLE["no-key"]

    async def test_a_configured_address_resolves_to_a_provider(self, monkeypatch):
        from server.registry import executors

        async def cfg():
            return executors.SearchConfig(name="searxng", key="", key_state="unset",
                                          base_url=BASE)

        monkeypatch.setattr(executors, "_read_search_config", cfg)
        resolved = await executors._search_provider()

        assert resolved.reason is None
        assert type(resolved.provider).__name__ == "SearXNGProvider"

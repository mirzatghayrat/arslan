"""Search works with no key at all, and every result says who served it.

TWO HALVES OF ONE DEFECT, per the ruling. (a) a machine with no key should still
search — "download it and it works" is the product promise. (b) a machine WITH a key
whose key has broken must not report itself as having no key. They are not
alternatives; the second is what cost this project's author a month.

🔴 WHY THE OLD GATE MADE (a) STRUCTURALLY IMPOSSIBLE. `_search_provider` asked
`if not key: return None` BEFORE ever looking at which provider was chosen. So a
provider that needs no key could never be reached — not "was not implemented", but
unreachable by construction. The question moves onto the provider itself.

🔴 AND WHY PROVENANCE IS NOT DECORATION. A fallback that scrapes HTML, self-describes
as best-effort and gets rate-limited is fine as a fallback and dishonest as a silent
substitute. If the user cannot tell which provider answered, a degraded result is
indistinguishable from a good one — which is the same class of silence this whole
line of work exists to remove.
"""
from __future__ import annotations

import pytest

from server.registry import executors, search_providers


class _Fake(search_providers.SearchProvider):
    name = "fake"
    requires_key = False

    def __init__(self, api_key: str = "", **kw):
        self.api_key = api_key

    async def search(self, query, num_results=5):
        return [{"title": "t", "url": "https://example.test/", "snippet": "s"}]


class _NeedsKey(_Fake):
    name = "needskey"
    requires_key = True


class TestTheProviderDecidesWhetherAKeyIsNeeded:
    def test_the_contract_exists_on_the_base_class(self):
        # Default True: a new provider that forgets to say so is treated as needing a
        # key, which fails toward "ask the user" rather than toward a broken call.
        assert search_providers.SearchProvider.requires_key is True

    def test_the_builtin_fallback_needs_no_key(self):
        cls = search_providers._PROVIDERS[search_providers._FALLBACK]
        assert cls.requires_key is False

    def test_tavily_still_needs_one(self):
        assert search_providers._PROVIDERS["tavily"].requires_key is True

    def test_the_dropdown_lists_the_keyless_one_first(self):
        # It is the default for a fresh install, so it belongs at the top rather than
        # buried under options that will not work until someone signs up somewhere.
        assert search_providers.list_providers()[0] == search_providers._FALLBACK


class TestAKeylessProviderIsReachable:
    async def test_no_key_still_produces_a_provider(self, monkeypatch):
        # THE structural fix. Under the old gate this could not happen at any setting.
        monkeypatch.setattr(search_providers, "_PROVIDERS",
                            {**search_providers._PROVIDERS, "fake": _Fake})
        monkeypatch.setattr(executors, "_read_search_config",
                            _stub_config(name="fake", key=""))

        resolved = await executors._search_provider()

        assert resolved.provider is not None
        assert resolved.reason is None

    async def test_a_key_needing_provider_without_one_says_so_precisely(self, monkeypatch):
        monkeypatch.setattr(search_providers, "_PROVIDERS",
                            {**search_providers._PROVIDERS, "needskey": _NeedsKey})
        monkeypatch.setattr(executors, "_read_search_config",
                            _stub_config(name="needskey", key=""))

        resolved = await executors._search_provider()

        assert resolved.provider is None
        assert resolved.reason == "no-key"

    async def test_a_stored_key_that_cannot_be_decrypted_is_its_own_reason(self, monkeypatch):
        # spec ⓪ made this state knowable; ① must not flatten it back into "no key".
        # Reporting the wrong cause sends the user to re-enter a key that is already
        # there, which is precisely the month that was lost.
        monkeypatch.setattr(search_providers, "_PROVIDERS",
                            {**search_providers._PROVIDERS, "needskey": _NeedsKey})
        monkeypatch.setattr(executors, "_read_search_config",
                            _stub_config(name="needskey", key="", state="undecryptable"))

        resolved = await executors._search_provider()

        assert resolved.provider is None
        assert resolved.reason == "key-undecryptable"

    async def test_the_two_reasons_produce_different_user_facing_errors(self, monkeypatch):
        seen = {}
        for state, key in (("unset", ""), ("undecryptable", "")):
            monkeypatch.setattr(search_providers, "_PROVIDERS",
                                {**search_providers._PROVIDERS, "needskey": _NeedsKey})
            monkeypatch.setattr(executors, "_read_search_config",
                                _stub_config(name="needskey", key=key, state=state))
            out = await executors.WebSearchExecutor().execute({"query": "x"})
            seen[state] = out["error"]

        assert seen["unset"] != seen["undecryptable"], (
            "a broken key and a missing key read identically — the original defect"
        )
        assert "not configured" in seen["unset"]


class TestEveryResultSaysWhoServedIt:
    async def test_a_successful_search_carries_the_provider(self, monkeypatch):
        monkeypatch.setattr(search_providers, "_PROVIDERS",
                            {**search_providers._PROVIDERS, "fake": _Fake})
        monkeypatch.setattr(executors, "_read_search_config",
                            _stub_config(name="fake", key=""))

        out = await executors.WebSearchExecutor().execute({"query": "x"})

        assert out["ok"] is True
        assert out["provider"] == "fake"

    async def test_the_fallback_marks_itself_best_effort(self, monkeypatch):
        # The honesty requirement, in the payload rather than only in the UI: the model
        # sees this too, and "these results came from a scraper that may be throttled"
        # is information it can act on.
        monkeypatch.setattr(executors, "_read_search_config",
                            _stub_config(name=search_providers._FALLBACK, key=""))

        async def _fake_search(self, query, num_results=5):
            return [{"title": "t", "url": "https://example.test/", "snippet": "s"}]

        monkeypatch.setattr(
            search_providers._PROVIDERS[search_providers._FALLBACK], "search", _fake_search)

        out = await executors.WebSearchExecutor().execute({"query": "x"})

        assert out["provider"] == search_providers._FALLBACK
        assert out["best_effort"] is True

    async def test_a_key_backed_provider_is_not_marked_best_effort(self, monkeypatch):
        monkeypatch.setattr(search_providers, "_PROVIDERS",
                            {**search_providers._PROVIDERS, "fake": _Fake})
        monkeypatch.setattr(executors, "_read_search_config",
                            _stub_config(name="fake", key=""))

        out = await executors.WebSearchExecutor().execute({"query": "x"})

        assert out.get("best_effort", False) is False


def _stub_config(*, name: str, key: str, state: str = "unset"):
    async def _read():
        return executors.SearchConfig(name=name, key=key, key_state=state)
    return _read


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Nothing in this file may reach the internet."""
    async def _boom(*a, **kw):
        raise AssertionError("a test tried to make a real request")

    monkeypatch.setattr(executors.net_pin, "_fetch_text", _boom)

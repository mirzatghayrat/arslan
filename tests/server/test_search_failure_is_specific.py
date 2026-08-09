"""A search failure says WHICH failure, all the way to the screen.

(b) of the ruling, runtime half. ⓪ made "a key is stored but cannot be opened"
knowable; this makes "the key works but the service refused us" knowable too, and the
two must not read alike either.

🔴 THE CLASSIFICATION IS WORTHLESS WITHOUT THE LAST MILE. `_categorize_exc` already
kept the status code — 429 became "http 429" — and it never reached anyone, because
toolHumanize.ts replaced every web_search error with one generic sentence. Semantics
on one end and a shrug on the other is the same as no semantics. So the backend test
and the frontend test are two halves of one requirement, and neither is sufficient.

🔴 AND THE BRANCH ORDER IN _categorize_exc IS LOad-BEARING. HTTPStatusError and
TimeoutException are BOTH subclasses of httpx.HTTPError, so moving the HTTPError arm
up collapses everything into "network error". That was previously true with no test
and no comment saying so.
"""
from __future__ import annotations

import httpx
import pytest

from server.registry import net_pin


def _status(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://example.test/")
    return httpx.HTTPStatusError("boom", request=req,
                                 response=httpx.Response(code, request=req))


class TestTheCategoriesAreSemanticNotJustNumeric:
    @pytest.mark.parametrize("code,expected", [
        (429, "rate-limited"),
        (402, "quota-exhausted"),
        (403, "key-rejected"),
        (401, "key-rejected"),
    ])
    def test_the_codes_a_user_can_act_on_get_names(self, code, expected):
        # These four are the ones with DIFFERENT remedies: wait, top up, replace the
        # key. "http 429" is a fact; "rate-limited" is the fact plus what to do.
        assert net_pin.categorize(_status(code)) == expected

    def test_an_unremarkable_status_keeps_its_number(self):
        # No invented meaning for codes we have no advice about — a made-up category is
        # worse than the raw number, because it reads as understanding.
        assert net_pin.categorize(_status(418)) == "http 418"

    def test_a_timeout_is_a_timeout(self):
        assert net_pin.categorize(httpx.TimeoutException("slow")) == "timeout"

    def test_a_transport_failure_is_a_network_error(self):
        assert net_pin.categorize(httpx.ConnectError("no route")) == "network error"

    def test_anything_else_is_not_dressed_up(self):
        assert net_pin.categorize(ValueError("?")) == "unexpected error"


class TestTheBranchOrderIsProtected:
    def test_a_status_error_does_not_collapse_into_network_error(self):
        # HTTPStatusError IS an HTTPError. If the HTTPError arm ever moves above it,
        # every 429 in the product silently becomes "network error" — and the user is
        # told to check their connection while the real answer is "wait a minute".
        assert net_pin.categorize(_status(429)) != "network error"

    def test_a_timeout_does_not_collapse_into_network_error(self):
        assert net_pin.categorize(httpx.TimeoutException("slow")) != "network error"


class TestRateLimitGetsOneRetry:
    async def test_a_429_is_retried_once_and_then_reported(self, monkeypatch):
        from server.registry import executors, search_providers

        calls = {"n": 0}

        class _Limited(search_providers.SearchProvider):
            name = "limited"
            requires_key = False

            def __init__(self, api_key: str = "", **kw): ...

            async def search(self, query, num_results=5):
                calls["n"] += 1
                raise _status(429)

        monkeypatch.setattr(search_providers, "_PROVIDERS",
                            {**search_providers._PROVIDERS, "limited": _Limited})

        async def _cfg():
            return executors.SearchConfig(name="limited", key="", key_state="unset")

        monkeypatch.setattr(executors, "_read_search_config", _cfg)
        monkeypatch.setattr(executors, "_RETRY_SLEEP", _no_sleep)

        out = await executors.WebSearchExecutor().execute({"query": "x"})

        # Exactly twice: one retry, not a loop. An unbounded backoff on a rate limit
        # is how a throttle becomes a hang.
        assert calls["n"] == 2, calls
        assert out["ok"] is False
        assert "rate-limited" in out["error"]

    async def test_a_bad_key_is_NOT_retried(self, monkeypatch):
        # Retrying a rejected key just gets it rejected again, more slowly. Only the
        # failures that can succeed on a second try are worth one.
        from server.registry import executors, search_providers

        calls = {"n": 0}

        class _Rejected(search_providers.SearchProvider):
            name = "rejected"
            requires_key = False

            def __init__(self, api_key: str = "", **kw): ...

            async def search(self, query, num_results=5):
                calls["n"] += 1
                raise _status(403)

        monkeypatch.setattr(search_providers, "_PROVIDERS",
                            {**search_providers._PROVIDERS, "rejected": _Rejected})

        async def _cfg():
            return executors.SearchConfig(name="rejected", key="k", key_state="set")

        monkeypatch.setattr(executors, "_read_search_config", _cfg)
        monkeypatch.setattr(executors, "_RETRY_SLEEP", _no_sleep)

        out = await executors.WebSearchExecutor().execute({"query": "x"})

        assert calls["n"] == 1, "a rejected key was retried"
        assert "key-rejected" in out["error"]


async def _no_sleep(_seconds: float) -> None:
    """Retry backoff, minus the waiting. Tests assert the count, not the clock."""
    return None

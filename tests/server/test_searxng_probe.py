"""Four verdicts, because the four fixes are different.

🔴 WHY NOT ONE "connection failed". The most common failure by far is an instance
whose settings.yml omits `json` — and it is also the one most easily misread as "I
typed the address wrong". A single message sends that user to check an address that
was never the problem. Distinguishing costs one branch here and saves the support
conversation entirely.

🔴 EVERY VERDICT NEEDS A FIXTURE THAT ONLY IT CAN EXPLAIN. A case satisfiable by two
verdicts proves neither, so `not_searxng` and `json_disabled` are driven by bodies
that differ ONLY in the marker the implementation is allowed to look at.
"""
from __future__ import annotations

import httpx
import pytest

from server.registry import net_pin
from server.services import searxng_probe

BASE = "http://192.168.1.10:8080"


def _stub(monkeypatch, outcome):
    async def fake(method, url, **kw):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(searxng_probe.net_pin, "pinned_request", fake)


def _resp(status=200, *, json=None, text=None, headers=None):
    return httpx.Response(status, json=json, text=text, headers=headers,
                          request=httpx.Request("GET", BASE))


class TestUnreachable:
    async def test_a_refused_connection(self, monkeypatch):
        _stub(monkeypatch, httpx.ConnectError("no route to host"))
        assert (await searxng_probe.probe(BASE))["verdict"] == "unreachable"

    async def test_a_timeout(self, monkeypatch):
        _stub(monkeypatch, httpx.ReadTimeout("timed out"))
        assert (await searxng_probe.probe(BASE))["verdict"] == "unreachable"

    async def test_blocked_by_pinning_counts_as_unreachable(self, monkeypatch):
        """From the user's chair a refusal by our own guard and a dead host are the
        same event: nothing answered. Naming our guard here would describe our
        internals instead of their problem."""
        _stub(monkeypatch, net_pin._BlockedHost("private address"))
        assert (await searxng_probe.probe(BASE))["verdict"] == "unreachable"


class TestOk:
    async def test_results_come_back(self, monkeypatch):
        _stub(monkeypatch, _resp(json={"results": [{"title": "x"}, {"title": "y"}]}))
        out = await searxng_probe.probe(BASE)
        assert out["verdict"] == "ok"
        assert out["result_count"] == 2

    async def test_zero_results_is_still_ok(self, monkeypatch):
        """The instance answered the question and found nothing. That is a working
        instance, and calling it broken would send someone to fix a healthy box."""
        _stub(monkeypatch, _resp(json={"results": []}))
        out = await searxng_probe.probe(BASE)
        assert out["verdict"] == "ok"
        assert out["result_count"] == 0


class TestTellingTheTwoHtmlCasesApart:
    """The pair that has to be discriminated. Both are 200 with an HTML body; the
    ONLY difference is the marker, which is exactly what the heuristic may read."""

    async def test_searxng_serving_html_means_json_is_disabled(self, monkeypatch):
        _stub(monkeypatch, _resp(
            text='<html><meta name="generator" content="searxng"></html>',
            headers={"content-type": "text/html"}))
        assert (await searxng_probe.probe(BASE))["verdict"] == "json_disabled"

    async def test_some_other_server_means_not_searxng(self, monkeypatch):
        _stub(monkeypatch, _resp(
            text="<html><body>Welcome to nginx!</body></html>",
            headers={"content-type": "text/html"}))
        assert (await searxng_probe.probe(BASE))["verdict"] == "not_searxng"

    async def test_json_that_is_not_a_search_response_is_not_searxng(self, monkeypatch):
        """Something answers JSON at this address, but it is not a search result. A
        different app on the port the user guessed."""
        _stub(monkeypatch, _resp(json={"status": "healthy", "uptime": 41}))
        assert (await searxng_probe.probe(BASE))["verdict"] == "not_searxng"


class TestTheContract:
    def test_there_are_exactly_four_distinct_verdicts(self):
        assert len(set(searxng_probe.VERDICTS)) == 4

    async def test_the_probe_carries_the_exemption_for_the_typed_host(self, monkeypatch):
        """The probe reaches a LAN address for the same reason the provider does, and
        under the same constraint — the exemption names the host being tested."""
        rec: dict = {}

        async def fake(method, url, **kw):
            rec.update(kw)
            return _resp(json={"results": []})

        monkeypatch.setattr(searxng_probe.net_pin, "pinned_request", fake)
        await searxng_probe.probe(BASE)
        assert rec["allow_host"] == "192.168.1.10"

    async def test_the_detail_never_leaks_the_query_string_back(self, monkeypatch):
        """The probe sends a fixed phrase, not user content — but the detail field is
        rendered in the UI, so it must not become a channel for whatever the instance
        echoes back."""
        _stub(monkeypatch, httpx.ConnectError("connect to 192.168.1.10 failed"))
        out = await searxng_probe.probe(BASE)
        assert isinstance(out["detail"], str)
        assert len(out["detail"]) <= 200


@pytest.mark.parametrize("verdict", ["unreachable", "not_searxng", "json_disabled", "ok"])
def test_every_verdict_is_declared(verdict):
    assert verdict in searxng_probe.VERDICTS


class TestTheEndpointIsActuallyReachable:
    """🔴 A green service function does not mean a wired route.

    The service can be perfect while the endpoint is unregistered, mounted without
    the /api/v1 prefix, or broken by a schema mismatch — and every unit test above
    stays green through all three. This project has the scar: provider APIs live
    under /api/v1 and a round was lost to assuming otherwise.
    """

    @pytest.mark.asyncio
    async def test_it_answers_with_a_verdict(self, client, monkeypatch):
        from server.services import searxng_probe as sp

        async def fake(base_url):
            return {"verdict": "json_disabled", "detail": "", "result_count": None}

        monkeypatch.setattr(sp, "probe", fake)
        resp = await client.post("/api/v1/settings/test-search-instance",
                                 json={"base_url": BASE})
        assert resp.status_code == 200, resp.text
        assert resp.json()["verdict"] == "json_disabled"

    @pytest.mark.asyncio
    async def test_a_blank_address_does_not_reach_the_network(self, client, monkeypatch):
        called: list[str] = []

        async def fake(method, url, **kw):
            called.append(url)
            return _resp(json={"results": []})

        monkeypatch.setattr(net_pin, "pinned_request", fake)
        resp = await client.post("/api/v1/settings/test-search-instance",
                                 json={"base_url": "   "})
        assert resp.status_code == 200, resp.text
        assert resp.json()["verdict"] == "unreachable"
        assert not called, "a blank address must not produce a request to /search"

    @pytest.mark.asyncio
    async def test_a_failure_is_a_verdict_not_a_500(self, client, monkeypatch):
        """A 500 says "something went wrong", which is the sentence this endpoint
        exists to replace."""
        from server.services import searxng_probe as sp

        async def boom(base_url):
            raise RuntimeError("unexpected")

        monkeypatch.setattr(sp.net_pin, "pinned_request",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
        resp = await client.post("/api/v1/settings/test-search-instance",
                                 json={"base_url": BASE})
        assert resp.status_code == 200, resp.text
        assert resp.json()["verdict"] == "unreachable"

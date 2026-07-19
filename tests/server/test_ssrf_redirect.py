"""web_extract must re-check the SSRF guard on every redirect hop (release-gate).

FU-1 MOVED THE SEAM. These tests used to monkeypatch `_is_private_host` and drive
unresolvable example hostnames, because the old `_fetch_text` never resolved anything —
it asked that predicate and then handed the HOSTNAME to httpx. That split is precisely
the DNS-rebinding hole FU-1 closes, so the gate is now `_resolve_pinned`, which really
resolves, validates every answer, and connects to the pinned address.

They are rewritten against the new seam rather than deleted: what they assert — a private
redirect target is refused, a legitimate public one is followed — is behaviour that must
survive the fix, and it does. Note the second test can no longer look for the hostname in
the request URL: the URL now carries the pinned IP, and the hostname rides in the Host
header. That is the change being verified, not an accident.
"""
import socket

import httpx
import pytest

from server.registry import executors

PUBLIC_A = "93.184.216.34"
PUBLIC_B = "93.184.216.35"
METADATA = "169.254.169.254"


def _addrinfo(ip: str):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]


def _client_with(handler):
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False, trust_env=False
    )


def _resolver(mapping: dict[str, str]):
    def fake(host, *a, **k):
        return _addrinfo(mapping[host])
    return fake


async def test_fetch_text_blocks_redirect_to_private_host(monkeypatch):
    # public start host is fine; the redirect target is the cloud metadata address.
    monkeypatch.setattr(socket, "getaddrinfo",
                        _resolver({"public.example": PUBLIC_A, METADATA: METADATA}))

    def handler(request):
        if METADATA in str(request.url):
            return httpx.Response(200, text="SECRET CLOUD METADATA")
        return httpx.Response(302, headers={"location": f"http://{METADATA}/latest/meta-data"})

    monkeypatch.setattr(executors, "_build_client", lambda: _client_with(handler))

    with pytest.raises(executors._BlockedHost):
        await executors._fetch_text("http://public.example/page")


async def test_fetch_text_follows_legit_public_redirect(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        _resolver({"a.example": PUBLIC_A, "b.example": PUBLIC_B}))
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        if request.headers["Host"].startswith("a.example"):
            return httpx.Response(302, headers={"location": "http://b.example/final"})
        return httpx.Response(
            200,
            text="<html><body><article>"
            "这是一段足够长的正文用于 trafilatura 正确抽取内容。"
            "</article></body></html>",
        )

    monkeypatch.setattr(executors, "_build_client", lambda: _client_with(handler))

    await executors._fetch_text("http://a.example/start")
    # the hostname now lives in the Host header; the URL carries the pinned address
    assert any(r.headers["Host"].startswith("b.example") for r in seen), (
        "legit public redirect must still be followed")
    assert any(r.url.host == PUBLIC_B for r in seen), (
        "and the second hop must be pinned too, not resolved again at connect time")

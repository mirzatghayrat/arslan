"""One table of adversarial URLs, run through BOTH callers, asserting one verdict.

🔴 THIS FILE WAS PROMISED AND NOT WRITTEN. net_pin's module docstring has claimed
since the extraction that "tests/server/test_pinning_is_the_same_on_both_paths.py
runs one table of adversarial URLs through BOTH callers and fails if their verdicts
ever differ." It did not exist. A guard that only a comment believes in is worse
than a missing guard, because the comment stops anyone from noticing it is missing.

WHY PARITY IS THE THING TO TEST. Two paths reach the network — web_extract and
search. They now share `pinned_request`, but sharing is a property of today's code,
not a property anyone is holding them to. The failure this prevents is the cheap
one: someone loosens the search side alone (a redirect allowance, an exemption
widened "just for the instance"), every search test stays green, and the two paths
quietly stop agreeing about what is safe to reach.
"""
from __future__ import annotations

import socket

import httpx
import pytest

from server.registry import net_pin, search_providers

#: Each entry is (label, hostname, resolved_ip, must_be_refused).
#: Reasons live with the case, because "why is this one here" is the part that rots.
ADVERSARIAL = [
    ("loopback", "evil.test", "127.0.0.1", True),
    ("rfc1918 private", "evil.test", "192.168.1.10", True),
    # 100.64.0.0/10 belongs to none of is_private/is_loopback/is_link_local/is_reserved
    # in Python's ipaddress — it is the case the allow-list predicate exists for, and
    # the one an enumeration missed. It is also a whole Tailscale tailnet.
    ("cgnat / tailnet", "evil.test", "100.64.1.1", True),
    ("link-local", "evil.test", "169.254.169.254", True),
    ("ipv6 loopback", "evil.test", "::1", True),
    ("ipv6 unique-local", "evil.test", "fd00::1", True),
    ("multicast", "evil.test", "224.0.0.1", True),
    ("ordinary public", "example.test", "93.184.216.34", False),
]


def _addrinfo(ip: str):
    fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(fam, socket.SOCK_STREAM, 6, "", (ip, 0))]


@pytest.fixture(autouse=True)
def no_env_proxy(monkeypatch):
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(net_pin, "getproxies", lambda: {})


def _transport(monkeypatch):
    """Nothing leaves the machine; a reached request is recorded as 'allowed'."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="<html><body>ok</body></html>",
                              headers={"content-type": "text/html"})

    monkeypatch.setattr(
        net_pin, "_build_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                  follow_redirects=False, trust_env=False))
    return seen


async def _extract_refused(monkeypatch, host: str, ip: str) -> bool:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo(ip))
    seen = _transport(monkeypatch)
    try:
        await net_pin.pinned_get(f"https://{host}/page")
    except net_pin._BlockedHost:
        return True
    return not seen


async def _search_refused(monkeypatch, host: str, ip: str) -> bool:
    """Drive the SEARCH path at the same address by pointing a provider's constant
    destination at it — the provider's own URL is not the subject here, the pinning
    decision is."""
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo(ip))
    seen = _transport(monkeypatch)
    provider = search_providers.DuckDuckGoHtmlProvider()
    monkeypatch.setattr(provider, "_URL", f"https://{host}/html/", raising=False)
    try:
        await provider.search("anything")
    except net_pin._BlockedHost:
        return True
    return not seen


@pytest.mark.parametrize("label,host,ip,must_refuse", ADVERSARIAL,
                         ids=[c[0] for c in ADVERSARIAL])
async def test_both_paths_agree(monkeypatch, label, host, ip, must_refuse):
    extract = await _extract_refused(monkeypatch, host, ip)
    search = await _search_refused(monkeypatch, host, ip)

    assert extract == search, (
        f"{label}: web_extract {'refused' if extract else 'allowed'} but search "
        f"{'refused' if search else 'allowed'} — the two paths disagree about what "
        "is safe to reach, which is the drift this file exists to catch"
    )
    assert extract is must_refuse, (
        f"{label}: expected {'refusal' if must_refuse else 'success'}, got the opposite"
    )


async def test_the_table_contains_both_verdicts(monkeypatch):
    """🔴 A parity file where every case refuses would pass against a path that
    refuses everything — including a typo that breaks search entirely. The table has
    to contain at least one address that must be REACHED."""
    assert any(not case[3] for case in ADVERSARIAL)
    assert any(case[3] for case in ADVERSARIAL)

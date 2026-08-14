"""The loopback half of RFC 8252: catch one authorization code, then vanish.

USER RULING (spec ③ §2.2): dynamic port, per the RFC — 127.0.0.1 with ANY port
is what loopback redirects are defined to allow. A provider that demands a fixed
port gets recorded as a per-provider exception; the design does not bend to it.

WHAT THE TESTS PIN, beyond the happy path: the listener must be gone the moment
the code arrives. A callback server that lingers is an open local HTTP endpoint
nobody remembers — the opposite of "bind, catch, close".
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from server.mcp.oauth_loopback import catch_authorization_code


async def test_catches_code_and_state_then_closes():
    catcher = await catch_authorization_code(timeout=5.0)
    assert catcher.port > 0
    assert catcher.redirect_uri == f"http://127.0.0.1:{catcher.port}/callback"

    async with httpx.AsyncClient() as c:
        r = await c.get(f"{catcher.redirect_uri}?code=abc123&state=xyz")
    assert r.status_code == 200
    # The page a HUMAN sees in the browser tab — it must say the tab is done,
    # not dump JSON at them.
    assert "close" in r.text.lower()

    code, state = await catcher.result
    assert (code, state) == ("abc123", "xyz")

    # Gone means gone: the port must refuse connections once the code arrived.
    await asyncio.sleep(0.05)
    with pytest.raises(OSError):
        reader, writer = await asyncio.open_connection("127.0.0.1", catcher.port)
        writer.close()


async def test_two_catchers_get_two_different_ports():
    """The kernel picks the port (bind :0), so two flows cannot collide — and
    neither can a fixed-port assumption creep in unnoticed."""
    a = await catch_authorization_code(timeout=5.0)
    b = await catch_authorization_code(timeout=5.0)
    try:
        assert a.port != b.port
    finally:
        a.cancel()
        b.cancel()


async def test_a_denial_resolves_with_the_error_not_a_hang():
    """Providers redirect back with ?error=access_denied when the user clicks
    Cancel. That is an answer, not a timeout — the flow must learn it now."""
    catcher = await catch_authorization_code(timeout=5.0)
    async with httpx.AsyncClient() as c:
        await c.get(f"{catcher.redirect_uri}?error=access_denied&state=xyz")
    with pytest.raises(RuntimeError, match="access_denied"):
        await catcher.result


async def test_timeout_frees_the_port():
    catcher = await catch_authorization_code(timeout=0.2)
    with pytest.raises(asyncio.TimeoutError):
        await catcher.result
    await asyncio.sleep(0.05)
    with pytest.raises(OSError):
        reader, writer = await asyncio.open_connection("127.0.0.1", catcher.port)
        writer.close()


async def test_the_probe_can_fail_wrong_path_is_404():
    """⓪ first: a request to the wrong path must NOT resolve the flow — proving
    the parser discriminates, so the happy-path pass means something."""
    catcher = await catch_authorization_code(timeout=5.0)
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"http://127.0.0.1:{catcher.port}/favicon.ico")
        assert r.status_code == 404
        assert not catcher.result.done()
    finally:
        catcher.cancel()

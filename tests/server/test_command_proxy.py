"""MITM credential proxy: host allowlist gate + real TLS interception with credential injection.
The injection test runs a local TLS 'upstream' (a fake github, cert signed by the same LocalCA) and
drives an HTTPS request THROUGH the proxy, asserting the injected Authorization reached upstream."""
import asyncio
import base64
import ssl
import tempfile
from pathlib import Path

import pytest

from server.services import command_proxy
from server.services.command_ca import LocalCA


def test_hostport_from_connect():
    assert command_proxy._hostport_from_connect(b"CONNECT github.com:443 HTTP/1.1\r\n\r\n") == ("github.com", 443)
    assert command_proxy._hostport_from_connect(b"CONNECT localhost:8443 HTTP/1.1\r\n\r\n") == ("localhost", 8443)
    assert command_proxy._hostport_from_connect(b"GET / HTTP/1.1\r\n\r\n") == (None, 0)


def test_inject_auth():
    # git-over-HTTPS (github.com) → basic auth with x-access-token
    out = command_proxy._inject_auth(b"GET /x HTTP/1.1\r\nHost: github.com\r\n\r\n", "TOK", "github.com")
    assert b"Authorization: Basic " + base64.b64encode(b"x-access-token:TOK") in out
    assert b"Connection: close" in out
    assert out.startswith(b"GET /x HTTP/1.1\r\n")
    # REST API (api.github.com) → bearer
    api = command_proxy._inject_auth(b"GET /user HTTP/1.1\r\n\r\n", "TOK", "api.github.com")
    assert b"Authorization: Bearer TOK" in api
    # existing Authorization from the client is dropped
    out2 = command_proxy._inject_auth(b"GET / HTTP/1.1\r\nAuthorization: Basic evil\r\n\r\n", "TOK", "github.com")
    assert b"evil" not in out2


def _server_ctx(ca: LocalCA, host: str) -> ssl.SSLContext:
    cert_pem, key_pem = ca.leaf_for(host)
    d = Path(tempfile.mkdtemp())
    (d / "c").write_bytes(cert_pem)
    (d / "k").write_bytes(key_pem)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(d / "c"), str(d / "k"))
    return ctx


@pytest.mark.asyncio
async def test_proxy_rejects_non_allowlisted():
    ca = LocalCA(Path(tempfile.mkdtemp()) / "ca")
    proxy = await command_proxy.start_proxy(allow_hosts={"localhost"}, inject_token=None, ca=ca)
    try:
        r, w = await asyncio.open_connection("127.0.0.1", proxy.port)
        w.write(b"CONNECT evil.com:443 HTTP/1.1\r\n\r\n")
        await w.drain()
        line = await asyncio.wait_for(r.readline(), timeout=5)
        assert b"403" in line
        w.close()
    finally:
        await proxy.close()


@pytest.mark.asyncio
async def test_proxy_mitm_injects_credentials():
    ca = LocalCA(Path(tempfile.mkdtemp()) / "ca")

    # Fake 'github' upstream: TLS server that echoes the request head it received.
    async def up_handle(ur, uw):
        head = await asyncio.wait_for(ur.readuntil(b"\r\n\r\n"), timeout=5)
        body = b"SEEN\r\n" + head
        uw.write(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body)
        await uw.drain()
        uw.close()

    upstream = await asyncio.start_server(up_handle, "127.0.0.1", 0, ssl=_server_ctx(ca, "localhost"))
    up_port = upstream.sockets[0].getsockname()[1]

    up_trust = ssl.create_default_context(cadata=ca.ca_cert_pem.decode())
    proxy = await command_proxy.start_proxy(
        allow_hosts={"localhost"}, inject_token="TESTTOK", ca=ca, upstream_ctx=up_trust)
    try:
        # Client: CONNECT localhost:up_port through the proxy, then TLS (trusting our CA), GET /.
        r, w = await asyncio.open_connection("127.0.0.1", proxy.port)
        w.write(b"CONNECT localhost:%d HTTP/1.1\r\n\r\n" % up_port)
        await w.drain()
        status = await asyncio.wait_for(r.readline(), timeout=5)
        assert b"200" in status
        await asyncio.wait_for(r.readline(), timeout=5)  # consume the blank line ending the 200 head
        cctx = ssl.create_default_context(cadata=ca.ca_cert_pem.decode())
        await w.start_tls(cctx, server_hostname="localhost")
        w.write(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
        await w.drain()
        resp = await asyncio.wait_for(r.read(4096), timeout=5)
        # the echoed upstream-seen head must carry the injected credential + forced close
        expect = b"Authorization: Basic " + base64.b64encode(b"x-access-token:TESTTOK")
        assert expect in resp, resp
        assert b"Connection: close" in resp
        w.close()
    finally:
        await proxy.close()
        upstream.close()
        await upstream.wait_closed()

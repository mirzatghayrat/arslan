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
    for target in (b"github.com", b"github.com:bad", b"github.com:65536", b"github.com.:443", b"github.com\xff:443", b"github.com:443 extra"):
        assert command_proxy._hostport_from_connect(b"CONNECT " + target + b" HTTP/1.1\r\n\r\n") == (None, 0)


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
    for host in ("other.example", "github.com.evil.example", "localhost", "api.github.com.evil"):
        remote = command_proxy._inject_auth(b"GET / HTTP/1.1\r\nAuthorization: Basic client-secret\r\n\r\n", "TOK", host)
        assert b"Authorization:" not in remote and b"TOK" not in remote and b"client-secret" not in remote


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
@pytest.mark.parametrize("host,authenticated", [("github.com", True), ("other.example", False)])
async def test_proxy_mitm_authentication_is_bound_to_github(monkeypatch, host, authenticated):
    ca = LocalCA(Path(tempfile.mkdtemp()) / "ca")

    # Fake 'github' upstream: TLS server that echoes the request head it received.
    async def up_handle(ur, uw):
        head = await asyncio.wait_for(ur.readuntil(b"\r\n\r\n"), timeout=5)
        body = b"SEEN\r\n" + head
        uw.write(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(body) + body)
        await uw.drain()
        uw.close()

    upstream = await asyncio.start_server(up_handle, "127.0.0.1", 0, ssl=_server_ctx(ca, host))
    up_port = upstream.sockets[0].getsockname()[1]
    original_connect = asyncio.open_connection
    async def connect(name, port, *args, **kwargs):
        if name == host and port == 443:
            return await original_connect("127.0.0.1", up_port, *args, **kwargs)
        return await original_connect(name, port, *args, **kwargs)
    monkeypatch.setattr(asyncio, "open_connection", connect)

    up_trust = ssl.create_default_context(cadata=ca.ca_cert_pem.decode())
    proxy = await command_proxy.start_proxy(
        allow_hosts={host}, inject_token="TESTTOK", ca=ca, upstream_ctx=up_trust)
    try:
        # Client: CONNECT localhost:up_port through the proxy, then TLS (trusting our CA), GET /.
        r, w = await asyncio.open_connection("127.0.0.1", proxy.port)
        w.write(f"CONNECT {host}:443 HTTP/1.1\r\n\r\n".encode())
        await w.drain()
        status = await asyncio.wait_for(r.readline(), timeout=5)
        assert b"200" in status
        await asyncio.wait_for(r.readline(), timeout=5)  # consume the blank line ending the 200 head
        cctx = ssl.create_default_context(cadata=ca.ca_cert_pem.decode())
        await w.start_tls(cctx, server_hostname=host)
        w.write(b"GET / HTTP/1.1\r\nHost: attacker.example\r\n\r\n")
        await w.drain()
        resp = await asyncio.wait_for(r.read(4096), timeout=5)
        # A non-GitHub upstream must not receive a GitHub credential, even when
        # explicitly allowed as this repository's remote.
        expect = b"Authorization: Basic " + base64.b64encode(b"x-access-token:TESTTOK")
        if authenticated:
            assert expect in resp, resp
        else:
            assert expect not in resp and b"TESTTOK" not in resp and b"Authorization:" not in resp, resp
        assert f"Host: {host}".encode() in resp and b"attacker.example" not in resp
        assert b"Connection: close" in resp
        w.close()
    finally:
        await proxy.close()
        upstream.close()
        await upstream.wait_closed()


@pytest.mark.parametrize("raw_head", [
    b"GET https://other.example/ HTTP/1.1\r\n\r\n",
    b"GET / HTTP/1.1\r\n Authorization: folded\r\n\r\n",
    b"GET / HTTP/1.1\r\nBad Header: value\r\n\r\n",
    b"GET / HTTP/1.1\r\nX-Header: value\ninjected\r\n\r\n",
    b"POST / HTTP/1.1\r\nContent-Length: 1\r\nTransfer-Encoding: chunked\r\n\r\n",
    b"POST / HTTP/1.1\r\nContent-Length: 1\r\nContent-Length: 2\r\n\r\n",
])
def test_proxy_rejects_ambiguous_request_framing(raw_head):
    with pytest.raises(ValueError):
        command_proxy._inject_auth(raw_head, "synthetic-canary", "github.com")


async def test_proxy_rejects_non_https_port_and_closes_active_clients():
    ca = LocalCA(Path(tempfile.mkdtemp()) / "ca")
    proxy = await command_proxy.start_proxy(allow_hosts=set(), inject_token=None, ca=ca)
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
    writer.write(b"CONNECT github.com:8443 HTTP/1.1\r\n\r\n")
    await writer.drain()
    assert b"403" in await asyncio.wait_for(reader.readline(), 2)
    writer.close()
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy.port)
    writer.write(b"CONNECT github.com:443 HTTP/1.1\r\n\r\n")
    await writer.drain()
    assert b"200" in await asyncio.wait_for(reader.readline(), 2)
    await asyncio.wait_for(proxy.close(), 3)
    writer.close()
    assert not proxy._tasks

"""Single-command MITM proxy: host allowlist + credential injection for the shell's network
commands (git/gh over HTTPS). The real token lives ONLY here, host-side; the sandbox reaches
only localhost:<port> and never sees a credential.

Flow per connection: read CONNECT host:port -> host allowlist gate -> 200 -> MITM the client TLS
with a LocalCA-signed leaf for `host` -> open real TLS upstream -> read the client's request head,
inject `Authorization` + force `Connection: close` -> forward -> pump both directions.
"""
from __future__ import annotations

import asyncio
import base64
import ssl
import tempfile
from dataclasses import dataclass
from pathlib import Path

from server.services import command_policy
from server.services.command_ca import LocalCA


def _hostport_from_connect(head: bytes) -> tuple[str | None, int]:
    """Parse `CONNECT host:port HTTP/1.1` → (host, port). Non-CONNECT → (None, 0)."""
    line = head.split(b"\r\n", 1)[0]
    if not line.startswith(b"CONNECT "):
        return None, 0
    parts = line.split(b" ")
    if len(parts) < 2:
        return None, 0
    host, _, port = parts[1].decode("ascii", "ignore").partition(":")
    return (host.lower() or None), (int(port) if port.isdigit() else 443)


def _host_from_connect(head: bytes) -> str | None:
    return _hostport_from_connect(head)[0]


def _inject_auth(req_head: bytes, token: str | None, host: str) -> bytes:
    """Insert GitHub credentials + force `Connection: close` (one request per connection so
    injection always applies). Format depends on the target: the REST API (api.github.com) wants
    `Bearer <token>`; git-over-HTTPS (github.com) wants basic auth (user 'x-access-token'). Drops
    any Authorization/Connection the client sent — the sandbox has no creds, but be defensive."""
    lines = req_head.split(b"\r\n")
    kept = [ln for ln in lines if ln and not ln.lower().startswith(b"authorization:")
            and not ln.lower().startswith(b"connection:")]
    if not kept:
        return req_head
    inject: list[bytes] = []
    if token:
        if host == "api.github.com":
            inject.append(f"Authorization: Bearer {token}".encode())
        else:
            blob = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            inject.append(f"Authorization: Basic {blob}".encode())
    inject.append(b"Connection: close")
    return b"\r\n".join([kept[0], *inject, *kept[1:]]) + b"\r\n\r\n"


@dataclass
class Proxy:
    port: int
    _server: asyncio.AbstractServer

    async def close(self) -> None:
        self._server.close()
        try:
            await self._server.wait_closed()
        except Exception:  # noqa: BLE001
            pass


async def start_proxy(*, allow_hosts: set, inject_token: str | None, ca: LocalCA,
                      upstream_ctx: ssl.SSLContext | None = None) -> Proxy:
    """Start a single-command MITM proxy on localhost. Only CONNECTs to allow_hosts (∪ GitHub)
    pass; TLS is MITM'd with `ca`; `inject_token` is injected as GitHub basic auth. `upstream_ctx`
    defaults to system trust (real github); tests pass a context trusting a local CA."""
    up_ctx = upstream_ctx or ssl.create_default_context()

    def _leaf_ctx(host: str) -> ssl.SSLContext:
        cert_pem, key_pem = ca.leaf_for(host)
        d = Path(tempfile.mkdtemp(prefix="arslan-leaf-"))
        cp, kp = d / "c.pem", d / "k.pem"
        cp.write_bytes(cert_pem)
        kp.write_bytes(key_pem)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cp), str(kp))
        return ctx

    async def _upgrade_server_tls(cr: asyncio.StreamReader, cw: asyncio.StreamWriter,
                                  ctx: ssl.SSLContext) -> None:
        # StreamWriter.start_tls is client-only (no server_side); use loop.start_tls with the
        # transport+protocol, then rebind the stream to the new TLS transport. Verified pattern.
        loop = asyncio.get_running_loop()
        transport = cw.transport
        protocol = transport.get_protocol()
        new_t = await loop.start_tls(transport, protocol, ctx, server_side=True)
        cw._transport = new_t
        protocol._transport = new_t

    async def _pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
        try:
            while True:
                chunk = await src.read(65536)
                if not chunk:
                    break
                dst.write(chunk)
                await dst.drain()
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                dst.close()
            except Exception:  # noqa: BLE001
                pass

    async def handle(cr: asyncio.StreamReader, cw: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(cr.readuntil(b"\r\n\r\n"), timeout=15)
        except Exception:  # noqa: BLE001
            cw.close()
            return
        host, port = _hostport_from_connect(head)
        if not host or not command_policy.is_host_allowed(host, repo_remote_hosts=allow_hosts):
            cw.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            await cw.drain()
            cw.close()
            return
        cw.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await cw.drain()
        try:
            await _upgrade_server_tls(cr, cw, _leaf_ctx(host))
        except Exception:  # noqa: BLE001
            cw.close()
            return
        try:
            ur, uw = await asyncio.open_connection(host, port, ssl=up_ctx, server_hostname=host)
        except Exception:  # noqa: BLE001
            cw.close()
            return
        try:
            req = await asyncio.wait_for(cr.readuntil(b"\r\n\r\n"), timeout=15)
        except Exception:  # noqa: BLE001
            cw.close()
            uw.close()
            return
        uw.write(_inject_auth(req, inject_token, host))
        await uw.drain()
        await asyncio.gather(_pump(cr, uw), _pump(ur, cw))

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return Proxy(port=server.sockets[0].getsockname()[1], _server=server)

"""Single-command MITM proxy: host allowlist + credential injection for the shell's network
commands (git/gh over HTTPS). This in-process transport is NOT an isolated credential
broker. Production callers must not supply credentials until an OS boundary is verified.

Flow per connection: read CONNECT host:port -> host allowlist gate -> 200 -> MITM the client TLS
with a LocalCA-signed leaf for `host` -> open real TLS upstream -> read the client's request head,
inject `Authorization` + force `Connection: close` -> forward -> pump both directions.
"""
from __future__ import annotations

import asyncio
import base64
import re
import ssl
import tempfile
from dataclasses import dataclass
from pathlib import Path

from server.services import command_policy
from server.services.command_ca import LocalCA


def _hostport_from_connect(head: bytes) -> tuple[str | None, int]:
    """Parse `CONNECT host:port HTTP/1.1` → (host, port). Non-CONNECT → (None, 0)."""
    line = head.split(b"\r\n", 1)[0]
    match = re.fullmatch(rb"CONNECT ([A-Za-z0-9.-]+):([0-9]{1,5}) HTTP/1\.[01]", line)
    if match is None:
        return None, 0
    host = match[1].decode("ascii").lower()
    port = int(match[2])
    if not 1 <= port <= 65535 or host.startswith(".") or host.endswith(".") or ".." in host:
        return None, 0
    return host, port


def _host_from_connect(head: bytes) -> str | None:
    return _hostport_from_connect(head)[0]


def _inject_auth(req_head: bytes, token: str | None, host: str) -> bytes:
    """Insert GitHub credentials + force `Connection: close` (one request per connection so
    injection always applies). Format depends on the target: the REST API (api.github.com) wants
    `Bearer <token>`; git-over-HTTPS (github.com) wants basic auth (user 'x-access-token'). Drops
    any Authorization/Connection the client sent — the sandbox has no creds, but be defensive."""
    lines = req_head.split(b"\r\n")
    if not lines or not re.fullmatch(rb"[A-Z]+ /[^ \r\n]* HTTP/1\.[01]", lines[0]):
        raise ValueError("Only origin-form HTTP requests are accepted")
    kept = []
    framing = set()
    for line in lines[1:]:
        if not line:
            continue
        key, colon, value = line.partition(b":")
        if not colon or not re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key):
            raise ValueError("Invalid or folded proxy header")
        if any(byte < 32 and byte != 9 or byte == 127 for byte in value):
            raise ValueError("Control character in proxy header")
        if key.lower() in {b"content-length", b"transfer-encoding"}:
            if framing:
                raise ValueError("Ambiguous request body framing")
            framing.add(key.lower())
            if key.lower() == b"content-length" and not value.strip().isdigit():
                raise ValueError("Invalid content length")
            if key.lower() == b"transfer-encoding" and value.strip().lower() != b"chunked":
                raise ValueError("Unsupported transfer encoding")
        if key.lower() not in {b"authorization", b"proxy-authorization", b"connection", b"host"}:
            kept.append(line)
    if token and any(ord(char) < 33 or ord(char) > 126 for char in token):
        raise ValueError("Invalid credential encoding")
    inject: list[bytes] = []
    # A repository remote being allowed is not authority to receive a GitHub
    # credential. Redirects and non-GitHub remotes must remain unauthenticated.
    if token and host in {"github.com", "api.github.com"}:
        if host == "api.github.com":
            inject.append(f"Authorization: Bearer {token}".encode())
        else:
            blob = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            inject.append(f"Authorization: Basic {blob}".encode())
    inject.append(b"Connection: close")
    return b"\r\n".join([lines[0], f"Host: {host}".encode("ascii"), *inject, *kept]) + b"\r\n\r\n"


@dataclass
class Proxy:
    port: int
    _server: asyncio.AbstractServer
    _tasks: set[asyncio.Task]

    async def close(self) -> None:
        self._server.close()
        try:
            await self._server.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        pending = list(self._tasks)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


async def start_proxy(*, allow_hosts: set, inject_token: str | None, ca: LocalCA,
                      upstream_ctx: ssl.SSLContext | None = None) -> Proxy:
    """Start a single-command MITM proxy on localhost. Only CONNECTs to allow_hosts (∪ GitHub)
    pass; TLS is MITM'd with `ca`; `inject_token` is injected as GitHub basic auth. `upstream_ctx`
    defaults to system trust (real github); tests pass a context trusting a local CA."""
    up_ctx = upstream_ctx or ssl.create_default_context()
    tasks: set[asyncio.Task] = set()

    def _leaf_ctx(host: str) -> ssl.SSLContext:
        cert_pem, key_pem = ca.leaf_for(host)
        with tempfile.TemporaryDirectory(prefix="arslan-leaf-") as directory:
            d = Path(directory)
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
        task = asyncio.current_task()
        tasks.add(task)
        uw = None
        established = False
        try:
            async with asyncio.timeout(60):
                head = await asyncio.wait_for(cr.readuntil(b"\r\n\r\n"), timeout=15)
                host, port = _hostport_from_connect(head)
                if not host or port != 443 or not command_policy.is_host_allowed(host, repo_remote_hosts=allow_hosts):
                    raise ValueError("Proxy destination denied")
                cw.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await cw.drain()
                established = True
                await _upgrade_server_tls(cr, cw, _leaf_ctx(host))
                ur, uw = await asyncio.open_connection(host, port, ssl=up_ctx, server_hostname=host)
                req = await asyncio.wait_for(cr.readuntil(b"\r\n\r\n"), timeout=15)
                uw.write(_inject_auth(req, inject_token, host))
                await uw.drain()
                await asyncio.gather(_pump(cr, uw), _pump(ur, cw))
        except Exception:  # noqa: BLE001 — no request/credential values leave this boundary
            if not established:
                try:
                    cw.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                    await cw.drain()
                except OSError:
                    pass
        finally:
            tasks.discard(task)
            for writer in (cw, uw):
                if writer is not None:
                    writer.close()
                    try:
                        await asyncio.wait_for(writer.wait_closed(), 1)
                    except Exception:  # noqa: BLE001
                        pass

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return Proxy(port=server.sockets[0].getsockname()[1], _server=server, _tasks=tasks)

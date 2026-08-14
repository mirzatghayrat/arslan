"""One-shot loopback catcher for an OAuth authorization code (RFC 8252 §7.3).

USER RULING (spec ③ §2.2): DYNAMIC port. Loopback redirects are defined to allow
127.0.0.1 with any port, so the kernel picks one (bind :0) and the redirect_uri
carries whatever it picked, for exactly one flow. A provider that refuses
anything but a fixed port gets recorded as a per-provider exception — the design
does not bend to the minority that ignores the RFC.

🔴 NOT `choose_port()` / DEFAULT_PORT: those belong to the main server, and
reusing them would make the redirect_uri depend on the main server's port
choice — two unrelated lifetimes tied together for no reason (spec §0.7).

LIFETIME. Bind, catch one code, close. The listener dying on success, denial,
timeout AND cancel is load-bearing: a lingering callback server is an open local
HTTP endpoint nobody remembers. Tests connect to the port afterwards and expect
refusal.

`state` verification and PKCE both belong to the SDK's client (spec §0.3) — this
module only ferries `code`/`state` back and never judges them.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

_CLOSE_PAGE = (
    "<!doctype html><meta charset='utf-8'><title>Arslan</title>"
    "<body style='font-family:system-ui;background:#17150F;color:#d9d2c7;"
    "display:grid;place-items:center;height:100vh;margin:0'>"
    "<p>Authorization received — you can close this tab and return to Arslan.</p>"
)


@dataclass
class CodeCatcher:
    port: int
    redirect_uri: str
    result: "asyncio.Future[tuple[str, str]]"
    _server: asyncio.AbstractServer = field(repr=False, default=None)  # type: ignore[assignment]
    _timeout_task: asyncio.Task | None = field(repr=False, default=None)

    def cancel(self) -> None:
        """Idempotent teardown for every exit path, success included."""
        if self._timeout_task is not None:
            self._timeout_task.cancel()
        if self._server is not None:
            self._server.close()
        if not self.result.done():
            self.result.cancel()


async def catch_authorization_code(*, timeout: float = 180.0) -> CodeCatcher:
    """Bind 127.0.0.1:<kernel-picked>, resolve on the first /callback hit, close."""
    loop = asyncio.get_running_loop()
    result: asyncio.Future[tuple[str, str]] = loop.create_future()
    catcher = CodeCatcher(port=0, redirect_uri="", result=result)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = (await asyncio.wait_for(reader.readline(), 5.0)).decode(
                "latin-1", "replace"
            )
            parts = request_line.split(" ")
            path = parts[1] if len(parts) >= 2 else "/"
            url = urlsplit(path)
            if url.path != "/callback":
                writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                return
            q = parse_qs(url.query)
            body = _CLOSE_PAGE.encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                + f"Content-Length: {len(body)}\r\n\r\n".encode()
                + body
            )
            await writer.drain()
            if not result.done():
                if "error" in q:
                    result.set_exception(
                        RuntimeError(f"authorization refused: {q['error'][0]}")
                    )
                else:
                    result.set_result(
                        (q.get("code", [""])[0], q.get("state", [""])[0])
                    )
                # Caught (or refused) — either way this listener's job is over.
                catcher.cancel()
        finally:
            try:
                writer.close()
            except Exception:  # noqa: BLE001 — teardown must not mask the result
                pass

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    catcher._server = server
    catcher.port = server.sockets[0].getsockname()[1]
    catcher.redirect_uri = f"http://127.0.0.1:{catcher.port}/callback"

    async def reap() -> None:
        await asyncio.sleep(timeout)
        if not result.done():
            result.set_exception(asyncio.TimeoutError(f"no callback within {timeout}s"))
        catcher.cancel()

    catcher._timeout_task = asyncio.create_task(reap())
    return catcher

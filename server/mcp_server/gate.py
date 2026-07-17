"""Fail-closed ASGI gate wrapping the inbound MCP mount (spec §Architecture 3).

Independent of require_auth (a no-op on dev+localhost). Rejects unless
mcp_server_enabled is True AND the request carries the correct dedicated MCP token
(secrets.compare_digest). Reads both PER REQUEST, so disabling the toggle or rotating
the token is immediate — combined with stateless_http=True, no established session
survives a disable. Origin/Host validation is delegated to the SDK's
transport_security inside the wrapped app (configured in build_mcp_server)."""
from __future__ import annotations

from starlette.responses import JSONResponse

from server.db import session as db_session
from server.mcp_server import audit, token_store
from server.services import settings_service


class McpServerGate:
    def __init__(self, app):
        self.app = app  # the mounted streamable-http ASGI app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            # A browser can open a cross-site WS to the mount; reject cleanly
            # (streamable-http is HTTP-only). Never reaches the MCP app.
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self._reject(scope, receive, send, 404, "not found")
            return
        async with db_session.AsyncSessionLocal() as db:
            enabled = await settings_service.mcp_server_enabled(db)
        if not enabled:
            await self._reject(scope, receive, send, 403, "MCP server is disabled")
            return
        if not token_store.mcp_token_matches(self._bearer(scope)):
            await self._reject(scope, receive, send, 401, "invalid MCP token",
                               headers={"WWW-Authenticate": "Bearer"})
            return
        # Every ACCEPTED inbound request is audited at the connection level (the
        # per-tool record in tools.py adds the tool name). Satisfies "every inbound
        # MCP request is recorded" for non-tool requests (initialize/tools/list) too.
        audit.record(tool="-", status="accept")
        await self.app(scope, receive, send)

    @staticmethod
    def _bearer(scope):
        for k, v in scope.get("headers", []):
            if k == b"authorization":
                val = v.decode("latin-1")
                if val.lower().startswith("bearer "):
                    return val[7:].strip()
        return None

    @staticmethod
    async def _reject(scope, receive, send, status, detail, *, headers=None):
        audit.record(tool="-", status="reject:%d" % status)
        await JSONResponse({"detail": detail}, status_code=status,
                           headers=headers or {})(scope, receive, send)

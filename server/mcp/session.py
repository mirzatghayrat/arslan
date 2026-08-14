"""Lazy, cached MCP stdio sessions. `_open_session` is the only SDK/subprocess touchpoint
(overridden in tests). Any call error drops the cached session so the next call relaunches."""
from __future__ import annotations

import asyncio
import logging
import os

from mcp.client.streamable_http import streamablehttp_client

from server.mcp import proxy_resolve

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 30.0


class MCPSessionManager:
    def __init__(self) -> None:
        self._sessions: dict[int, tuple[object, object]] = {}   # server_id -> (session, stack)
        self._lock = asyncio.Lock()
        self._proxy_sources: dict[int, str] = {}                # server_id -> PB-1 proxy source

    def proxy_source(self, server_id: int) -> str | None:
        """Which link of the PB-1 proxy chain hit for this server's last stdio launch."""
        return self._proxy_sources.get(server_id)

    async def _open_session(self, server: dict):
        """Open the MCP session for this server's transport. SDK-only seam (overridden in tests)."""
        from contextlib import AsyncExitStack

        from mcp import ClientSession

        stack = AsyncExitStack()
        try:
            transport = server.get("transport") or "stdio"
            if transport == "http":
                # Tokens stored for this server (a completed Authorize flow) turn
                # into the SDK's auth provider — the one argument spec ③'s recon
                # found missing. SILENT provider on purpose: a background connect
                # may refresh with stored tokens but must never open a browser;
                # the interactive flow lives in oauth_flow.authorize, behind the
                # button. No tokens ⇒ auth=None ⇒ byte-for-byte today's request.
                from server.mcp import oauth_flow

                auth = (
                    oauth_flow.silent_provider(server)
                    if await oauth_flow.has_tokens(server["id"])
                    else None
                )
                streams = await stack.enter_async_context(
                    streamablehttp_client(
                        server["url"], headers=server.get("env") or {}, auth=auth
                    )
                )
                read, write = streams[0], streams[1]          # http yields (read, write, get_session_id)
            else:
                from mcp import StdioServerParameters
                from mcp.client.stdio import stdio_client
                server_env = server.get("env") or {}
                additions, source = proxy_resolve.resolve_proxy(server_env)
                self._proxy_sources[server["id"]] = source
                logger.info(
                    "MCP stdio %s proxy source: %s", server.get("label") or server["id"], source
                )
                params = StdioServerParameters(
                    command=server["command"], args=list(server.get("args") or []),
                    env={**os.environ, **additions, **server_env},   # explicit server env wins
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            client = await stack.enter_async_context(ClientSession(read, write))
            await client.initialize()
            return client, stack
        except BaseException:
            # On any failure — including a connect-timeout cancellation — close the partial
            # stack so a half-started subprocess/connection doesn't leak on repeated timeouts.
            await stack.aclose()
            raise

    async def probe_with_auth(self, server: dict, provider) -> None:
        """One authed connect, uncached — drives the SDK's interactive flow.

        Deliberately NOT get_session: the flow's provider carries live loopback
        handlers, and caching a session built on them would pin a dead callback
        server into the cache. Open, initialize (the 401 challenge happens here
        and the SDK walks the whole flow), then close.
        """
        from contextlib import AsyncExitStack

        from mcp import ClientSession

        stack = AsyncExitStack()
        try:
            streams = await stack.enter_async_context(
                streamablehttp_client(
                    server["url"], headers=server.get("env") or {}, auth=provider
                )
            )
            client = await stack.enter_async_context(ClientSession(streams[0], streams[1]))
            await client.initialize()
        finally:
            await stack.aclose()

    async def get_session(self, server: dict):
        sid = server["id"]
        async with self._lock:
            if sid not in self._sessions:
                self._sessions[sid] = await asyncio.wait_for(
                    self._open_session(server), timeout=_CONNECT_TIMEOUT
                )
            return self._sessions[sid][0]

    async def _drop(self, sid: int) -> None:
        entry = self._sessions.pop(sid, None)
        if entry is not None:
            try:
                await entry[1].aclose()
            except Exception as exc:  # noqa: BLE001
                logger.warning("MCP session %s close failed: %s", sid, exc)

    async def list_tools(self, server: dict):
        try:
            return await (await self.get_session(server)).list_tools()
        except Exception:
            await self._drop(server["id"])
            raise

    async def call_tool(self, server: dict, name: str, args: dict):
        try:
            return await (await self.get_session(server)).call_tool(name, args)
        except Exception:
            await self._drop(server["id"])
            raise

    async def aclose_all(self) -> None:
        for sid in list(self._sessions):
            await self._drop(sid)


manager = MCPSessionManager()   # process-level singleton

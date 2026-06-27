"""Lazy, cached MCP stdio sessions. `_open_session` is the only SDK/subprocess touchpoint
(overridden in tests). Any call error drops the cached session so the next call relaunches."""
from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 30.0


class MCPSessionManager:
    def __init__(self) -> None:
        self._sessions: dict[int, tuple[object, object]] = {}   # server_id -> (session, stack)
        self._lock = asyncio.Lock()

    async def _open_session(self, server: dict):
        """Open the MCP session for this server's transport. SDK-only seam (overridden in tests)."""
        from contextlib import AsyncExitStack

        from mcp import ClientSession

        stack = AsyncExitStack()
        transport = server.get("transport") or "stdio"
        if transport == "http":
            from mcp.client.streamable_http import streamablehttp_client
            streams = await stack.enter_async_context(
                streamablehttp_client(server["url"], headers=server.get("env") or {})
            )
            read, write = streams[0], streams[1]          # http yields (read, write, get_session_id)
        else:
            import os

            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client
            params = StdioServerParameters(
                command=server["command"], args=list(server.get("args") or []),
                env={**os.environ, **(server.get("env") or {})},
            )
            read, write = await stack.enter_async_context(stdio_client(params))
        client = await stack.enter_async_context(ClientSession(read, write))
        await client.initialize()
        return client, stack

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

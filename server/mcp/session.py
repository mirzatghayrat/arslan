"""MCP sessions, one per server (0.1.61 §B1).

`_open_session` is the only SDK/subprocess touchpoint (overridden in tests). Only the supervisor and
discovery open sessions (`get_session`, `list_tools`); a tool call uses the cached session or raises
NotStarted, so a chat turn never waits for a start. A stdio server runs in its own folder
(`<data>/mcp/<id>/`), on Arslan's pinned Node/uv when its command is a bare npx/node/npm/uvx/uv and
the runtime is installed, and writes its stderr to `stderr.log` there, one start marker per run.

Measured against mcp 1.28.1 (2026-10-12): a session-wide read timeout would also bound
`initialize`, so none is set (the start budget bounds it; tools/list and tools/call have their own);
closing a half-open stack raises its own ExceptionGroup, so the cleanup never replaces the cause;
the message handler runs inside the receive loop, so it never awaits session I/O.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anyio
import anyio.lowlevel
import httpx
from mcp import types
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.exceptions import McpError

from server.mcp import proxy_resolve

logger = logging.getLogger(__name__)

LIST_TIMEOUT_S = 30.0            # tools/list, per page
CALL_TIMEOUT_S = 120.0           # tools/call: the SDK's per-request read timeout
DEFAULT_START_BUDGET_S = 60.0    # open + initialize for a server that has answered before
COLD_START_BUDGET_S = 120.0      # a first start, a server that never answered, a runtime fetched now
LOG_CAP_BYTES = 256 * 1024       # over this at a start → keep the last LOG_KEEP_BYTES
LOG_KEEP_BYTES = 64 * 1024
TAIL_BYTES = 8 * 1024
TAIL_LINES = 20
START_MARK = "--- arslan start "
#: ANSI escape sequences and control characters other than tab and newline (npm progress bars).
CONTROL_CHARS = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|[\x00-\x08\x0b-\x1f\x7f]")


class NotStarted(RuntimeError):
    """No live session for this server in this process; the supervisor starts it."""

    def __init__(self, server_id: int):
        super().__init__(f"MCP server {server_id} has no live session")
        self.server_id = server_id


class ListTimeout(TimeoutError):
    """tools/list did not answer within LIST_TIMEOUT_S (the session itself had started)."""


class LoopLocks:
    """asyncio locks for the running loop. The module-level manager outlives pytest's per-test
    loops, and a lock bound to one loop must never be awaited on another, so the set starts over
    whenever the running loop changes (production has one loop)."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._locks: dict = {}

    def get(self, key) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if loop is not self._loop:
            self._loop, self._locks = loop, {}
        return self._locks.setdefault(key, asyncio.Lock())

    def forget(self, key) -> None:
        self._locks.pop(key, None)


def server_dir(server_id: int) -> Path:
    """`<data>/mcp/<id>/`, created on demand: a stdio server's working folder and log."""
    from server import config

    path = config.data_dir() / "mcp" / str(int(server_id))
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_path(server_id: int) -> Path:
    """`<data>/mcp/<id>/stderr.log`, without creating anything."""
    from server import config

    return config.data_dir() / "mcp" / str(int(server_id)) / "stderr.log"


def is_dropped_error(exc: BaseException) -> bool:
    """The session is gone: the process exited, or the pipe or connection closed."""
    if isinstance(exc, (anyio.ClosedResourceError, anyio.BrokenResourceError)):
        return True
    return isinstance(exc, McpError) and exc.error.code == types.CONNECTION_CLOSED


def cap_log(path: Path, *, limit: int = LOG_CAP_BYTES, keep: int = LOG_KEEP_BYTES) -> None:
    """Over `limit` bytes → keep the last `keep`, rewritten in place (a child appending with
    O_APPEND carries on at the new end). Best effort: a log never blocks a start."""
    try:
        size = path.stat().st_size
        if size <= limit:
            return
        with path.open("rb+") as fh:
            fh.seek(size - keep)
            tail = fh.read()
            fh.seek(0)
            fh.write(tail)
            fh.truncate()
    except OSError:
        logger.debug("mcp log cap failed for %s", path, exc_info=True)


def read_tail(path: Path) -> str:
    """The last TAIL_LINES non-empty lines of the newest run in `path` (after its last start
    marker), within the last TAIL_BYTES, without control characters."""
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - TAIL_BYTES))
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return ""
    if START_MARK in text:
        after = text.rsplit(START_MARK, 1)[1]
        text = after.split("\n", 1)[1] if "\n" in after else ""
    lines = [line for line in CONTROL_CHARS.sub("", text).splitlines() if line.strip()]
    return "\n".join(lines[-TAIL_LINES:])


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fingerprint(server: dict) -> tuple:
    return (server.get("transport") or "stdio", server.get("command"),
            tuple(server.get("args") or ()), server.get("url"))


class MCPSessionManager:
    def __init__(self) -> None:
        self._sessions: dict[int, tuple[object, object]] = {}   # server_id -> (session, stack)
        self._fingerprints: dict[int, tuple] = {}
        self._locks = LoopLocks()
        self._proxy_sources: dict[int, str] = {}                # server_id -> PB-1 proxy source
        self._non_json: dict[int, int] = {}                     # unparsable stdout lines, this open
        self._log_marks: dict[int, float] = {}                  # monotonic time of the last start marker
        # Set by the supervisor. Both are SYNC and only schedule work: the message handler runs
        # inside the session's receive loop, and awaiting session I/O there deadlocks it.
        self.on_tools_changed: Callable[[int], None] | None = None
        self.on_dropped: Callable[[int, BaseException], None] | None = None

    def proxy_source(self, server_id: int) -> str | None:
        """Which link of the PB-1 proxy chain hit for this server's last stdio launch."""
        return self._proxy_sources.get(server_id)

    def cached(self, server_id: int):
        entry = self._sessions.get(server_id)
        return entry[0] if entry is not None else None

    def non_json_lines(self, server_id: int) -> int:
        return self._non_json.get(server_id, 0)

    def _handler(self, sid: int):
        async def handle(message) -> None:
            if isinstance(message, Exception):
                self._non_json[sid] = self._non_json.get(sid, 0) + 1
            elif (isinstance(message, types.ServerNotification)
                  and isinstance(message.root, types.ToolListChangedNotification)):
                callback = self.on_tools_changed
                if callback is not None:
                    try:
                        callback(sid)
                    except Exception:  # noqa: BLE001 — a callback bug must not kill the session
                        logger.warning("mcp %s: tools/list_changed callback failed", sid, exc_info=True)
            await anyio.lowlevel.checkpoint()
        return handle

    async def _open_session(self, server: dict):
        """Open the MCP session for this server's transport. SDK-only seam (overridden in tests)."""
        from contextlib import AsyncExitStack

        from mcp import ClientSession

        sid = server["id"]
        stack = AsyncExitStack()
        try:
            transport = server.get("transport") or "stdio"
            if transport == "http":
                # Tokens stored for this server (a completed Authorize flow) turn into the SDK's
                # auth provider. SILENT provider on purpose: a background connect may refresh with
                # stored tokens but must never open a browser; the interactive flow lives in
                # oauth_flow.authorize, behind the button. No tokens ⇒ auth=None ⇒ today's request.
                from server.mcp import oauth_flow

                auth = (
                    oauth_flow.silent_provider(server)
                    if await oauth_flow.has_tokens(server["id"])
                    else None
                )
                streams = await stack.enter_async_context(
                    streamablehttp_client(server["url"], headers=server.get("env") or {}, auth=auth)
                )
                read, write = streams[0], streams[1]          # http yields (read, write, get_session_id)
            else:
                from mcp import StdioServerParameters
                from mcp.client.stdio import stdio_client

                from server.mcp import spawn_env

                server_env = server.get("env") or {}
                # Off the event loop: scutil and the login shell are subprocesses.
                additions, source = await asyncio.to_thread(proxy_resolve.resolve_proxy, server_env)
                self._proxy_sources[sid] = source
                logger.info("MCP stdio %s proxy source: %s", server.get("label") or sid, source)
                env = spawn_env.child_environment(additions, server_env)
                # A PATH configured on the server wins over the merged (login-shell) PATH; Arslan's
                # pinned runtime goes in front of either, so `npx` finds the pinned `node`.
                user_path = server_env.get("PATH") or await asyncio.to_thread(spawn_env.merged_path)
                command, extra = spawn_env.pinned_command(server["command"])
                env["PATH"] = f"{extra}{os.pathsep}{user_path}" if extra else user_path
                if extra is None:
                    command = await asyncio.to_thread(spawn_env.resolve_command, server["command"])
                args = list(server.get("args") or [])
                if server.get("sandbox"):
                    # 0.1.57 §5.3: an installed capability runs under its own profile, in its own home.
                    from server.services import capability_sandbox

                    command, args, env, cwd = await asyncio.to_thread(
                        capability_sandbox.wrap, command, args, env, server["sandbox"])
                else:
                    cwd = str(server_dir(sid))
                params = StdioServerParameters(command=command, args=args, env=env, cwd=cwd)
                path = server_dir(sid) / "stderr.log"
                await asyncio.to_thread(cap_log, path)
                errlog = path.open("a", encoding="utf-8", errors="replace")
                stack.callback(errlog.close)
                errlog.write(f"\n{START_MARK}{_utc_iso()} ---\n")
                errlog.flush()
                self._log_marks[sid] = time.monotonic()
                read, write = await stack.enter_async_context(stdio_client(params, errlog=errlog))
            client = await stack.enter_async_context(
                ClientSession(read, write, message_handler=self._handler(sid)))
            await client.initialize()
            return client, stack
        except BaseException:
            # Keep the real cause. Closing a half-open stdio/http stack raises its own
            # ExceptionGroup(BrokenResourceError); if it escaped, it would replace the
            # TimeoutError / McpError being handled (measured 2026-10-12, mcp 1.28.1).
            try:
                await stack.aclose()
            except Exception:  # noqa: BLE001 — cleanup noise, never the cause
                logger.debug("MCP open cleanup failed for %s", sid, exc_info=True)
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
                streamablehttp_client(server["url"], headers=server.get("env") or {}, auth=provider)
            )
            client = await stack.enter_async_context(ClientSession(streams[0], streams[1]))
            await client.initialize()
        finally:
            await stack.aclose()

    async def get_session(self, server: dict, *, budget_s: float | None = None):
        """The live session, opened within the start budget when none is cached. Only the
        supervisor and discovery call this (and `list_tools`, which calls this)."""
        sid = server["id"]
        async with self._locks.get(sid):
            fingerprint = _fingerprint(server)
            if sid in self._sessions and self._fingerprints.get(sid) not in (None, fingerprint):
                await self.drop(sid)         # the row changed under this id, or the id was reused
            if sid not in self._sessions:
                budget = budget_s if budget_s is not None else float(
                    server.get("start_budget_s") or DEFAULT_START_BUDGET_S)
                self._non_json.pop(sid, None)
                self._sessions[sid] = await asyncio.wait_for(self._open_session(server), timeout=budget)
                self._fingerprints[sid] = fingerprint
            return self._sessions[sid][0]

    async def list_tools(self, server: dict, cursor: str | None = None):
        """One page of tools. Opens the session when none is cached (the supervisor's and
        discovery's path only); LIST_TIMEOUT_S per page; any failure drops the session."""
        session = await self.get_session(server)
        try:
            if cursor is None:
                request = session.list_tools()
            else:
                request = session.list_tools(params=types.PaginatedRequestParams(cursor=cursor))
            try:
                return await asyncio.wait_for(request, LIST_TIMEOUT_S)
            except TimeoutError as exc:
                raise ListTimeout(f"tools/list did not answer within {LIST_TIMEOUT_S:g} s") from exc
        except BaseException:
            await self.drop(server["id"])
            raise

    async def call_tool(self, server: dict, name: str, args: dict):
        """One tool call on the LIVE session only — never opens one (a chat turn never waits for
        a start). A server's JSON-RPC error answer leaves the session alone; anything else that
        failed drops it and tells the supervisor, which restarts it in the background."""
        sid = server["id"]
        session = self.cached(sid)
        if session is None:
            raise NotStarted(sid)
        try:
            return await session.call_tool(
                name, args, read_timeout_seconds=timedelta(seconds=CALL_TIMEOUT_S))
        except McpError as exc:
            if exc.error.code in (types.CONNECTION_CLOSED, httpx.codes.REQUEST_TIMEOUT):
                await self._drop_after_call(sid, exc)
            raise
        except Exception as exc:
            await self._drop_after_call(sid, exc)
            raise

    async def _drop_after_call(self, sid: int, exc: BaseException) -> None:
        await self.drop(sid)
        callback = self.on_dropped
        if callback is not None:
            try:
                callback(sid, exc)
            except Exception:  # noqa: BLE001
                logger.warning("mcp %s: on_dropped callback failed", sid, exc_info=True)

    async def drop(self, server_id: int) -> None:
        entry = self._sessions.pop(server_id, None)
        self._fingerprints.pop(server_id, None)
        if entry is not None:
            try:
                await entry[1].aclose()
            except Exception as exc:  # noqa: BLE001
                if "different task" in str(exc):
                    # Closed from another task than the opener: anyio complains, the process is
                    # still terminated (measured 2026-10-12).
                    logger.debug("MCP session %s closed from another task", server_id)
                else:
                    logger.warning("MCP session %s close failed: %s", server_id, exc)

    _drop = drop

    async def forget(self, server_id: int) -> None:
        """drop + every per-id record: a deleted server, whose id SQLite may hand out again."""
        await self.drop(server_id)
        self._locks.forget(server_id)
        for per_id in (self._non_json, self._proxy_sources, self._log_marks):
            per_id.pop(server_id, None)

    def stderr_tail(self, server_id: int, *, secrets: list[str], since: float | None = None) -> str:
        """The masked tail of this server's newest run. With `since` (a time.monotonic() value),
        "" unless a run started after it — a log from an earlier run, or from before this attempt
        reached the spawn, is never today's cause."""
        if since is not None and self._log_marks.get(server_id, float("-inf")) < since:
            return ""
        from server.mcp.spawn_env import mask

        return mask(read_tail(log_path(server_id)), secrets)

    async def aclose_all(self) -> None:
        for sid in list(self._sessions):
            await self.drop(sid)
        self._locks = LoopLocks()
        self._non_json.clear()
        self._log_marks.clear()


manager = MCPSessionManager()   # process-level singleton

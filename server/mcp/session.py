"""MCP sessions, one per server (0.1.61 §B1).

`_open_session` is the only SDK/subprocess touchpoint (overridden in tests). Only the supervisor and
discovery open sessions (`get_session`, `list_tools`); a tool call uses the cached session or raises
NotStarted, so a chat turn never waits for a start; a re-list and the later pages of a listing
ask for `live_only` (the cached session as it is, never an open or a restart). A stdio server runs
in its own folder (`<data>/mcp/<id>/`), on Arslan's pinned Node/uv when its command is a bare
npx/node/npm/uvx/uv and the runtime is installed, and writes its stderr to `stderr.log` there, one
start marker per run.

Measured against mcp 1.28.1 (2026-10-12): a session-wide read timeout would also bound
`initialize`, so none is set (the start budget bounds it; tools/list and tools/call have their own);
closing a half-open stack raises its own ExceptionGroup, so the cleanup never replaces the cause;
the message handler runs inside the receive loop, so it never awaits session I/O; closing a session
never wakes its pending requests (each would wait out its own timeout), so `drop` wakes them.

A session is cached only by the open that made it, and only if nothing dropped or forgot the server
while it opened (a per-server generation): a stale open closes what it made instead.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
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
from arslan.aio import within

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
FORGOTTEN_DIR = ".forgotten"     # <data>/mcp/.forgotten/<id>-<utc>/: a forgotten server's folder
FORGOTTEN_KEEP_DAYS = 30         # then, at boot, the folder goes to the user's Trash
_FORGOTTEN_STAMP = "%Y%m%dT%H%M%S%fZ"
#: The SDK's code for an http 404 on a request ("Session terminated": the server expired the
#: session). JSON-RPC's invalid-request code is -32600, which stays a server's answer.
SESSION_TERMINATED = 32600
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
        self._users: dict = {}            # key -> tasks holding or waiting for its lock

    def get(self, key) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if loop is not self._loop:
            self._loop, self._locks, self._users = loop, {}, {}
        return self._locks.setdefault(key, asyncio.Lock())

    @contextlib.asynccontextmanager
    async def hold(self, key):
        """`async with lock`, counted, so `forget` never drops a lock someone holds or awaits."""
        lock = self.get(key)
        users = self._users
        users[key] = users.get(key, 0) + 1
        try:
            async with lock:
                yield
        finally:
            users[key] -= 1
            if not users[key]:
                del users[key]

    def forget(self, key) -> None:
        """Drop the key's lock unless a task holds or awaits it (a new lock beside a held one
        would let two opens of one server run at once)."""
        if not self._users.get(key):
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
    """The session is gone: the process exited, the pipe or connection closed, or an http server
    expired the session (the SDK's "Session terminated" for a 404: a new session is needed)."""
    if isinstance(exc, (anyio.ClosedResourceError, anyio.BrokenResourceError)):
        return True
    return isinstance(exc, McpError) and exc.error.code in (types.CONNECTION_CLOSED,
                                                            SESSION_TERMINATED)


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


def _move_aside(server_id: int) -> Path | None:
    """Move `<data>/mcp/<id>/` to `<data>/mcp/.forgotten/<id>-<utc>/` (never deleted), so a later
    server that reuses the id starts in an empty folder with an empty log. Best effort."""
    from server import config

    root = config.data_dir() / "mcp"
    source = root / str(int(server_id))
    if not source.exists():
        return None
    stamp = datetime.now(timezone.utc).strftime(_FORGOTTEN_STAMP)
    target = root / FORGOTTEN_DIR / f"{int(server_id)}-{stamp}"
    n = 1
    while target.exists():
        n += 1
        target = root / FORGOTTEN_DIR / f"{int(server_id)}-{stamp}-{n}"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
    except OSError:
        logger.warning("mcp %s: could not move its folder aside", server_id, exc_info=True)
        return None
    return target


def prune_forgotten() -> list[str]:
    """At boot: `<data>/mcp/.forgotten/` entries forgotten more than FORGOTTEN_KEEP_DAYS ago go to
    the user's Trash (`capability_install.to_trash`; never deleted outright). The age is the UTC
    stamp `_move_aside` put in the name (`<id>-<stamp>` or `<id>-<stamp>-<n>`); an entry without
    one is not ours to judge and stays. Best effort; returns the names it moved."""
    from server import config
    from server.services import capability_install

    root = config.data_dir() / "mcp" / FORGOTTEN_DIR
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return []                                   # none yet (or unreadable): nothing to prune
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=FORGOTTEN_KEEP_DAYS)
    moved: list[str] = []
    for entry in entries:
        parts = entry.name.split("-")
        if len(parts) not in (2, 3) or not parts[0].isdigit():
            continue
        try:
            forgotten_at = datetime.strptime(parts[1], _FORGOTTEN_STAMP)
        except ValueError:
            continue
        if forgotten_at >= cutoff:
            continue
        try:
            capability_install.to_trash(entry)
        except Exception:  # noqa: BLE001 — the next boot tries again
            logger.warning("mcp: could not move %s to the Trash", entry.name, exc_info=True)
            continue
        moved.append(entry.name)
    return moved


def _fingerprint(server: dict) -> tuple:
    """What the running process was started from: a change under the same id reopens. The env is
    hashed (its values are secrets); the sandbox carries an installed capability's folder grants."""
    env = json.dumps(server.get("env") or {}, sort_keys=True, default=str)
    return (server.get("transport") or "stdio", server.get("command"),
            tuple(server.get("args") or ()), server.get("url"),
            hashlib.sha256(env.encode()).hexdigest(),
            json.dumps(server.get("sandbox") or None, sort_keys=True, default=str))


class MCPSessionManager:
    def __init__(self) -> None:
        self._sessions: dict[int, tuple[object, object]] = {}   # server_id -> (session, stack)
        self._fingerprints: dict[int, tuple] = {}
        self._locks = LoopLocks()
        self._proxy_sources: dict[int, str] = {}                # server_id -> PB-1 proxy source
        self._non_json: dict[int, int] = {}                     # unparsable stdout lines, this open
        self._log_marks: dict[int, float] = {}                  # monotonic time of the last start marker
        # Bumped by drop/forget (per id) and aclose_all (all ids): an open that finishes under a
        # different generation was overtaken and must not cache. Never popped (a reused id must
        # not see its counter start over under an open still running).
        self._epochs: dict[int, int] = {}
        self._closing = 0
        # server_id -> (entry, future): set when that entry is dropped, so its pending requests
        # end at once (the SDK never wakes them when the session closes).
        self._wakes: dict[int, tuple[object, asyncio.Future]] = {}
        # Closes still running, held strongly (the loop keeps only weak references): a cancel of
        # whoever awaits a close never cuts it (`_close_uncut`), and `aclose_all` waits for them.
        self._closes: set[asyncio.Task] = set()
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
        except BaseException as exc:
            # Keep the real cause. Closing a half-open stdio/http stack raises its own
            # ExceptionGroup(BrokenResourceError); if it escaped, it would replace the
            # TimeoutError / McpError being handled (measured 2026-10-12, mcp 1.28.1).
            # One exception: the http transport sends each request from a child task of its
            # task group, so a refused connection, an HTTP 401/405/500 or the silent provider's
            # NeedsInteractiveAuth fails THAT task, and anyio cancels this one (awaiting
            # initialize) — a CancelledError nobody asked for (cancelling() is 0 again once the
            # group's scope has closed). Then the group the close raises IS the cause.
            try:
                await stack.aclose()
            except Exception as cleanup:  # noqa: BLE001 — cleanup noise, never the cause
                task = asyncio.current_task()
                if (isinstance(exc, asyncio.CancelledError) and task is not None
                        and not task.cancelling()):
                    raise cleanup from None
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

    def _generation(self, sid: int) -> tuple[int, int]:
        return self._closing, self._epochs.get(sid, 0)

    def generation(self, server_id: int):
        """Moves whenever this server's session is dropped or forgotten, or every session is
        closed: a caller that noted it can tell whether the session it used was dropped since."""
        return self._generation(server_id)

    async def get_session(self, server: dict, *, budget_s: float | None = None):
        """The live session, opened within the start budget when none is cached. Only the
        supervisor and discovery call this (and `list_tools`, which calls this). The budget bounds
        open + initialize; after a timeout the cleanup (the SDK's ~2 s graceful wait, then a
        terminate) comes on top. Raises NotStarted when the server was dropped or forgotten while
        it opened: what it opened is closed, never cached."""
        return (await self._entry(server, budget_s=budget_s))[0]

    async def _entry(self, server: dict, *, budget_s: float | None = None):
        sid = server["id"]
        only = server.get("live_only")
        if only:
            # A re-list (tools/list_changed) or a later page of one listing: the session as it
            # is. No lock, no fingerprint check, no open: it never restarts a server, and a
            # start still in progress is not a live session. `live_only` is True, or the session
            # object the request must run on (a cursor belongs to the session that issued it):
            # any other session is NotStarted. The flag is invisible to `_fingerprint` (it reads
            # named keys only), like `start_budget_s`.
            entry = self._sessions.get(sid)
            if entry is None or (only is not True and entry[0] is not only):
                raise NotStarted(sid)
            return entry
        async with self._locks.hold(sid):
            fingerprint = _fingerprint(server)
            if sid in self._sessions and self._fingerprints.get(sid) not in (None, fingerprint):
                await self.drop(sid)         # the row changed under this id, or the id was reused
            entry = self._sessions.get(sid)
            if entry is None:
                budget = budget_s if budget_s is not None else float(
                    server.get("start_budget_s") or DEFAULT_START_BUDGET_S)
                self._non_json.pop(sid, None)
                generation = self._generation(sid)
                # A cancel delivered in the loop iteration in which the open finishes is never lost
                # (arslan.aio.within; wait_for returned the session and lost it, gh-86296): what was
                # opened is closed, nothing is cached, and the cancel goes on.
                entry = await within(self._open_session(server), timeout=budget,
                                     dispose=lambda opened: self._close_uncut(sid, opened))
                if self._generation(sid) != generation or sid in self._sessions:
                    # Dropped or forgotten while it opened (set_folders, a delete, shutdown), or
                    # cached by someone else: never undo that, never overwrite an entry.
                    await self._close_uncut(sid, entry)
                    raise NotStarted(sid)
                self._sessions[sid] = entry
                self._fingerprints[sid] = fingerprint
            return entry

    async def _until_dropped(self, sid: int, entry, request):
        """Await `request` (a coroutine on `entry`'s session), or raise CONNECTION_CLOSED as soon
        as `entry` is dropped: closing a session never wakes its pending requests (measured,
        mcp 1.28.1), so without this each would wait out its own timeout."""
        if self._sessions.get(sid) is not entry:
            request.close()
            raise McpError(types.ErrorData(code=types.CONNECTION_CLOSED, message="Connection closed"))
        wake = self._wakes.get(sid)
        if wake is None or wake[0] is not entry:
            wake = self._wakes[sid] = (entry, asyncio.get_running_loop().create_future())
        task = asyncio.ensure_future(request)
        try:
            await asyncio.wait({task, wake[1]}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(BaseException):
                    await task
        if task.cancelled():
            raise McpError(types.ErrorData(code=types.CONNECTION_CLOSED, message="Connection closed"))
        return task.result()

    async def list_tools(self, server: dict, cursor: str | None = None):
        """One page of tools. Opens the session when none is cached (the supervisor's and
        discovery's path only), unless `server["live_only"]` is set: then the cached session as it
        is (or the one session it names), else NotStarted. LIST_TIMEOUT_S per page; any failure drops the session it ran on
        (never a newer one under the same id)."""
        sid = server["id"]
        entry = await self._entry(server)
        try:
            if cursor is None:
                request = entry[0].list_tools()
            else:
                request = entry[0].list_tools(params=types.PaginatedRequestParams(cursor=cursor))
            try:
                return await self._until_dropped(sid, entry, within(request, LIST_TIMEOUT_S))
            except TimeoutError as exc:
                raise ListTimeout(f"tools/list did not answer within {LIST_TIMEOUT_S:g} s") from exc
        except BaseException:
            if self._sessions.get(sid) is entry:
                await self.drop(sid)
            raise

    async def call_tool(self, server: dict, name: str, args: dict):
        """One tool call on the LIVE session only — never opens one (a chat turn never waits for
        a start). A server's JSON-RPC error answer leaves the session alone; anything else that
        failed drops it and tells the supervisor, which restarts it in the background — once per
        session, and never for a session that was already dropped or replaced."""
        sid = server["id"]
        entry = self._sessions.get(sid)
        if entry is None:
            raise NotStarted(sid)
        try:
            return await self._until_dropped(sid, entry, entry[0].call_tool(
                name, args, read_timeout_seconds=timedelta(seconds=CALL_TIMEOUT_S)))
        except McpError as exc:
            if is_dropped_error(exc) or exc.error.code == httpx.codes.REQUEST_TIMEOUT:
                # shielded: a caller cut mid-close (the whole-call bound, a stopped turn) never
                # abandons the close nor the restart (re-review N-1)
                await asyncio.shield(self._drop_after_call(sid, exc, entry))
            raise
        except Exception as exc:
            await asyncio.shield(self._drop_after_call(sid, exc, entry))
            raise

    async def _drop_after_call(self, sid: int, exc: BaseException, entry) -> None:
        if self._sessions.get(sid) is not entry:
            return      # already dropped or replaced: whoever did it handles the restart
        await self.drop(sid)
        callback = self.on_dropped
        if callback is not None:
            try:
                callback(sid, exc)
            except Exception:  # noqa: BLE001
                logger.warning("mcp %s: on_dropped callback failed", sid, exc_info=True)

    async def _close(self, server_id: int, entry) -> None:
        try:
            await entry[1].aclose()
        except Exception as exc:  # noqa: BLE001
            if "different task" in str(exc):
                # Closed from another task than the opener: anyio complains, the process is
                # still terminated (measured 2026-10-12).
                logger.debug("MCP session %s closed from another task", server_id)
            else:
                logger.warning("MCP session %s close failed: %s", server_id, exc)

    async def drop(self, server_id: int) -> None:
        """Close this server's session, wake every request pending on it (CONNECTION_CLOSED),
        and make an open still running for it close what it opens instead of caching it."""
        self._epochs[server_id] = self._epochs.get(server_id, 0) + 1
        entry = self._sessions.pop(server_id, None)
        self._fingerprints.pop(server_id, None)
        wake = self._wakes.pop(server_id, None)
        if wake is not None and not wake[1].done():
            wake[1].set_result(None)
        if entry is not None:
            await self._close_uncut(server_id, entry)

    _drop = drop

    async def _close_uncut(self, server_id: int, entry) -> None:
        """`_close`, never cut by a cancel of whoever awaits it (final review, fix A). The SDK's stdio
        close is "stdin closed → up to 2 s for the process → terminate it"; a cancel landing in that
        wait skips the terminate, and anyio's Process.aclose() then waits for the process with no
        bound — whoever awaits the cancelled task (a switch-off, a delete, an edit's fresh start,
        shutdown) hangs until the server exits by itself, and a server that ignores stdin EOF never
        does. So the close runs as its own task, held in `_closes`: a cancelled caller leaves at once,
        the close finishes (the terminate runs), and `aclose_all` waits for the ones still running."""
        closing = asyncio.ensure_future(self._close(server_id, entry))
        self._closes.add(closing)
        closing.add_done_callback(self._closes.discard)
        await asyncio.shield(closing)

    async def forget(self, server_id: int) -> None:
        """drop + every per-id record + its folder moved aside (never deleted): a deleted server,
        whose id SQLite may hand out again, leaves nothing for the next one to inherit."""
        await self.drop(server_id)
        self._locks.forget(server_id)
        from server.mcp import discovery      # imports this module, so only here

        discovery.forget(server_id)
        for per_id in (self._non_json, self._proxy_sources, self._log_marks):
            per_id.pop(server_id, None)
        await asyncio.to_thread(_move_aside, server_id)

    def stderr_tail(self, server_id: int, *, secrets: list[str], since: float | None = None) -> str:
        """The masked tail of this server's newest run. With `since` (a time.monotonic() value),
        "" unless a run started after it — a log from an earlier run, or from before this attempt
        reached the spawn, is never today's cause."""
        if since is not None and self._log_marks.get(server_id, float("-inf")) < since:
            return ""
        from server.mcp.spawn_env import mask

        return mask(read_tail(log_path(server_id)), secrets)

    async def aclose_all(self) -> None:
        """Close every session; an open still running closes what it opens. The locks stay (an
        opener may hold one; LoopLocks starts over by itself on a new loop) and so do the
        folders."""
        self._closing += 1
        for sid in list(self._sessions):
            await self.drop(sid)
        # A close a cancelled caller left running (fix A) ends before the loop does: the SDK's
        # terminate step must run, or a server that ignores stdin EOF outlives Arslan. Only this
        # loop's: the module-level manager outlives a test's loop, and a task of a closed loop never
        # finishes (it is let go).
        loop = asyncio.get_running_loop()
        pending = [task for task in self._closes if not task.done() and task.get_loop() is loop]
        self._closes.difference_update([task for task in self._closes if task.get_loop() is not loop])
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._non_json.clear()
        self._log_marks.clear()


manager = MCPSessionManager()   # process-level singleton

"""The MCP supervisor (0.1.61 §B1): every enabled server starts in the background, each has one
state the UI and the model read, failures keep their cause, and a chat turn never waits.

States: off | starting | ready | failed | needs_auth | parked.

- A start is a *plan* of attempts — `first` (an attempt, then up to 3 more after 1/2/4 s),
  `retry`, `probe`, `refresh` and `restart` (one attempt each). One plan is in flight per server.
  `restart` (Connect, Reconnect, the install test) joins an attempt that is running — one process —
  and otherwise replaces the pending plan (an attempt still queued for a slot included); it is the
  only plan that starts a switched-off server.
- The supervisor holds no per-server lock: the session manager's lock guards only the open, and
  the semaphore (MAX_CONCURRENT) is held around one background attempt, never across a backoff
  sleep. A `restart` is the user's own start and skips it (final review M-2): it never queues behind
  background attempts that may hold every slot for 60–120 s.
- Every write goes through `_set`: one short transaction, dropped when a newer plan (generation)
  has started since, or when the row is gone. The legacy status/health_status follow the state.
- A failed server is retried after 30 s, doubling to 600 s (counted per plan); parked and
  needs_auth servers probe every 300 s; a dropped session reconnects up to 5 times, then falls back
  to the backoff.
- An open overtaken by a drop or forget (`NotStarted`) is neither a failure nor a park: nothing is
  written and fail_count does not move — whoever dropped the session starts it again
  (`schedule(fresh=True)`, which cancels a running attempt, so the replacement never waits out the
  overtaken open's budget). A re-list that finds the session dead schedules that fresh start
  itself: `list_tools` never calls `on_dropped`.
- Masking never raises: `spawn_env.secret_forms` refuses a malformed URL, so `_secrets` falls back.
- Only a `ready` with a live session in this process is offered to the model (`ready_now`). The tick
  restarts a `ready` row with no live session and no start on its way — the safety net for a session
  that vanished without a drop callback — and starts a switched-on row still `off` (a switch-on whose
  `starting` write failed).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import anyio
import httpx
from mcp import types
from mcp.shared.exceptions import McpError
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm.exc import StaleDataError

from server.db import session as db_session
from server.db.models import MCPServer, Tool
from server.mcp import discovery, oauth_flow, spawn_env
from server.mcp import session as mcp_session
from arslan.aio import within

logger = logging.getLogger(__name__)

#: "0" leaves the background supervisor off (the test suite sets it in tests/conftest.py; the
#: app's lifespan reads it through `switched_on`). Exactly this name.
SWITCH_ENV = "ARSLAN_MCP_SUPERVISOR"

MAX_CONCURRENT = 4
FIRST_START_GAPS_S = (1.0, 2.0, 4.0)
RETRY_BASE_S = 30
RETRY_CAP_S = 600
PROBE_EVERY_S = 300
MAX_RECONNECTS = 5
RECONNECT_RESET_S = 600.0
LOOP_TICK_S = 15.0
RELIST_DEBOUNCE_S = 0.5
RUNTIME_FETCH_S = 600.0
LIVE_LOG_CAP_BYTES = 1024 * 1024
LAST_ERROR_CAP = 2000
OK_WRITE_EVERY_S = 60.0
STARTING_STALE_S = 60.0          # a `starting` row that no plan owns for this long is restarted
BOOT_RESET_RETRY_S = (1.0, 2.0, 4.0, 8.0, 16.0)   # a failed boot reset is retried this far apart

LEGACY_STATUS = {"ready": "connected", "starting": "connecting", "failed": "error",
                 "parked": "error", "needs_auth": "error"}
LEGACY_HEALTH = {"ready": "ok", "failed": "failing", "parked": "failing", "needs_auth": "failing"}
_RUNTIME_NAMES = {"node": "Node.js", "uv": "uv"}

NOT_MCP_LINE = ("this program did not answer as an MCP server — it may need a start flag such as "
                "`--mcp`")
#: How an OAuth server's sign-in line begins: such a server is asked to sign in (Authorize), even
#: when it also sends headers (Task 7 re-review R5).
SIGN_IN_PREFIX = "authorization needed:"
SIGN_IN_LINE = (f"{SIGN_IN_PREFIX} the saved sign-in expired or was never completed — use "
                "Authorize on this server in Capabilities")
#: How `_give_up`'s line begins: a server that keeps dropping its connection is answered as unstable,
#: never as failing to start (Task 7 review M-3).
GAVE_UP_LINE = "the server keeps dropping its connection"
#: The beginnings of every line `classify` and `_give_up` write. Only such a line may enter the
#: system prompt (ruling 6); `_describe_failure` text and anything else stays out.
SAFE_REASON_PREFIXES = (
    "authorization failed (HTTP ", SIGN_IN_PREFIX, "command `", "program `",
    "the URL did not answer as an MCP endpoint", "did not answer tools/list within ",
    "did not start within ", "the connection closed during start",
    "this program did not answer as an MCP server", "the server exited during start",
    "speaks an MCP version", "the server refused to start (MCP error ",
    "could not reach the MCP URL", GAVE_UP_LINE,
    "the MCP URL answered HTTP ", "the connection ended the start without a reason",
)


def _utcnow() -> datetime:
    """Naive UTC, like every DateTime column here."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ready_now(server_id: int, state: str | None) -> bool:
    """0.1.61 §B1 exposure (Task 7, amended after its review): a server is ready in this process —
    its tools offered, its calls made — only when its row says `ready` AND the session manager holds
    a live session for it. Every `ready` this process writes has its session cached first, so this
    loses nothing; a `ready` with nothing behind it (the last run's, after a failed boot reset; one
    whose session died while its restart waits for a start slot) offers nothing, is told as still
    starting, and the tick restarts it (`_tick`)."""
    return state == "ready" and mcp_session.manager.cached(server_id) is not None


def switched_on() -> bool:
    """False when ARSLAN_MCP_SUPERVISOR is "0" (the test suite); on by default, and always in the desktop
    app's frozen server, whatever its environment says (0.1.63, after #364)."""
    if getattr(sys, "frozen", False):
        return True
    return os.environ.get(SWITCH_ENV, "1") != "0"


def _secrets(server: dict) -> list[str]:
    """This server's secret forms for masking. `spawn_env.secret_forms` raises ValueError on a
    malformed URL (`http://[::1/mcp`), and masking must never raise: then the env forms, the URL
    as written and the query values as written (over-masking a broken URL is harmless)."""
    try:
        return spawn_env.secret_forms(server)
    except Exception:  # noqa: BLE001 — a malformed URL; never let masking fail a start
        logger.debug("mcp %s: secret_forms failed; masking with the fallback", server.get("id"),
                     exc_info=True)
    try:
        forms = spawn_env.secret_forms({"env": server.get("env") or {}})
    except Exception:  # noqa: BLE001 — an env that is not a dict of strings
        forms = []
    url = str(server.get("url") or "")
    extra = [url, *(pair.partition("=")[2] for pair in url.partition("?")[2].split("&") if "=" in pair)]
    return sorted({*forms, *(value for value in extra if len(value) >= 4)}, key=len, reverse=True)


def mask_for(server: dict, text: str) -> str:
    """`text` with this server's own secrets replaced by ****; never raises. For every `last_error`
    written outside the supervisor too (the health probe), so a secret never reaches the UI or a
    tool result through that column."""
    return spawn_env.mask(text, _secrets(server))


@dataclass
class StartResult:
    state: str
    tools: list[dict] = field(default_factory=list)
    tool_count: int = 0
    last_error: str | None = None
    next_retry_at: datetime | None = None


def _chain(exc: BaseException) -> list[BaseException]:
    """exc, its group members, causes and contexts — depth-limited (anyio wraps transport errors)."""
    seen: list[BaseException] = [exc]
    i = 0
    while i < len(seen) and len(seen) < 64:
        current = seen[i]
        i += 1
        for link in (*(getattr(current, "exceptions", ()) or ()), current.__cause__,
                     current.__context__):
            if link is not None and link not in seen:
                seen.append(link)
    return seen


def _missing_line(err: BaseException, server: dict) -> str:
    command = str(server.get("command") or "")
    if os.path.sep in command:
        return f"program `{command[:120]}` is missing or not executable — reinstall it"
    name = command[:60]
    if isinstance(err, PermissionError):
        return f"command `{name}` is not executable — check its permissions"
    runtime = spawn_env.runtime_for(command)
    if runtime is not None:
        return f"command `{name}` not found — install {_RUNTIME_NAMES[runtime]}, or let Arslan fetch it"
    return f"command `{name}` not found — install it, or give its full path"


def classify(exc: BaseException, *, server: dict, non_json: int, budget_s: float) -> tuple[str, str]:
    """(state, line) for a failed start, from the exception shapes the SDK really produces
    (measured 2026-10-12). `line` is Arslan's own words: the server's own text (an McpError
    message, its stderr) never becomes the line — it goes below it, with the tail."""
    chain = _chain(exc)
    http = (server.get("transport") or "stdio") == "http"

    def find(kind):
        return next((e for e in chain if isinstance(e, kind)), None)

    def mcp_code(*codes):
        return next((e for e in chain if isinstance(e, McpError) and e.error.code in codes), None)

    # 1 sign-in
    if find(oauth_flow.NeedsInteractiveAuth) is not None:
        return "needs_auth", SIGN_IN_LINE
    status = find(httpx.HTTPStatusError)
    if status is not None and status.response.status_code in (401, 403):
        return "needs_auth", discovery._describe_failure(status, has_headers=bool(server.get("env")))
    # 2 the program is missing or cannot run (a program: an http server's OSError is about the URL)
    missing = None if http else find((FileNotFoundError, PermissionError))
    if missing is not None:
        return "parked", _missing_line(missing, server)
    # 3 an http URL that is not an MCP endpoint (a 404 arrives as McpError 32600 "Session terminated")
    if http and ((status is not None and status.response.status_code in (404, 405)) or mcp_code(32600)):
        code = status.response.status_code if status is not None else 404
        return "parked", (f"the URL did not answer as an MCP endpoint (HTTP {code}) — check the "
                          "path, often /mcp")
    # 3b any other HTTP answer: a server error retries like an unreachable URL; the rest name it
    if http and status is not None:
        code = status.response.status_code
        if code >= 500:
            return "failed", f"could not reach the MCP URL — it answered HTTP {code}, a server error"
        return "failed", f"the MCP URL answered HTTP {code}"
    # 4 timeouts: tools/list first (ListTimeout is a TimeoutError), then the start budget
    if find(mcp_session.ListTimeout) is not None or mcp_code(httpx.codes.REQUEST_TIMEOUT):
        return "failed", f"did not answer tools/list within {mcp_session.LIST_TIMEOUT_S:g} s"
    if find(TimeoutError) is not None:
        return "failed", f"did not start within {budget_s:g} s (still downloading?)"
    # 5 the process or the connection went away during the start
    if mcp_code(types.CONNECTION_CLOSED) or find((anyio.ClosedResourceError, anyio.BrokenResourceError)):
        if http:
            return "failed", "the connection closed during start"
        if non_json > 0:
            return "parked", NOT_MCP_LINE
        return "failed", "the server exited during start — see its log below"
    # 6 a protocol version the SDK does not speak
    if any(isinstance(e, RuntimeError) and "Unsupported protocol version" in str(e) for e in chain):
        return "parked", "speaks an MCP version Arslan does not support"
    # 7 the server answered the start with a JSON-RPC error (its message stays out of the line)
    answered = find(McpError)
    if answered is not None:
        return "failed", f"the server refused to start (MCP error {answered.error.code})"
    # 8 an http transport error
    if http and find(httpx.TransportError) is not None:
        return "failed", "could not reach the MCP URL — check the address and the network"
    # 9 a cancel nobody asked for (the transport ended the start and nothing above says why)
    if isinstance(exc, asyncio.CancelledError):
        return "failed", "the connection ended the start without a reason"
    # 10 anything else: today's classified text of the first real exception (never a task
    #    group's own "unhandled errors in a TaskGroup"), never empty
    leaf = next((e for e in chain if not isinstance(e, BaseExceptionGroup)), exc)
    return "failed", discovery._describe_failure(leaf, has_headers=bool(server.get("env")))


def budget_for(row, tool_count: int, *, fetched: bool = False, cold: bool = False) -> float:
    """COLD_START_BUDGET_S for a first start (no tools listed yet), a server that never answered,
    when its runtime was fetched in this start, after a failed plan, or when the caller asks
    (`cold`: an edit's fresh start, `Supervisor._cold`); DEFAULT_START_BUDGET_S otherwise. Every plan
    uses it. After a failed plan (final review I-3): a server that worked once and whose package is
    no longer cached — an npm cache cleaned, a new version of an unpinned `npx -y pkg` — needs its
    cold start again; at the warm budget every attempt and every retry is killed mid-download and it
    never starts. fail_count goes back to 0 on `ready`."""
    if (tool_count == 0 or getattr(row, "last_ok_at", None) is None or fetched or cold
            or (getattr(row, "fail_count", 0) or 0) > 0):
        return mcp_session.COLD_START_BUDGET_S
    return mcp_session.DEFAULT_START_BUDGET_S


def safe_reason(text: str | None) -> str:
    """The first line of `text` when it is in Arslan's own vocabulary, else ""."""
    line = mcp_session.CONTROL_CHARS.sub("", (text or "").split("\n", 1)[0]).strip()
    return line[:120] if line.startswith(SAFE_REASON_PREFIXES) else ""


def fix_for(state: str, *, has_headers: bool, reason: str = "", next_retry_at=None) -> str:
    """What fixes a server in this state, in words for the model and the user."""
    if state == "starting":
        return "wait a moment; it is starting by itself"
    if state == "failed":
        when = f" (next try {next_retry_at})" if next_retry_at else ""
        return f"it retries by itself{when}; the user can press Reconnect in Capabilities"
    if state == "needs_auth":
        return ("re-check the key/token on this server in Capabilities" if has_headers
                else "the user must sign in from Capabilities (Authorize)")
    if state == "parked":
        cause = f": {reason}" if reason else ""
        return f"it is stopped until the cause is fixed{cause}; then the user can press Reconnect in Capabilities"
    if state == "off":
        # `off` is the state, not a verdict on who did it: the user's switch, or an install whose test
        # failed (installs are created off and left off). Never "the user" (Task 8 review I-1).
        return "switched off; it can be switched on in Capabilities"
    return ""


class Supervisor:
    def __init__(self) -> None:
        self.running = False
        self._sem: asyncio.Semaphore | None = None
        self._inflight: dict[int, asyncio.Task] = {}          # the plan in flight per server
        self._attempt_fut: dict[int, asyncio.Future] = {}     # present while an attempt runs
        self._gen: dict[int, int] = {}
        self._notes: dict[int, str] = {}
        self._fetch_error: dict[int, str] = {}
        self._reconnects: dict[int, int] = {}
        self._ready_since: dict[int, float] = {}
        self._ok_written: dict[int, float] = {}
        self._relist_wanted: set[int] = set()
        self._relisting: set[int] = set()
        self._bg: set[asyncio.Task] = set()
        self._loop_task: asyncio.Task | None = None
        # server -> deliberate verbs (forget, switch-off, give-up) acting on it right now. Each
        # takes the plan out of _inflight and then awaits its unwinding; the tick must not read
        # that window as "starting, no plan" and start the server again.
        self._busy: dict[int, int] = {}
        # Servers whose next starts get the cold budget until one is ready: an edit's fresh start
        # (`schedule(cold=True)`: the update may have changed the package). A flag, never a cleared
        # last_ok_at (final review, fix C).
        self._cold: set[int] = set()
        # server -> the marker of its attempt while it waits for a slot: `restart` never joins that
        # one (final review M-2).
        self._queued: dict[int, object] = {}
        # server -> the lock `_set` holds across its generation check AND its transaction: a write
        # that passed the check can never land after a newer generation's (re-review: a switch-off's
        # `off` landing after a Connect's `ready` left a process running for a switched-off server).
        self._set_locks = mcp_session.LoopLocks()

    # ── lifecycle ──────────────────────────────────────────────────────────────────────
    def start(self, *, run_loops: bool = True) -> None:
        """Called from lifespan after reset_for_boot. Tests pass run_loops=False to get the hooks
        and the semaphore without start_all and the periodic loop."""
        if self.running:
            return
        self.running = True
        self._sem = asyncio.Semaphore(MAX_CONCURRENT)
        mcp_session.manager.on_tools_changed = self._on_tools_changed
        mcp_session.manager.on_dropped = self._on_dropped
        if run_loops:
            self._spawn_bg(self._boot())
            self._loop_task = asyncio.create_task(self._loop(), name="mcp-supervisor-loop")

    async def stop(self) -> None:
        self.running = False
        mcp_session.manager.on_tools_changed = None
        mcp_session.manager.on_dropped = None
        tasks = [t for t in (*self._bg, *self._inflight.values(), self._loop_task)
                 if t is not None and not t.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._bg.clear()
        self._inflight.clear()
        self._attempt_fut.clear()
        self._queued.clear()
        self._relisting.clear()       # a re-list cancelled before its first step never ran its finally
        self._relist_wanted.clear()
        self._loop_task = None
        self._sem = None

    async def reset_for_boot(self, *, written_before: datetime | None = None) -> None:
        """A `ready` (or a pending retry) from an earlier process is never trusted: every enabled
        server is `starting` until this process has a live session. last_error is kept.
        `written_before` (a retry after a failed boot reset) limits it to the rows nothing has
        written since then — never stamped, or stamped by an earlier process: a state this process
        already wrote stands."""
        now = _utcnow()
        unwritten = [] if written_before is None else [
            or_(MCPServer.state_at.is_(None), MCPServer.state_at < written_before)]
        async with db_session.AsyncSessionLocal() as db:
            await db.execute(update(MCPServer).where(MCPServer.host_allowed.is_(False), *unwritten)
                             .values(state="off", state_at=now, next_retry_at=None))
            await db.execute(update(MCPServer).where(MCPServer.host_allowed.is_(True), *unwritten)
                             .values(state="starting", status="connecting", state_at=now,
                                     next_retry_at=None))
            await db.commit()

    def retry_boot_reset(self) -> None:
        """reset_for_boot failed at boot (a locked database): retry it in the background,
        BOOT_RESET_RETRY_S apart, for the rows nothing in this process has written by then — so a
        `ready` left from the last run (migration 0068 maps connected → ready) never keeps its
        tools offered with no session behind them. Called before `start()`: nothing in this process
        has written a state yet."""
        self._spawn_bg(self._retry_boot_reset(_utcnow()))

    async def _retry_boot_reset(self, since: datetime) -> None:
        for gap in BOOT_RESET_RETRY_S:
            await asyncio.sleep(gap)
            try:
                await self.reset_for_boot(written_before=since)
                return
            except Exception:  # noqa: BLE001 — the next try, or the error below
                logger.warning("mcp: the boot reset failed again", exc_info=True)
        logger.error("mcp: the boot reset never succeeded; a `ready` from the last run may remain "
                     "until its server starts")

    async def _boot(self) -> None:
        await asyncio.to_thread(spawn_env.login_shell_path)     # prewarm, off the event loop
        await self.start_all()

    async def start_all(self) -> None:
        """Every switched-on server, at most MAX_CONCURRENT attempts at once; returns when they
        have settled."""
        async with db_session.AsyncSessionLocal() as db:
            ids = (await db.execute(select(MCPServer.id).where(MCPServer.host_allowed.is_(True))
                                    .order_by(MCPServer.id))).scalars().all()
        tasks = []
        for sid in ids:
            task = self._inflight.get(sid)
            tasks.append(task if task is not None and not task.done() else self._new_plan(sid, "first"))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ── the public verbs ───────────────────────────────────────────────────────────────
    def schedule(self, server_id: int, *, fresh: bool = False, cold: bool = False) -> None:
        """Start this server soon, in the background; never waits; a no-op unless running.
        fresh=True (a drop, new folders, a dead re-list) replaces whatever plan is in flight —
        a running attempt included: its open was overtaken, and the replacement must never wait
        out that open's budget — with one fresh attempt that respects the user's switch;
        otherwise a plan in flight or a live session is left alone. cold=True (an edit) gives its
        starts the cold budget until one is ready — also a Connect's, and when nothing runs."""
        if cold:
            self._cold.add(server_id)
        if not self.running:
            return
        if fresh:
            self._new_plan(server_id, "refresh")
            return
        task = self._inflight.get(server_id)
        if (task is not None and not task.done()) or mcp_session.manager.cached(server_id) is not None:
            return
        self._new_plan(server_id, "first")

    async def restart(self, server_id: int) -> StartResult:
        """A fresh start now — Connect, Reconnect, the install test. Joins an attempt already
        running (one process); otherwise replaces whatever plan is pending, an attempt still queued
        for a slot included, and never waits for a slot itself (M-2). Works whether or not the
        background supervisor runs; raises ValueError for an unknown id."""
        async with db_session.AsyncSessionLocal() as db:
            if await db.get(MCPServer, server_id) is None:
                raise ValueError(f"mcp server {server_id} not found")
        running = self._attempt_fut.get(server_id)
        if running is None or server_id in self._queued:
            # nothing running, or an attempt still queued for a slot: the user's start goes now
            # (M-2) and replaces it, never joining it at the back of the queue
            waitable = self._new_plan(server_id, "restart")
        else:
            waitable = running
        for _ in range(3):
            try:
                return await asyncio.shield(waitable)
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise                         # the caller's own cancel (wait_for, shutdown)
                # The attempt was replaced by a fresh one (a drop, new folders): answer with the
                # replacement's result. Switch-off, delete and give-up take the plan out of
                # _inflight first, so they find nothing to follow and say "cancelled".
                follow = self._attempt_fut.get(server_id) or self._inflight.get(server_id)
                if follow is None or follow is waitable or follow.done():
                    break
                waitable = follow
        return StartResult("failed", last_error="the start was cancelled (the server was "
                           "switched off, removed or restarted)")

    async def forget(self, server_id: int) -> None:
        """A deleted server: cancel its plan, drop late writes, close and forget its session."""
        with self._verb(server_id):
            self._bump(server_id)
            await self._cancel_plan(server_id)
            await mcp_session.manager.forget(server_id)
            for per_id in (self._notes, self._fetch_error, self._reconnects, self._ready_since,
                           self._ok_written):
                per_id.pop(server_id, None)
            self._relist_wanted.discard(server_id)
            self._cold.discard(server_id)

    async def set_enabled(self, server_id: int, on: bool) -> None:
        """The user's switch. Off: cancel the plan, stop the process, state `off`. On: `starting`
        and a start, unless it is already running or starting — a session or plan whose row says
        `starting` or `ready`. A session or plan the state does not account for (any path that
        cached a session for an `off` server) is replaced by a fresh start, never taken for "already
        running" (Task 6 fix round 1, F2). The caller commits `host_allowed` first: a background
        plan reads the row to respect the switch."""
        if on:
            task = self._inflight.get(server_id)
            running = (mcp_session.manager.cached(server_id) is not None
                       or (task is not None and not task.done()))
            if running and await self._state_of(server_id) in ("starting", "ready"):
                return
            await self._set(server_id, self._bump(server_id), "starting")
            self.schedule(server_id, fresh=running)
            return
        with self._verb(server_id):
            gen = self._bump(server_id)
            await self._cancel_plan(server_id)
            await mcp_session.manager.drop(server_id)
            self._ready_since.pop(server_id, None)
            self._notes.pop(server_id, None)
            await self._set(server_id, gen, "off")

    def note(self, server_id: int) -> str | None:
        """What a starting server is doing now, e.g. "downloading Node 24.21.0 (50 MB)"."""
        return self._notes.get(server_id)

    def start_in_flight(self, server_id: int) -> bool:
        """An attempt for this server is queued or running: it drops the session and opens a new
        one itself, so nobody else should drop it now (the health probe, carry 2b)."""
        return server_id in self._attempt_fut

    def generation(self, server_id: int) -> int:
        """Moves with every new plan and every deliberate verb (forget, switch-off, give-up): a
        caller that noted it before a drop can tell a deliberate drop from a death, like `_relist`."""
        return self._gen.get(server_id, 0)

    async def _state_of(self, server_id: int) -> str | None:
        async with db_session.AsyncSessionLocal() as db:
            row = await db.get(MCPServer, server_id)
        return row.state if row is not None else None

    def note_ok(self, server_id: int) -> None:
        """A successful call refreshes last_ok_at, at most once a minute per server (spec §B1:
        "every start, call and probe updates the state")."""
        if not self.running:
            return
        now = time.monotonic()
        if now - self._ok_written.get(server_id, float("-inf")) < OK_WRITE_EVERY_S:
            return
        self._ok_written[server_id] = now
        self._spawn_bg(self._write_ok(server_id))

    # ── plans and attempts ─────────────────────────────────────────────────────────────
    def _bump(self, server_id: int) -> int:
        self._gen[server_id] = self._gen.get(server_id, 0) + 1
        return self._gen[server_id]

    @contextlib.contextmanager
    def _verb(self, server_id: int):
        """Mark a deliberate verb acting on this server (counted: two may overlap)."""
        self._busy[server_id] = self._busy.get(server_id, 0) + 1
        try:
            yield
        finally:
            left = self._busy[server_id] - 1
            if left:
                self._busy[server_id] = left
            else:
                del self._busy[server_id]

    def _spawn_bg(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
        return task

    async def _cancel_plan(self, server_id: int) -> None:
        task = self._inflight.pop(server_id, None)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _new_plan(self, server_id: int, plan: str) -> asyncio.Task:
        old = self._inflight.get(server_id)
        if old is not None and not old.done():
            old.cancel()
        gen = self._bump(server_id)
        task = asyncio.create_task(self._run(server_id, gen, plan), name=f"mcp-start-{server_id}")
        self._inflight[server_id] = task
        task.add_done_callback(lambda t, sid=server_id: self._plan_done(sid, t))
        return task

    def _plan_done(self, server_id: int, task: asyncio.Task) -> None:
        if self._inflight.get(server_id) is task:
            del self._inflight[server_id]
            if task.cancelled() and self.running:
                # every deliberate cancel (a new plan, switch-off, delete, give-up, stop) takes
                # the plan out of _inflight first: this one ended without anybody asking
                logger.warning("mcp %s: start plan ended cancelled; nobody asked for it", server_id)
        if not task.cancelled() and task.exception() is not None:
            logger.warning("mcp %s: start plan crashed", server_id, exc_info=task.exception())

    async def _run(self, sid: int, gen: int, plan: str) -> StartResult:
        gaps = FIRST_START_GAPS_S if plan == "first" else ()
        attempt = 0
        while True:
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            self._attempt_fut[sid] = fut
            try:
                result = await self._attempt_limited(sid, gen, plan)
                final = result.state != "failed" or attempt >= len(gaps)
                if final:
                    result = await self._settle(sid, gen, result)
                else:
                    await self._set(sid, gen, "starting", error=result.last_error)
            except BaseException:
                if not fut.done():
                    fut.cancel()
                raise
            finally:
                if self._attempt_fut.get(sid) is fut:
                    del self._attempt_fut[sid]
            if not fut.done():
                fut.set_result(result)
            if final:
                return result
            await asyncio.sleep(gaps[attempt])
            attempt += 1

    async def _attempt_limited(self, sid: int, gen: int, plan: str) -> StartResult:
        """One attempt, in one of the MAX_CONCURRENT slots — unless the supervisor is not running (an
        API request or a test: no queue) or it is the user's own start (`restart`: Connect, the
        install test, add_capability), which never waits behind background attempts (final review
        M-2). The session manager's per-server lock still lets one start of a server open at a time."""
        sem = self._sem      # the one this attempt acquires is the one it releases (stop() sets None)
        if sem is None or plan == "restart":
            return await self._attempt(sid, gen, plan)
        mark = object()
        self._queued[sid] = mark
        try:
            await sem.acquire()
        finally:
            if self._queued.get(sid) is mark:
                del self._queued[sid]
        try:
            return await self._attempt(sid, gen, plan)
        finally:
            sem.release()

    async def _attempt(self, sid: int, gen: int, plan: str) -> StartResult:
        """One fresh process: drop any cached session, fetch the runtime if needed (outside the
        budget), then open + list + write the tools within the budget. A switched-off server is
        never marked `starting` by a background plan. An open overtaken by a drop or forget
        (NotStarted) is `starting` again with nothing written: not a failure, not a park, and
        fail_count stays (carry 2a). Never raises, except on cancellation."""
        async with db_session.AsyncSessionLocal() as db:
            row = await db.get(MCPServer, sid)
            if row is None:
                return StartResult("off", last_error="removed")
            switched_off = not row.host_allowed and plan != "restart"
            if not switched_off:
                server = discovery.runtime_dict(row)
                tool_count = (await db.execute(select(func.count()).select_from(Tool)
                                               .where(Tool.toolset_key == f"mcp_{sid}"))).scalar_one()
        if switched_off:
            # Never a live process behind an `off` row: a Connect is allowed on a switched-off
            # server and leaves its session, which this start must not leave running under the
            # `off` it is about to write. Only the current generation drops; a stale plan has no
            # say over a session that is not its own.
            if self._gen.get(sid, 0) == gen:
                await mcp_session.manager.drop(sid)
            return StartResult("off")
        await self._set(sid, gen, "starting")
        await mcp_session.manager.drop(sid)
        dropped_at = mcp_session.manager.generation(sid)       # any later drop moves it
        secrets = _secrets(server)
        cold = sid in self._cold
        budget = budget_for(row, tool_count, cold=cold)
        began = time.monotonic()
        try:
            if await self._ensure_runtime(sid, server):
                budget = budget_for(row, tool_count, fetched=True, cold=cold)
            tools = await discovery.connect_and_discover(sid, start_budget_s=budget)
        except discovery.ServerGone:
            await mcp_session.manager.drop(sid)          # never a live process for a vanished row
            return StartResult("off", last_error="removed")
        except mcp_session.NotStarted:
            return StartResult("starting")      # overtaken, not failed: `_settle` writes nothing
        except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 — classified below
            current = asyncio.current_task()
            if current is None or current.cancelling():
                # A real cancel (switch-off, delete, a new plan, shutdown) is never a cause — also
                # when CPython 3.11's wait_for swallowed it (cancelled in the very iteration the
                # open failed) and raised the open's own error in its place.
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise asyncio.CancelledError() from exc
            state, line = classify(exc, server=server, budget_s=budget,
                                   non_json=mcp_session.manager.non_json_lines(sid))
            command = str(server.get("command") or "")
            code, runtime = self._fetch_error.get(sid), spawn_env.runtime_for(command)
            if state == "parked" and code and runtime and line.startswith("command `"):
                line = (f"command `{command}` not found, and Arslan could not fetch "
                        f"{'Node' if runtime == 'node' else 'uv'} ({code}) — install "
                        f"{_RUNTIME_NAMES[runtime]}, or check the network")
            tail = mcp_session.manager.stderr_tail(sid, secrets=secrets, since=began)
            text = line if not tail else f"{line}\n{tail}"
            return StartResult(state, last_error=spawn_env.mask(text, secrets)[:LAST_ERROR_CAP])
        finally:
            self._notes.pop(sid, None)
        if self._gen.get(sid, 0) != gen:
            # Superseded while it opened (a verb moved the generation; a replaced plan whose cancel
            # was lost lands here too): a stale plan never caches. What it opened is closed and
            # nothing is written — unless a newer plan is in flight, which drops and opens afresh
            # itself and must not find its session closed under it.
            newer = self._inflight.get(sid)
            if newer is None or newer.done() or newer is asyncio.current_task():
                await mcp_session.manager.drop(sid)
            return StartResult("starting")
        if mcp_session.manager.generation(sid) != dropped_at:
            # The session this start listed on was dropped before the start ended — another
            # caller's tools/list failed on it: never `ready` with no session behind it (ruling 11;
            # Task 6 fix round 1, F1).
            line = ("the connection closed during start" if (server.get("transport") or "stdio") == "http"
                    else "the server exited during start — see its log below")
            tail = mcp_session.manager.stderr_tail(sid, secrets=secrets, since=began)
            text = line if not tail else f"{line}\n{tail}"
            return StartResult("failed", last_error=spawn_env.mask(text, secrets)[:LAST_ERROR_CAP])
        return StartResult("ready", tools=tools, tool_count=len(tools))

    async def _ensure_runtime(self, sid: int, server: dict) -> bool:
        """Arslan's pinned Node/uv for a bare npx/node/npm/uvx/uv (spec §B1). Never inside a start
        budget. When the command is on the user's PATH, the start goes on now and the runtime is
        fetched in the background for next time; otherwise it is fetched now (≤ RUNTIME_FETCH_S).
        Any failure falls back to the user's PATH (ruling 8). True when it was fetched now."""
        from server.services import capability_runtime

        self._fetch_error.pop(sid, None)
        if (server.get("transport") or "stdio") == "http" or server.get("sandbox"):
            return False
        command = str(server.get("command") or "")
        runtime = spawn_env.runtime_for(command)
        if runtime is None or capability_runtime.ready(runtime):
            return False
        try:
            await asyncio.to_thread(spawn_env.resolve_command, command)
            on_path = True
        except FileNotFoundError:
            on_path = False
        if on_path:
            if self.running:
                self._spawn_bg(self._fetch_quietly(runtime))
            return False
        pin = capability_runtime.PINS[runtime]
        self._notes[sid] = (f"downloading {'Node' if runtime == 'node' else 'uv'} {pin.version} "
                            f"({pin.size_mb} MB)")
        try:
            await within(capability_runtime.ensure(runtime), RUNTIME_FETCH_S)
            return True
        except Exception as exc:  # noqa: BLE001 — RuntimeFailure, TimeoutError, anything (ruling 8)
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise asyncio.CancelledError() from exc   # a cancel wait_for swallowed (3.11)
            self._fetch_error[sid] = getattr(exc, "code", None) or type(exc).__name__
            logger.warning("mcp %s: could not fetch %s: %s", sid, runtime, exc)
            return False

    async def _fetch_quietly(self, runtime: str) -> None:
        from server.services import capability_runtime

        try:
            await within(capability_runtime.ensure(runtime), RUNTIME_FETCH_S)
        except Exception as exc:  # noqa: BLE001 — next time, from the user's PATH again
            logger.info("mcp: background fetch of %s failed: %s", runtime, exc)

    async def _settle(self, sid: int, gen: int, result: StartResult) -> StartResult:
        if result.state == "starting":          # an overtaken open: whoever dropped it restarts it
            return result
        if result.state == "off":
            await self._set(sid, gen, "off")
            return result
        if result.state == "ready":
            self._ready_since[sid] = time.monotonic()
            self._fetch_error.pop(sid, None)
            self._cold.discard(sid)                 # an edit's cold start is done
            await self._set(sid, gen, "ready", ok=True)
            if sid in self._relist_wanted:
                self._relist_wanted.discard(sid)
                self._schedule_relist(sid)
            return result
        self._ready_since.pop(sid, None)
        retry_in = PROBE_EVERY_S if result.state in ("parked", "needs_auth") else None
        result.next_retry_at = await self._set(sid, gen, result.state, error=result.last_error,
                                               retry_in=retry_in)
        return result

    async def _set(self, sid: int, gen: int, state: str, *, error: str | None = None, ok: bool = False,
                   retry_in: float | None = None) -> datetime | None:
        """The one writer of `state`. One short transaction; a no-op for a superseded generation or
        a vanished row — also one deleted between the read and the write (final review M-3).
        last_error changes only with an error or on ready (then it is cleared). fail_count counts
        failed plans; a failed server's next try backs off 30 s → 600 s."""
        async with self._set_locks.hold(sid):
            return await self._set_locked(sid, gen, state, error=error, ok=ok, retry_in=retry_in)

    async def _set_locked(self, sid: int, gen: int, state: str, *, error: str | None, ok: bool,
                          retry_in: float | None) -> datetime | None:
        if self._gen.get(sid, 0) != gen:
            return None
        now = _utcnow()
        try:
            async with db_session.AsyncSessionLocal() as db:
                row = await db.get(MCPServer, sid)
                if row is None:
                    return None
                row.state, row.state_at = state, now
                if state in LEGACY_STATUS:
                    row.status = LEGACY_STATUS[state]
                if state in LEGACY_HEALTH:
                    row.health_status, row.last_checked_at = LEGACY_HEALTH[state], now
                if ok:
                    row.last_ok_at, row.last_error, row.fail_count, row.next_retry_at = now, None, 0, None
                elif error is not None:
                    row.last_error = error
                if state in ("failed", "parked", "needs_auth"):
                    row.fail_count = (row.fail_count or 0) + 1
                    if retry_in is None:
                        retry_in = min(RETRY_BASE_S * 2 ** (row.fail_count - 1), RETRY_CAP_S)
                    row.next_retry_at = now + timedelta(seconds=retry_in)
                elif state in ("starting", "off"):
                    row.next_retry_at = None
                next_at = row.next_retry_at
                await db.commit()
            return next_at
        except StaleDataError:              # the UPDATE matched no row: deleted meanwhile
            return None

    async def _write_ok(self, sid: int) -> None:
        async with db_session.AsyncSessionLocal() as db:
            await db.execute(update(MCPServer).where(MCPServer.id == sid, MCPServer.state == "ready")
                             .values(last_ok_at=_utcnow()))
            await db.commit()

    # ── hooks from the session manager (sync; they only schedule) ──────────────────────
    def _on_dropped(self, server_id: int, exc: BaseException) -> None:
        """A call lost its session. A real drop counts toward MAX_RECONNECTS; any other call
        failure that closed the session restarts uncounted (ruling 11)."""
        if not self.running:
            return
        self._ready_since.pop(server_id, None)
        if mcp_session.is_dropped_error(exc):
            count = self._reconnects[server_id] = self._reconnects.get(server_id, 0) + 1
            if count > MAX_RECONNECTS:
                self._spawn_bg(self._give_up(server_id))
                return
        self.schedule(server_id, fresh=True)

    async def _give_up(self, server_id: int) -> None:
        with self._verb(server_id):
            gen = self._bump(server_id)      # first, like forget/set_enabled(off): a re-list the
            await self._cancel_plan(server_id)   # drop below wakes sees a deliberate drop (M-5)
            self._reconnects.pop(server_id, None)
            try:
                async with db_session.AsyncSessionLocal() as db:
                    row = await db.get(MCPServer, server_id)
                secrets = _secrets(discovery.runtime_dict(row)) if row is not None else []
                line = f"{GAVE_UP_LINE} ({MAX_RECONNECTS} reconnects) — Arslan retries it later"
                tail = mcp_session.manager.stderr_tail(server_id, secrets=secrets)
                text = line if not tail else f"{line}\n{tail}"
                # The state before the drop: a call the drop wakes reads why it was cut — the
                # supervisor gave up for now — never "restarting" (Task 7 re-review).
                await self._set(server_id, gen, "failed",
                                error=spawn_env.mask(text, secrets)[:LAST_ERROR_CAP])
            finally:
                # Always, even if the write failed — unless a newer plan has started meanwhile: its
                # attempt drops the old session itself, and this drop must not kill its new one (N12).
                if self._gen.get(server_id, 0) == gen:
                    await mcp_session.manager.drop(server_id)

    def _on_tools_changed(self, server_id: int) -> None:
        if not self.running:
            return
        if server_id in self._attempt_fut:
            self._relist_wanted.add(server_id)     # the attempt is listing now; re-list after it
            return
        self._schedule_relist(server_id)

    def _schedule_relist(self, server_id: int) -> None:
        if not self.running or server_id in self._relisting:
            return
        self._relisting.add(server_id)
        self._spawn_bg(self._relist(server_id))

    async def _relist(self, server_id: int) -> None:
        gen = None
        try:
            await asyncio.sleep(RELIST_DEBOUNCE_S)
            if server_id in self._attempt_fut:
                self._relist_wanted.add(server_id)
                return
            gen = self._gen.get(server_id, 0)
            await discovery.relist(server_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("mcp %s: re-list after tools/list_changed failed: %s", server_id, exc)
            # A failed page (CONNECTION_CLOSED, ListTimeout, ...) has already dropped the session
            # it ran on, and list_tools never calls on_dropped: this caller saw the drop, so it
            # restarts the server (carry 2c; counted only for a real drop, ruling 11). Not when
            # the session is still there (a database error); not while a start runs (that start
            # dropped the session itself, which ended this re-list, and is the fresh one); and
            # not when the generation moved (forget, switch-off, give-up or a new plan dropped
            # it on purpose: a deliberate drop is not the server dying).
            if (mcp_session.manager.cached(server_id) is None
                    and server_id not in self._attempt_fut
                    and self._gen.get(server_id, 0) == gen):
                self._on_dropped(server_id, exc)
        finally:
            self._relisting.discard(server_id)

    # ── the periodic loop ──────────────────────────────────────────────────────────────
    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(LOOP_TICK_S)
            try:
                await self._tick()
            except Exception:  # noqa: BLE001 — one bad tick never stops the loop
                logger.warning("mcp supervisor tick failed", exc_info=True)

    async def _still(self, sid: int, states: tuple, gen: int) -> bool:
        """At act time, is the tick's candidate still what its snapshot said? No deliberate verb
        acts on it now, nothing moved its generation since the snapshot (a verb that came and went
        while the tick read, a plan created meanwhile), and its row, read again, is still in
        `states` (a plan that finished between the tick's read and now has its own answer)."""
        if sid in self._busy or self._gen.get(sid, 0) != gen:
            return False
        async with db_session.AsyncSessionLocal() as db:
            row = await db.get(MCPServer, sid)
        return (row is not None and row.state in states and sid not in self._busy
                and self._gen.get(sid, 0) == gen)

    async def _tick(self) -> None:
        now = _utcnow()
        gens = dict(self._gen)            # before the reads: whatever acts after them moves these
        async with db_session.AsyncSessionLocal() as db:
            due = (await db.execute(select(MCPServer.id, MCPServer.state).where(
                MCPServer.host_allowed.is_(True),
                MCPServer.state.in_(("failed", "parked", "needs_auth")),
                MCPServer.next_retry_at.is_not(None),
                MCPServer.next_retry_at <= now))).all()
            # A `starting` row whose plan is gone (a plan that crashed in its own writes, a boot
            # that failed before start_all, an overtaken open nobody restarted) would wait for the
            # next launch. Switched-off rows too: `refresh` respects the switch and ends them `off`.
            stale = (await db.execute(select(MCPServer.id).where(
                MCPServer.state == "starting",
                or_(MCPServer.state_at.is_(None),             # inserted, never started
                    MCPServer.state_at <= now - timedelta(seconds=STARTING_STALE_S))))).scalars().all()
            # A `ready` row with no live session behind it and no start on its way is dead (Task 7):
            # its session vanished without a drop callback (a cancelled health probe's listing
            # dropped it), or it is the last run's `ready` (a failed boot reset). Switched-off rows
            # too: `refresh` respects the switch and ends them `off`.
            ready = (await db.execute(select(MCPServer.id).where(
                MCPServer.state == "ready").order_by(MCPServer.id))).scalars().all()
            # A switched-on server is never left `off`: the user's switch-on committed host_allowed,
            # then its `starting` write failed (a locked database) — nothing else ever looks at an
            # `off` row (Task 7 review M-3). Only once it has been `off` for STARTING_STALE_S (or
            # was never stamped), like a stale `starting`: a switch-off whose host_allowed commit
            # lands after its `off` write is never started behind its back. A cached session is no
            # reason to wait.
            off_long_enough = or_(MCPServer.state_at.is_(None),
                                  MCPServer.state_at <= now - timedelta(seconds=STARTING_STALE_S))
            still_off = (await db.execute(
                select(MCPServer.id)
                .where(MCPServer.state == "off", MCPServer.host_allowed.is_(True), off_long_enough)
                .order_by(MCPServer.id))).scalars().all()
        for sid, state in due:
            if not await self._still(sid, (state,), gens.get(sid, 0)):    # a verb, a plan, moved on
                continue
            task = self._inflight.get(sid)
            if task is None or task.done():
                self._new_plan(sid, "retry" if state == "failed" else "probe")
        for sid in stale:
            if not await self._still(sid, ("starting",), gens.get(sid, 0)):
                continue
            task = self._inflight.get(sid)
            if task is None or task.done():
                logger.warning("mcp %s: starting with no plan for %g s; restarting it", sid,
                               STARTING_STALE_S)
                self._new_plan(sid, "refresh")
        for sid in ready:
            task = self._inflight.get(sid)
            if (mcp_session.manager.cached(sid) is not None or self.start_in_flight(sid)
                    or (task is not None and not task.done())):
                continue                          # alive, or a start (queued or running) is on its way
            if await self._still(sid, ("ready",), gens.get(sid, 0)):
                logger.warning("mcp %s: ready with no live session; restarting it", sid)
                self.schedule(sid, fresh=True)
        for sid in still_off:
            task = self._inflight.get(sid)
            if self.start_in_flight(sid) or (task is not None and not task.done()):
                continue                          # its start (queued or running) writes the state
            if await self._still(sid, ("off",), gens.get(sid, 0)):
                logger.warning("mcp %s: switched on but still off; starting it", sid)
                self.schedule(sid, fresh=True)
        mono = time.monotonic()
        for sid, since in list(self._ready_since.items()):
            if mono - since >= RECONNECT_RESET_S:
                self._reconnects.pop(sid, None)
            await asyncio.to_thread(mcp_session.cap_log, mcp_session.log_path(sid),
                                    limit=LIVE_LOG_CAP_BYTES)


supervisor = Supervisor()   # process-level singleton

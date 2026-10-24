"""Proxy executor: routes one MCP tool call through the session manager. MCP output is
UNTRUSTED external content → result carries NO external:False, so tool_loop wrap_externals it.

0.1.61 §B1: a server that is not `ready` is never called — the result names its state and reason
(`mcp_not_ready`, a known failure: the call never left Arslan). A call never starts a process: with
no live session it schedules a start and says so; a session that drops during the call is restarted
in the background (`mcp_dropped`, outcome unknown) — unless the user switched the server off or
removed it, which the answer then says (Task 7 review M-1). The whole call, its send included, is
bounded (`CALL_BOUND_S`); a call stuck past it gets its session replaced (review M-2).

0.1.61 §B1 (Task 6 fix round 1, F3): a failure's text — the tool's own error or a failed call —
has the server's own secrets masked (`supervisor.mask_for`) before it is stored in last_error and
before the model reads it: a tool that echoes its key never puts it in the column the UI serves,
nor in a tool result. It masks, then cuts (fix round 2, N-4): a key straddling a cut is masked
whole, never left with its head in the text."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

import httpx
from mcp.shared.exceptions import McpError
from sqlalchemy import update

from server.db import session as db_session
from server.db.models import MCPServer, Tool
from server.mcp.session import CALL_TIMEOUT_S, NotStarted, is_dropped_error, manager
from server.services.approvals import TIMEOUT_S as CARD_S

logger = logging.getLogger(__name__)

_STORED_ERROR_CAP = 500   # chars of upstream error text kept in mcp_servers.last_error
_SUMMARY_CAP = 6000       # chars of a tool's text handed to the model

#: The whole call, its send included (Task 7 review M-2). mcp 1.28.1 bounds only the wait for the
#: answer (`read_timeout_seconds`, CALL_TIMEOUT_S, raised as McpError 408) and awaits the send outside
#: it, so a send blocked on a full stdio pipe would wait for ever. A little past the SDK's own
#: timeout, which fires first once the request is out; the tool loop's `timeout_s` is a backstop.
CALL_BOUND_S = CALL_TIMEOUT_S + 5.0

#: Closes of replaced sessions still running (strong references: the event loop keeps only weak ones).
_CLOSING: set[asyncio.Task] = set()

_STATE_WORDS = {"starting": "still starting", "failed": "failing to start",
                "parked": "stopped until it is fixed", "needs_auth": "waiting for the user to sign in",
                "off": "switched off"}      # not "by the user": an install whose test failed is left off


def _answered(st: str, host_allowed: bool) -> str:
    """A `ready` with no live session, and a switched-on row that still says `off` (its `starting`
    write has not landed, or failed: the tick starts it), are still starting (Task 7 review I-1, M-3)."""
    if st == "ready" or (st == "off" and host_allowed):
        return "starting"
    return st


def answer_state(srv, state: str | None = None) -> str:
    """The state a call or the model is told for a server that is not ready in this process."""
    return _answered(state or srv.state or "starting", bool(srv.host_allowed))


def shown_state(server_id: int, state: str | None, host_allowed: bool) -> str:
    """The one state a server is shown in (`list_my_capabilities`), decided once: `ready` only for a
    switched-on server that is ready in this process (`supervisor.ready_now`); `off` while the user's
    switch is off — the host is refused before the supervisor has written `off`; otherwise the state a
    call to it is answered with."""
    from server.mcp.supervisor import ready_now
    if not host_allowed:
        return "off"
    if ready_now(server_id, state):
        return "ready"
    return _answered(state or "starting", True)


def label_of(srv) -> str:
    """A server's name as the prompt prints it: one line, cut."""
    return " ".join(str(srv.label or f"MCP {srv.id}").split())[:80]


def status_clauses(servers) -> list[str]:
    """One clause per server that is not ready in this process (`supervisor.ready_now`), in Arslan's
    own words for the system prompt: the state as a call to it is answered (`state_words`), never a raw
    state word, and a reason only when it is in the supervisor's vocabulary (`safe_reason`, ruling 6).
    The host's status line and a spawn's share it (Task 8 fix round 1)."""
    from server.mcp.supervisor import ready_now, safe_reason, supervisor
    clauses = []
    for srv in servers:
        if ready_now(srv.id, srv.state):
            continue
        state = answer_state(srv)
        words = state_words(srv, state)
        if state == "starting":
            note = supervisor.note(srv.id)
            clauses.append(f"{label_of(srv)}: {words}" + (f" ({note})" if note else ""))
            continue
        reason = safe_reason(srv.last_error)
        clauses.append(f"{label_of(srv)}: {words}" + (f" — {reason}" if reason else ""))
    return clauses


def masked_error(srv, text: str | None = None) -> str | None:
    """`text` (by default the row's own `last_error`) with the server's own secrets masked over the
    WHOLE text — the one helper every reader that shows a stored `last_error` goes through, to the
    model, the UI or the API, before it takes a line or cuts anything (final review I-2). A row
    written before 0.1.61 stored the upstream text as is (httpx puts a URL's `?key=` in it), and a
    switched-off server keeps its `last_error` for ever; 0.1.61's writers mask already, and masking
    twice changes nothing. Never raises (`mask_for`)."""
    text = srv.last_error if text is None else text
    if not text:
        return text
    from server.mcp.discovery import runtime_dict
    from server.mcp.supervisor import mask_for
    return mask_for(runtime_dict(srv), text)


def first_error_line(srv, text: str | None = None) -> str:
    """`masked_error`'s first line, cut to 200 characters: masked first, cut second, so a key
    straddling the cut is masked whole (Task 8 review M-5)."""
    return (masked_error(srv, text) or "").split("\n", 1)[0].strip()[:200]


async def error_line(server_id: int, text: str | None) -> str:
    """`first_error_line` for a server known by its id (the row is read for its secrets)."""
    if not (text or "").strip():
        return ""
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(MCPServer, server_id)
    if row is None:
        return ""
    return first_error_line(row, text)


def rechecks_key(last_error: str | None, env) -> bool:
    """Whether a `needs_auth` server is asked to re-check its key or header (True) or to sign in
    (False). A server with a key or header re-checks it; a saved sign-in that expired (OAuth:
    "authorization needed: … use Authorize") is a sign-in, even for an http server that also sends
    headers (Task 7 re-review R5). One rule for the status line, a call's answer and the capability
    list's `fix` (Task 8)."""
    from server.mcp.supervisor import SIGN_IN_PREFIX
    return bool(env) and not (last_error or "").startswith(SIGN_IN_PREFIX)


def state_words(srv, st: str) -> str:
    """Arslan's words for a not-ready state; a call's answer and the status line say the same, and
    never a raw state word (Task 7 review M-3). A server with a key or header is asked to re-check it
    (`fix_for`'s fix), never to sign in (`rechecks_key`); one the supervisor gave up on after its
    reconnects is unstable, not failing to start."""
    from server.mcp.supervisor import GAVE_UP_LINE
    if st == "needs_auth":
        from server.mcp.discovery import runtime_dict
        if rechecks_key(srv.last_error, runtime_dict(srv).get("env")):
            return "waiting for the user to re-check its key/token"
    if st == "failed" and (srv.last_error or "").startswith(GAVE_UP_LINE):
        return "unstable"
    return _STATE_WORDS.get(st, "not available")


def not_ready_result(srv, *, state: str | None = None) -> dict:
    """The answer for a call to a server that is not ready: its state and the classified line.
    A tool result (wrapped as external content by the tool loop), so the line may be raw — but never
    the server's own secrets (`first_error_line`)."""
    from server.mcp.supervisor import supervisor
    st = answer_state(srv, state)
    if st == "starting":
        note = supervisor.note(srv.id)
        detail = f" ({note})" if note else ""
        text = f"MCP '{srv.label}' is {state_words(srv, st)}{detail}. It was not called."
    else:
        reason = first_error_line(srv) if st != "off" else ""      # masked, then cut (fix B)
        text = (f"MCP '{srv.label}' is {state_words(srv, st)}" + (f": {reason}" if reason else "")
                + ". It was not called.")
    return {"ok": False, "code": "mcp_not_ready", "state": st, "error": text}


async def not_ready_for_key(tool_key: str) -> dict | None:
    """The state answer for an mcp_* key whose server is switched on but not ready in this process
    (`supervisor.ready_now`: no live session behind a `ready`, or any other state); None when the
    tool or server is unknown, switched off (then `tool_unavailable` is the truth) or ready."""
    from server.mcp.supervisor import ready_now
    async with db_session.AsyncSessionLocal() as db:
        tool = await db.get(Tool, tool_key)
        if tool is None or not (tool.toolset_key or "").startswith("mcp_"):
            return None
        try:
            server_id = int(tool.toolset_key.split("_", 1)[1])
        except (ValueError, IndexError):
            return None
        srv = await db.get(MCPServer, server_id)
    if srv is None or not srv.host_allowed or ready_now(srv.id, srv.state):
        return None
    return not_ready_result(srv)


def _summarize_content(content, *, cap: int | None = _SUMMARY_CAP) -> str:
    """The tool's text blocks, joined; cut to `cap` (None: uncut — an error text is masked first)."""
    parts = [t for t in (getattr(b, "text", None) for b in (content or [])) if t]
    text = "\n".join(parts)
    return (text if cap is None else text[:cap]) or "(no text content)"


async def _persist_last_error(server_id: int, err: str | None) -> None:
    """Record the latest failure (or clear it on success) in mcp_servers.last_error.
    Fail-open: a persistence problem is logged and never masks the tool result."""
    try:
        async with db_session.AsyncSessionLocal() as db:
            await db.execute(update(MCPServer).where(MCPServer.id == server_id)
                             .values(last_error=err))
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("mcp: could not persist last_error for server %s", server_id,
                       exc_info=True)


class MCPProxyExecutor:
    # The tool loop's backstop. S1: a call may first wait on its card (approvals.TIMEOUT_S), as Hands'
    # do; then 130 s, which CALL_BOUND_S ends first for a stuck call (0.1.61 §B1).
    timeout_s = CARD_S + 130

    def __init__(self, server_id: int, external_name: str, *, key: str | None = None,
                 annotations: dict | None = None) -> None:
        from server.mcp.discovery import mcp_tool_key
        self.server_id = server_id
        self.external_name = external_name
        # The row's own key: names over 50 characters are hashed in it (mcp_tool_key).
        self.key = key or mcp_tool_key(server_id, external_name)
        self.annotations = annotations      # the hints the server declared (S1)

    async def _fail(self, err_text: str, prefix: str, server: dict) -> dict:
        from server.mcp.supervisor import mask_for

        err_text = mask_for(server, err_text)[:_SUMMARY_CAP]     # never raises; masked, then cut
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        await _persist_last_error(
            self.server_id,
            f"{stamp} call_tool {self.external_name}: {err_text[:_STORED_ERROR_CAP]}")
        # 条件1: the upstream error body is EXTERNAL content. tool_loop's
        # _record_tool_result serializes the WHOLE result dict and wrap_external's it
        # unless external is False — the "error" field gets the exact same framing as
        # "summary" (per-result, not per-field). That granularity means the trusted
        # [MCP label · transport] prefix cannot sit outside the wrapped region, so the
        # entire enriched string lives inside the EXTERNAL_WEB_CONTENT frame. We keep
        # NO external:False here so that framing applies.
        return {"ok": False, "error": prefix + err_text}

    async def _approve(self, srv: MCPServer, args: dict) -> dict | None:
        """S1 (R6): decided here, before the call leaves Arslan, by what the server says the tool does:
        read-only runs (one ledger row, the mode let it); destructive asks every time, this time only;
        anything else asks, this time or for this conversation. With nobody to ask (a scheduled run)
        only read-only runs: the check above comes first (⓪Plan (i)). None means go ahead; otherwise
        the refusal, which never reached the server (`executed: False`) and is Arslan's own words."""
        from server.mcp.discovery import destructive, read_only
        from server.services import background_jobs, permissions, personal_context
        from server.ws import protocol
        detail = json.dumps(args or {}, ensure_ascii=False)
        target = f"{srv.label}/{self.external_name}"
        current = personal_context.current()
        ctx = permissions.Context(current.conversation_id if current else None,
                                  job_id=background_jobs._inside_job.get())
        title = f"Use {srv.label}\u2019s {self.external_name}?"
        extra = {"mcp_server": srv.label, "mcp_tool": self.external_name}
        if read_only(self.annotations):
            await permissions.record_standing(permissions.Request(
                kind="mcp_tool", target=self.key, title=title, detail=detail, extra=extra), ctx, by="mode")
            return None
        if len(detail) > protocol.DETAIL_MAX:
            # ⓪Plan's review: a card shows at most DETAIL_MAX characters, so padding could push the real
            # target off it and the yes would cover arguments nobody saw. Refused, never cut (not even
            # under a grant: every call that is not read-only has arguments a card can show in full).
            return {"ok": False, "external": False, "executed": False, "code": "too_long_to_show",
                    "error": f"Not sent: the arguments of {srv.label}\u2019s {self.external_name} are "
                             f"{len(detail)} characters, more than a card can show the user "
                             f"({protocol.DETAIL_MAX}). Make smaller calls, or tell the user what you needed."}
        frame = protocol.propose_action(uuid.uuid4().hex, "mcp_tool", target, detail)
        if destructive(self.annotations):     # red on the web, never from the island, "delete" on the phone
            req = permissions.Request(kind="destructive", target=self.key, title=title, detail=detail,
                                      once_only=True, extra=extra, frame=frame)
        else:
            req = permissions.Request(kind="mcp_tool", target=self.key, title=title, detail=detail,
                                      extra=extra, frame=frame)
        decision = await permissions.decide(req, ctx)        # with nobody to ask: refused by policy (U14 a)
        if decision.allowed:
            return None
        code = {"user": "declined", "expired": "no_answer", "policy": "no_one_to_ask"}.get(decision.by, "not_allowed")
        error = (f"The user did not allow {srv.label}\u2019s {self.external_name}."
                 f"{' They said: ' + decision.note if decision.note else ''} Do not retry; report it."
                 if decision.by == "user" else decision.model_text or f"{title} was not allowed.")
        return {"ok": False, "external": False, "executed": False, "code": code, "error": error}

    async def execute(self, args: dict) -> dict:
        async with db_session.AsyncSessionLocal() as db:
            srv = await db.get(MCPServer, self.server_id)
        if srv is None:
            return {"ok": False, "error": f"MCP server {self.server_id} not found"}
        if srv.state != "ready":
            return not_ready_result(srv)
        try:
            refused = await self._approve(srv, args)
        except Exception:  # noqa: BLE001 — a failed check is a refusal that never reached the server
            logger.warning("mcp approval failed for %s", self.key, exc_info=True)
            refused = {"ok": False, "external": False, "executed": False, "code": "not_allowed",
                       "error": f"Not sent: Arslan could not check whether {srv.label}\u2019s "
                                f"{self.external_name} may run. Tell the user."}
        if refused is not None:
            return refused
        from server.mcp.discovery import runtime_dict
        from server.mcp.supervisor import supervisor
        server = runtime_dict(srv)
        prefix = f"[MCP {srv.label} · {server.get('transport') or 'stdio'}] "
        session = manager.cached(self.server_id)        # the session the call below runs on
        try:
            async with asyncio.timeout(CALL_BOUND_S) as bound:
                result = await manager.call_tool(server, self.external_name, args or {})
        except NotStarted:
            supervisor.schedule(self.server_id)            # never waits (spec §B1)
            return not_ready_result(srv, state="starting")
        except TimeoutError as exc:
            if not bound.expired():                        # raised inside the call: an ordinary failure
                return await self._fail(f"MCP tool '{self.external_name}' failed: {exc}", prefix, server)
            # Stuck past the SDK's own timeout (a send that never went out): the session that hung
            # is replaced — the fresh start first, then the drop (every verb's order: the generation
            # has moved before the drop wakes anyone), and only while it is still the cached one (a
            # newer session is a start's healthy one). The drop is not awaited: it pops the session
            # and wakes its callers at its first step, and its close (an SDK stdio close may take
            # ~4 s, an http one sends a DELETE) never eats the bound→backstop margin, nor is it cut
            # if this turn is (re-review N-2).
            if session is not None and manager.cached(self.server_id) is session:
                supervisor.schedule(self.server_id, fresh=True)
                closing = asyncio.ensure_future(manager.drop(self.server_id))
                _CLOSING.add(closing)
                closing.add_done_callback(_CLOSING.discard)
            return await self._fail(
                f"MCP tool '{self.external_name}' timed out after {CALL_BOUND_S:g} s", prefix, server)
        except Exception as exc:  # noqa: BLE001
            if is_dropped_error(exc):
                # A death: the manager already told the supervisor, which restarts it. A drop the
                # user caused — switched off, removed — restarts nothing, and a give-up retries
                # later (it writes `failed` before it drops); the answer says which.
                from server.mcp.supervisor import GAVE_UP_LINE
                async with db_session.AsyncSessionLocal() as db:
                    now = await db.get(MCPServer, self.server_id)
                if now is None:
                    why = "it was removed"
                elif not now.host_allowed:
                    why = "the user switched it off"
                elif now.state == "failed" and (now.last_error or "").startswith(GAVE_UP_LINE):
                    why = "it is unstable: it keeps dropping its connection, and Arslan retries it later"
                else:
                    why = "Arslan is restarting it"
                return {"ok": False, "code": "mcp_dropped", "error": prefix + (
                    f"MCP '{srv.label}' lost its connection during this call; {why}. Whether the "
                    "call ran is unknown.")}
            if isinstance(exc, McpError) and exc.error.code == httpx.codes.REQUEST_TIMEOUT:
                return await self._fail(
                    f"MCP tool '{self.external_name}' timed out after {CALL_TIMEOUT_S:g} s", prefix, server)
            return await self._fail(f"MCP tool '{self.external_name}' failed: {exc}", prefix, server)
        supervisor.note_ok(self.server_id)
        content = getattr(result, "content", None)
        if getattr(result, "isError", False):
            return await self._fail(_summarize_content(content, cap=None), prefix, server)
        text = _summarize_content(content)
        if srv.last_error is not None:            # column reflects the LATEST state
            await _persist_last_error(self.server_id, None)
        return {"ok": True, "summary": text}      # no external:False → wrap_external applies


async def build_mcp_executor(tool_key: str):
    """Resolve an mcp_* Tool key → MCPProxyExecutor, or None if not an MCP tool / not found."""
    async with db_session.AsyncSessionLocal() as db:
        tool = await db.get(Tool, tool_key)
    if tool is None or not (tool.toolset_key or "").startswith("mcp_"):
        return None
    try:
        server_id = int(tool.toolset_key.split("_", 1)[1])
    except (ValueError, IndexError):
        return None
    return MCPProxyExecutor(server_id=server_id, external_name=tool.external_name or "", key=tool.key,
                            annotations=tool.annotations)

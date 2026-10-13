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
import logging
from datetime import datetime, timezone

import httpx
from mcp.shared.exceptions import McpError
from sqlalchemy import update

from server.db import session as db_session
from server.db.models import MCPServer, Tool
from server.mcp.session import CALL_TIMEOUT_S, NotStarted, is_dropped_error, manager

logger = logging.getLogger(__name__)

_STORED_ERROR_CAP = 500   # chars of upstream error text kept in mcp_servers.last_error
_SUMMARY_CAP = 6000       # chars of a tool's text handed to the model

#: The whole call, its send included (Task 7 review M-2). mcp 1.28.1 bounds only the wait for the
#: answer (`read_timeout_seconds`, CALL_TIMEOUT_S, raised as McpError 408) and awaits the send outside
#: it, so a send blocked on a full stdio pipe would wait for ever. A little past the SDK's own
#: timeout, which fires first once the request is out; the tool loop's `timeout_s` is a backstop.
CALL_BOUND_S = CALL_TIMEOUT_S + 5.0

_STATE_WORDS = {"starting": "still starting", "failed": "failing to start",
                "parked": "stopped until it is fixed", "needs_auth": "waiting for the user to sign in",
                "off": "switched off by the user"}


def answer_state(srv, state: str | None = None) -> str:
    """The state a call or the model is told for a server that is not ready in this process. A
    `ready` with no live session, and a switched-on row that still says `off` (its `starting` write
    has not landed, or failed: the tick starts it), are still starting (Task 7 review I-1, M-3)."""
    st = state or srv.state or "starting"
    if st == "ready" or (st == "off" and srv.host_allowed):
        return "starting"
    return st


def state_words(srv, st: str) -> str:
    """Arslan's words for a not-ready state; a call's answer and the status line say the same, and
    never a raw state word (Task 7 review M-3). A server with a key or header is asked to re-check it
    (`fix_for`'s fix), never to sign in; one the supervisor gave up on after its reconnects is
    unstable, not failing to start."""
    from server.mcp.supervisor import GAVE_UP_LINE
    if st == "needs_auth":
        from server.mcp.discovery import runtime_dict
        if runtime_dict(srv).get("env"):
            return "waiting for the user to re-check its key/token"
    if st == "failed" and (srv.last_error or "").startswith(GAVE_UP_LINE):
        return "unstable"
    return _STATE_WORDS.get(st, "not available")


def not_ready_result(srv, *, state: str | None = None) -> dict:
    """The answer for a call to a server that is not ready: its state and the classified line.
    A tool result (wrapped as external content by the tool loop), so the line may be raw."""
    from server.mcp.supervisor import supervisor
    st = answer_state(srv, state)
    if st == "starting":
        note = supervisor.note(srv.id)
        detail = f" ({note})" if note else ""
        text = f"MCP '{srv.label}' is {state_words(srv, st)}{detail}. It was not called."
    else:
        reason = (srv.last_error or "").split("\n", 1)[0].strip()[:200] if st != "off" else ""
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
    timeout_s = 130   # the tool loop's backstop: CALL_BOUND_S ends a stuck call first (0.1.61 §B1)

    def __init__(self, server_id: int, external_name: str) -> None:
        self.server_id = server_id
        self.external_name = external_name
        self.key = f"mcp_{server_id}__{external_name}"

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

    async def execute(self, args: dict) -> dict:
        async with db_session.AsyncSessionLocal() as db:
            srv = await db.get(MCPServer, self.server_id)
        if srv is None:
            return {"ok": False, "error": f"MCP server {self.server_id} not found"}
        if srv.state != "ready":
            return not_ready_result(srv)
        from server.mcp.discovery import runtime_dict
        from server.mcp.supervisor import supervisor
        server = runtime_dict(srv)
        prefix = f"[MCP {srv.label} · {server.get('transport') or 'stdio'}] "
        session = manager.cached(self.server_id)        # the session the call below runs on
        try:
            async with asyncio.timeout(CALL_BOUND_S):
                result = await manager.call_tool(server, self.external_name, args or {})
        except NotStarted:
            supervisor.schedule(self.server_id)            # never waits (spec §B1)
            return not_ready_result(srv, state="starting")
        except TimeoutError:
            # Stuck past the SDK's own timeout (a send that never went out): the session that hung
            # is replaced — the fresh start first, then the drop (every verb's order: the generation
            # has moved before the drop wakes anyone), and only while it is still the cached one (a
            # newer session is a start's healthy one). The drop finishes even if this turn is cut.
            if session is not None and manager.cached(self.server_id) is session:
                supervisor.schedule(self.server_id, fresh=True)
                await asyncio.shield(manager.drop(self.server_id))
            return await self._fail(
                f"MCP tool '{self.external_name}' timed out after {CALL_BOUND_S:g} s", prefix, server)
        except Exception as exc:  # noqa: BLE001
            if is_dropped_error(exc):
                # A death: the manager already told the supervisor, which restarts it. A drop the
                # user caused — switched off, removed — restarts nothing, and the answer says so.
                async with db_session.AsyncSessionLocal() as db:
                    now = await db.get(MCPServer, self.server_id)
                why = ("it was removed" if now is None else "the user switched it off"
                       if not now.host_allowed else "Arslan is restarting it")
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
    return MCPProxyExecutor(server_id=server_id, external_name=tool.external_name or "")

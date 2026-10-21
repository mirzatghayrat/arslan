"""Connect an MCP server, discover its tools, naturalize them into Tool/Toolset rows
(locked: tier=orchestrator/status=registered). suggest_tier is a derived UI hint only.

0.1.61 §B1/§B4: tools follow the server — every listing (all pages, at most MAX_PAGES) adds new
tools, updates changed ones, prunes vanished ones and stores each tool's declared hints. All pages
are fetched before any database session opens, and one server's listings are serialized (the
listing and its write run under one lock, so a newer snapshot is never overwritten by an older
one). A re-list uses the live session as it is and never opens or restarts one."""
from __future__ import annotations

import httpx
import hashlib
import json
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from server.db import session as db_session
from server.db.models import MCPServer, Tool, Toolset
from server.mcp.session import CONTROL_CHARS, LoopLocks, NotStarted, manager

logger = logging.getLogger(__name__)

_READ_VERBS = ("list", "get", "search", "read", "fetch", "query", "find", "describe", "show", "view")
_WRITE_VERBS = ("write", "create", "delete", "update", "exec", "run", "send", "patch", "move", "install", "remove", "set")


def suggest_tier(tool_name: str) -> str:
    n = (tool_name or "").lower()
    if any(n.startswith(v) or f"_{v}" in n for v in _WRITE_VERBS):
        return "orchestrator"
    if any(n.startswith(v) or f"_{v}" in n for v in _READ_VERBS):
        return "safe"
    return "orchestrator"           # unknown → conservative



def suggested_tier_for(srv, tool_name: str) -> str:
    """The tier hint for one tool of one server.

    A HAND-GRADED table wins over the heuristic, because the heuristic is a
    verb-list and some servers do not speak in those verbs. Playwright is the
    worked example: not one of snapshot / click / navigate / type appears in
    either list, so every tool — including the purely observational ones —
    comes back "orchestrator", and a toolset with no safe tool cannot be
    assigned to a spawn at all. Grading by hand is not a shortcut around the
    conservative default; it is the only way to distinguish "we looked and this
    one only reads" from "nothing matched a pattern".
    """
    from server.mcp.catalog import manual_tier

    return manual_tier(getattr(srv, "args", None), tool_name) or suggest_tier(tool_name)


def mcp_tool_key(server_id: int, name: str) -> str:
    """Namespaced, length-guarded (Tool.key is VARCHAR(50)). Original name lives in external_name."""
    key = f"mcp_{server_id}__{name}"
    if len(key) <= 50:
        return key
    digest = hashlib.sha1(name.encode()).hexdigest()[:8]
    prefix = f"mcp_{server_id}__"
    return (prefix + name)[: 50 - 9] + "_" + digest     # keep prefix + 8-char hash, fits 50


def runtime_dict(srv) -> dict:
    """Decrypted, transport-aware server dict for the session manager."""

    from server import crypto
    env = {}
    if srv.env:
        try:
            env = json.loads(crypto.decrypt(srv.env))
        except Exception:  # noqa: BLE001
            env = {}
    return {"id": srv.id, "transport": srv.transport or "stdio",
            "command": srv.command, "args": srv.args or [], "url": srv.url, "env": env,
            # 0.1.57 §5.3: installed capabilities start under their seatbelt profile.
            "sandbox": getattr(srv, "sandbox", None)}


def _describe_failure(exc: BaseException, *, has_headers: bool) -> str:
    """last_error for a failed connect — classified, and never empty.

    Two shapes this replaces. A 401 used to become `str(exc)[:500]`: whatever
    prose httpx chose, with no hint that the fix is credentials rather than the
    server. And `str(InvalidToken())` is the EMPTY STRING (measured, spec ⓪
    §2.3), so the same line could write a blank last_error — an error slot that
    reads as unset.

    The status error may arrive wrapped (anyio task groups), so the walk looks
    inside groups and causes, depth-limited rather than recursion-trusting.
    """
    # An index walk, not `for e in seen[:32]`: that slice is snapshotted before
    # the loop body ever appends, so wrapped exceptions would never be visited —
    # the exact case the walk exists for. (Caught by the wrapped-401 test.)
    seen: list[BaseException] = [exc]
    i = 0
    while i < len(seen) and i < 32:
        e = seen[i]
        i += 1
        if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (401, 403):
            code = e.response.status_code
            if has_headers:
                return (
                    f"authorization failed (HTTP {code}): the server rejected the "
                    "configured headers — re-check the token/key on this server"
                )
            return (
                f"authorization failed (HTTP {code}): no credentials are configured "
                "for this server — it requires authentication"
            )
        seen.extend(getattr(e, "exceptions", ()) or ())
        for link in (e.__cause__, e.__context__):
            if link is not None and link not in seen:
                seen.append(link)
    text = str(exc).strip()
    # An exception whose str() is empty must still leave a trace a human can read.
    return text[:500] if text else f"{type(exc).__name__} (no message)"


MAX_PAGES = 20
HINT_KEYS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint", "title")
_write_locks = LoopLocks()


class ServerGone(ValueError):
    """The MCP server row does not exist (any more)."""


def read_only(hints: dict | None) -> bool:
    """S1: the server says this tool only reads (MCP `readOnlyHint`). Self-reported: trusted as far as
    the user trusts a server they turned on (card S1, risks)."""
    return bool(hints) and hints.get("readOnlyHint") is True


def destructive(hints: dict | None) -> bool:
    """S1: the server says this tool may destroy something (`destructiveHint`), and not that it only
    reads. A tool with no hints is not destructive here, unlike the MCP spec's default: it gets the
    ordinary card (⓪Plan, Q5). K9 and S5 reuse these two."""
    return bool(hints) and hints.get("destructiveHint") is True and not read_only(hints)


def tool_hints(tool) -> dict | None:
    """The tool's declared MCP annotations (§B4): the known keys that are set — booleans for the
    hints, a title of at most 200 characters. None when it declares none. Hints are the server's
    claims, stored as data; nothing in PR 4 decides on them."""
    ann = getattr(tool, "annotations", None)
    if ann is None:
        return None
    if hasattr(ann, "model_dump"):
        data = ann.model_dump(exclude_none=True)
    elif isinstance(ann, dict):
        data = ann
    else:
        data = {key: getattr(ann, key, None) for key in HINT_KEYS}
    hints: dict = {}
    for key in HINT_KEYS:
        value = data.get(key)
        if key == "title":
            if isinstance(value, str):      # server-controlled text: no control or ANSI codes
                title = " ".join(CONTROL_CHARS.sub("", value).split())[:200]
                if title:
                    hints[key] = title
        elif isinstance(value, bool):
            hints[key] = value
    return hints or None


async def _runtime(server_id: int) -> dict:
    async with db_session.AsyncSessionLocal() as db:
        srv = await db.get(MCPServer, server_id)
        if srv is None:
            raise ServerGone(f"mcp server {server_id} not found")
        return runtime_dict(srv)


async def _list_all(server: dict) -> tuple[list, bool]:
    """Every page of tools/list → (tools, complete). Deduplicated by name (the last page wins);
    complete=False when MAX_PAGES stopped it. No database session is open meanwhile. Every page
    comes from ONE session: the later pages ask for the live session as it is (never an open), and
    a drop or replacement between pages raises NotStarted, because a cursor belongs to the session
    that issued it."""
    listed = await manager.list_tools(server)
    live = manager.cached(server["id"])
    later = {**server, "live_only": live if live is not None else True}
    by_name = {t.name: t for t in listed.tools}
    cursor, pages = getattr(listed, "nextCursor", None), 1
    while cursor:
        if pages >= MAX_PAGES:
            return list(by_name.values()), False
        listed = await manager.list_tools(later, cursor=cursor)
        by_name.update({t.name: t for t in listed.tools})
        cursor, pages = getattr(listed, "nextCursor", None), pages + 1
    return list(by_name.values()), True


def forget(server_id: int) -> None:
    """The server is gone for good (`manager.forget`): drop its lock unless a listing holds it."""
    _write_locks.forget(server_id)


async def _write(server_id: int, tools: list, *, complete: bool) -> list[dict]:
    """Add, update and prune this server's Tool rows in one short transaction. The caller holds the
    server's lock; a concurrent insert of the same key (another process) is retried once."""
    try:
        return await _write_once(server_id, tools, complete=complete)
    except IntegrityError:
        logger.info("mcp %s: concurrent tool write, retrying once", server_id)
        return await _write_once(server_id, tools, complete=complete)


async def _write_once(server_id: int, tools: list, *, complete: bool) -> list[dict]:
    discovered: list[dict] = []
    async with db_session.AsyncSessionLocal() as db:
        ts_key = f"mcp_{server_id}"
        srv = await db.get(MCPServer, server_id)
        if srv is None:
            raise ServerGone(f"mcp server {server_id} not found")
        if await db.get(Toolset, ts_key) is None:
            db.add(Toolset(key=ts_key, name=srv.label, description=f"MCP server: {srv.command}",
                           tier="orchestrator", status="registered", backend_note=f"MCP: {srv.command}"))
        rows = (await db.execute(select(Tool).where(Tool.toolset_key == ts_key))).scalars().all()
        by_key = {row.key: row for row in rows}
        for t in tools:
            key = mcp_tool_key(server_id, t.name)
            schema = getattr(t, "inputSchema", None) or {}
            hints = tool_hints(t)
            row = by_key.get(key)
            if row is None:
                row = Tool(key=key, toolset_key=ts_key, description=t.description or t.name,
                           tier="orchestrator", status="registered", input_schema=schema,
                           external_name=t.name, annotations=hints)
                db.add(row)
                by_key[key] = row
            else:                                  # tier/status (the user's wiring) are kept
                row.description = t.description or t.name
                row.input_schema = schema
                row.external_name = t.name
                row.annotations = hints
            discovered.append({"key": key, "name": t.name, "description": t.description or "",
                               "suggested_tier": suggested_tier_for(srv, t.name)})
        names = {t.name for t in tools}
        stale = [row for row in rows if (row.external_name or "") not in names]
        if stale and tools and complete:
            for row in stale:
                await db.delete(row)
        elif stale:
            logger.warning("mcp %s: listing was %s; kept %d tools it did not name", server_id,
                           "empty" if not tools else f"cut at {MAX_PAGES} pages", len(stale))
        await db.commit()
    return discovered


async def connect_and_discover(server_id: int, *, start_budget_s: float | None = None) -> list[dict]:
    """Returns [{key,name,description,suggested_tier}, ...]. Opens the session within
    `start_budget_s` when none is live, lists every page, then adds, updates and prunes the Tool
    rows and stores their hints. Raises whatever the open or the listing raised (ServerGone for an
    unknown id; NotStarted when the open was overtaken by a drop or forget). Writes no state: the
    supervisor's `_set` does (0.1.61 §B1) — classified and masked. The listing and its write run
    under the server's lock, so they never interleave with another listing's."""
    async with _write_locks.hold(server_id):
        server = await _runtime(server_id)
        if start_budget_s is not None:
            server["start_budget_s"] = start_budget_s
        tools, complete = await _list_all(server)
        return await _write(server_id, tools, complete=complete)


async def relist(server_id: int) -> list[dict] | None:
    """tools/list_changed (§B1): list again on the live session as it is — never opens one, never
    restarts one (an edited row does not reopen it) — then add, update and prune. None when no
    session is live, or it went away meanwhile: the supervisor restarts it, not this. Any other
    failure is raised (the session it ran on is already dropped, so the caller schedules a fresh
    start)."""
    if manager.cached(server_id) is None:
        return None
    async with _write_locks.hold(server_id):
        server = await _runtime(server_id)
        server["live_only"] = True
        try:
            tools, complete = await _list_all(server)
        except NotStarted:
            return None
        return await _write(server_id, tools, complete=complete)

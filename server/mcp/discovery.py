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
import unicodedata
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from server.db import session as db_session
from server.db.models import CapabilitySource, MCPServer, Tool, Toolset
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
    # SEC1: a moved secret is a `${NAME}` placeholder in the stored url/args, filled in here; `secrets` goes
    # with the dict so masking knows the values (spawn_env.secret_forms).
    from server.services import connection_secrets
    secrets = {}
    if getattr(srv, "secrets", None):
        try:
            secrets = json.loads(crypto.decrypt(srv.secrets))
        except Exception:  # noqa: BLE001 — unreadable: the placeholders stay; the list names them (secrets_missing)
            secrets = {}
    url, args = connection_secrets.fill(srv.url, srv.args or [], secrets)
    return {"id": srv.id, "transport": srv.transport or "stdio",
            "command": srv.command, "args": args, "url": url, "env": env, "secrets": secrets,
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


#: CAP5a: the parked line for a server whose tools changed (Arslan's own words, in the supervisor's safe reasons).
TOOLS_CHANGED_LINE = "its tools changed since it was installed — review the change in Capabilities"
#: Parks only the user's own review ends (the supervisor's fix line says so, never "press Reconnect").
HELD_REASONS = (TOOLS_CHANGED_LINE,)
#: CAP5a (#577 review F2): a review shows whole every tool the accept would pin. A change too large to read in
#: full (more tools, or a longer tool, than this) is recorded without an accept: remove or reinstall instead.
REVIEW_TOOLS_MAX, REVIEW_TOOL_CHARS_MAX = 100, 20_000


class ToolsChanged(Exception):
    """CAP5a: a server Arslan installed listed tools that differ from the ones pinned at its first test.
    Nothing of the new listing was written; the supervisor parks the server (TOOLS_CHANGED_LINE)."""

    def __init__(self, server_id: int, changes: dict):
        super().__init__(TOOLS_CHANGED_LINE)
        self.server_id, self.changes = server_id, changes


def _fingerprint(tool) -> str:
    """CAP5a: the SHA-256 of what the model and the approvals read of one tool: its name, title, description,
    input schema and declared hints, as canonical JSON (sorted keys), so a reordered schema is not a change."""
    return hashlib.sha256(json.dumps(_reviewed(tool), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _reviewed(tool) -> dict:
    """Exactly what the fingerprint covers of one tool, as the review shows it: nothing cut, nothing cleaned."""
    return {"name": tool.name, "title": getattr(tool, "title", None), "description": tool.description or tool.name,
            "inputSchema": getattr(tool, "inputSchema", None) or {}, "hints": tool_hints(tool)}


def tools_pin(tools: list) -> dict:
    """CAP5a: {tool name: fingerprint} of one listing."""
    return {t.name: _fingerprint(t) for t in tools}


def pin_digest(pin: dict) -> str:
    """CAP5a: one digest of a whole pin; a review's accept names it, so it pins exactly what the user read."""
    return hashlib.sha256(json.dumps(pin, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _hidden(value) -> int:
    """How many characters of a tool's text show nothing (#577 review F2), in every string it holds (its schema's
    included): the review keeps them as they are, so the page shows them as markers and says how many."""
    from server.orchestrator import untrusted
    if isinstance(value, dict):
        return sum(_hidden(k) + _hidden(v) for k, v in value.items())
    if isinstance(value, list):
        return sum(_hidden(v) for v in value)
    if not isinstance(value, str):
        return 0
    return sum(1 for ch in value if (unicodedata.category(ch).startswith("C") and ch not in "\n\t")
               or untrusted._NAME_INVISIBLE.fullmatch(ch))


def _loosens(old_hints: dict | None, new_hints: dict | None) -> list[str]:
    """What a change does to the approval of a call (S1, #577 review F2): a tool now read-only runs with no card,
    and one that no longer says it may destroy something loses that card's warning."""
    out = []
    if read_only(new_hints) and not read_only(old_hints):
        out.append("read_only_added")
    if destructive(old_hints) and not destructive(new_hints):
        out.append("destructive_dropped")
    return out


def _changes(pinned: dict, listed: dict, *, complete: bool) -> dict | None:
    """Added, removed and changed tool names, or None when the listing matches the pin. A listing cut at
    MAX_PAGES cannot show a removal, so only a complete one counts what it did not name."""
    added = sorted(set(listed) - set(pinned))
    changed = sorted(n for n in set(listed) & set(pinned) if listed[n] != pinned[n])
    removed = sorted(set(pinned) - set(listed)) if complete else []
    return {"added": added, "removed": removed, "changed": changed} if added or changed or removed else None


async def _source_of(db, server_id: int):
    """The capability source of a server Arslan installed: installed, or kept after a failed test, never removed
    (#577 review F3: a failed test kept the server row, and a switch could turn it on unpinned). The server must
    have existed when the source was installed, as capability_list._installed_servers asks (re-check G2): a
    number can be reused by a server added by hand later, which is not this source's."""
    return (await db.execute(select(CapabilitySource).join(MCPServer, MCPServer.id == CapabilitySource.mcp_server_id)
                             .where(CapabilitySource.mcp_server_id == server_id, CapabilitySource.kind == "mcp",
                                    CapabilitySource.state != "removed",
                                    MCPServer.created_at <= CapabilitySource.installed_at)
                             .order_by(CapabilitySource.created_at.desc()))).scalars().first()


async def held(server_id: int) -> dict | None:
    """CAP5a (#577 review F1): the change still waiting for the user's review, if any. While there is one the
    server is not started at all: no probe, boot, tick or tools/list_changed start opens its process; only the
    user's accept lifts it."""
    async with db_session.AsyncSessionLocal() as db:
        source = await _source_of(db, server_id)
    return (source.test or {}).get("tools_changed") if source is not None else None


async def _check_pin(db, server_id: int, tools: list, rows_by_name: dict, *, complete: bool) -> None:
    """CAP5a (rug pull): a server Arslan installed is pinned to the tools its first test listed (the pin lives in
    its capability source's `test`). Every later listing, on each connect and each tools/list_changed, is
    compared first: any difference records the change for review and raises ToolsChanged before a row is
    written. The record stays until the user accepts it (#577 review F5: a server that reverts is still the
    signal). Hand-added servers have no capability source and are not pinned (a stated limit). An empty
    listing is not compared: it never wipes the rows either."""
    from server.orchestrator import untrusted
    if not tools:
        return
    source = await _source_of(db, server_id)
    if source is None:
        return
    listed = tools_pin(tools)
    pinned = (source.test or {}).get("tools_pin")
    if pinned is None:                          # the first listing: its install test (or, once, after an upgrade)
        source.test = {**(source.test or {}), "tools_pin": listed}
        return
    changes = _changes(pinned, listed, complete=complete)
    if changes is None:
        return
    by_name = {t.name: t for t in tools}
    review, reviewable = [], len(changes["changed"]) + len(changes["added"]) <= REVIEW_TOOLS_MAX
    for n in (changes["changed"] + changes["added"])[:REVIEW_TOOLS_MAX]:
        now, row = _reviewed(by_name[n]), rows_by_name.get(n)
        text = json.dumps(now, ensure_ascii=False)
        entry = {"name": n, "loosens": _loosens(row.annotations if row else None, now["hints"]),
                 "hidden": _hidden(now)}
        if len(text) > REVIEW_TOOL_CHARS_MAX:
            entry["too_long"], reviewable = True, False
        else:
            entry["now"] = now
            entry["was"] = ({"description": row.description, "inputSchema": row.input_schema or {},
                             "hints": row.annotations} if row else None)
        review.append(entry)
    names = changes["added"] + changes["removed"] + changes["changed"]
    record = {**changes, "shown": {n: untrusted.clean_name(n, 128) for n in names}, "tools": review,
              "reviewable": reviewable, "pin": listed, "digest": pin_digest(listed),
              "at": datetime.utcnow().isoformat() + "Z"}
    source.test = {**(source.test or {}), "tools_changed": record}
    await db.commit()
    raise ToolsChanged(server_id, record)


def read_only(hints: dict | None) -> bool:
    """S1: the server says this tool only reads (MCP `readOnlyHint`), and does not also say it may
    destroy something. Self-reported: trusted as far as the user trusts a server they turned on (card
    S1, risks)."""
    return bool(hints) and hints.get("readOnlyHint") is True and hints.get("destructiveHint") is not True


def destructive(hints: dict | None) -> bool:
    """S1: the server says this tool may destroy something (`destructiveHint`). Saying it only reads as
    well contradicts that, and the safer reading wins (⓪Plan's review): it costs an honest server
    nothing. A tool with no hints is not destructive here, unlike the MCP spec's default: it gets the
    ordinary card (⓪Plan, Q5). K9 and S5 reuse these two."""
    return bool(hints) and hints.get("destructiveHint") is True


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
        await _check_pin(db, server_id, tools, {row.external_name: row for row in rows if row.external_name},
                         complete=complete)
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
        pending = await held(server_id)
        if pending is not None:                 # #577 review F1: held until reviewed; no process is opened
            raise ToolsChanged(server_id, pending)
        tools, complete = await _list_all(server)
        try:
            return await _write(server_id, tools, complete=complete)
        except ToolsChanged:
            # #577 review F1: the process that listed the changed tools goes now, with its folders, keys and
            # network; nothing starts it again before the user's review.
            await manager.drop(server_id)
            raise


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
        try:
            return await _write(server_id, tools, complete=complete)
        except ToolsChanged:
            # CAP5a: the live session serves the changed tools, so it goes now; the supervisor's restart lists
            # again and parks the server (the drop is what makes it restart, as for a failed re-list).
            await manager.drop(server_id)
            raise

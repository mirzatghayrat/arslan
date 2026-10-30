"""CRUD + connect/expose/wire + health probe for MCP servers. env stored encrypted, masked on read."""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm.exc import StaleDataError

from server import crypto
from server.db import session as db_session
from server.db.models import MCPServer, Tool, Toolset
from server.mcp import discovery
from server.orchestrator import untrusted
from server.services.secret_state import secret_state
from server.services.settings_service import mask_secret

logger = logging.getLogger(__name__)


class MCPStartFailed(RuntimeError):
    """A Connect whose start did not end `ready`; str() is the classified last_error — or, for a
    start overtaken twice by a newer one, the state answer. `state` says which (0.1.61 §B1)."""

    def __init__(self, text: str, *, state: str = "failed") -> None:
        super().__init__(text)
        self.state = state


def _mask_env(env: dict) -> dict:
    return {k: mask_secret(v) for k, v in (env or {}).items()}


def _legacy_words(srv: MCPServer, shown: str) -> tuple[str | None, str | None]:
    """The legacy `status` and `health_status`, from the SHOWN state (final review M-1): `connected`
    and `ok` only for a server that is ready in this process — the old UI (until PR 8) reads them,
    and a `ready` row with no live session behind it is starting, not connected. A switched-off
    server keeps what it said before (registered, error …), except a connection it no longer has."""
    from server.mcp.supervisor import LEGACY_HEALTH, LEGACY_STATUS
    status = LEGACY_STATUS.get(shown, srv.status)
    if shown == "off" and status in ("connected", "connecting"):
        status = "disconnected"
    health = srv.health_status
    if shown != "ready" and health == "ok":
        health = LEGACY_HEALTH.get(shown)            # failing, or None (= not checked) while starting/off
    return status, health


def _shown(srv: MCPServer) -> str:
    from server.mcp.executor import shown_state
    return shown_state(srv.id, srv.state, bool(srv.host_allowed))


def _to_dict(srv: MCPServer, *, mask: bool = True, stored_status: bool = False) -> dict:
    """The API's view of a server. `state` is the stored state (PR 8 and the Capabilities rows read
    it); `shown` is the state it is shown in — the one readiness rule (`executor.shown_state`) — and
    the legacy `status`/`health_status` follow `shown` (final review M-1). `stored_status` keeps the
    stored legacy status, for the Capabilities rows only: they tell "never connected" (registered)
    from a switched-on row whose start is pending. `last_error` is masked (final review I-2)."""
    from server.mcp.executor import masked_error
    env = {}
    if srv.env:
        try:
            env = json.loads(crypto.decrypt(srv.env))
        except Exception:  # noqa: BLE001
            env = {}
    # 🔴 env_status exists because the {} above is indistinguishable from "this server
    # never had credentials". An undecryptable env means the server is started WITHOUT
    # its API key and fails with whatever that remote service says about a missing
    # token — a symptom that points at the wrong thing entirely. Same three-state
    # vocabulary as the settings secrets and the provider rows; one word, not three
    # dialects.
    shown = _shown(srv)
    status, health = _legacy_words(srv, shown)
    return {"id": srv.id, "label": srv.label, "command": srv.command, "args": srv.args or [],
            "url": srv.url, "env": _mask_env(env) if mask else env,
            "status": srv.status if stored_status else status,
            "env_status": secret_state(srv.env), "last_error": masked_error(srv),
            "transport": srv.transport,
            "host_allowed": bool(srv.host_allowed),
            "health_status": health,
            "last_checked_at": srv.last_checked_at.isoformat() if srv.last_checked_at else None,
            # 0.1.61 §B1: the one state the supervisor writes, and the state it is shown in
            "state": srv.state, "shown": shown,
            "state_at": srv.state_at.isoformat() if srv.state_at else None,
            "last_ok_at": srv.last_ok_at.isoformat() if srv.last_ok_at else None,
            "next_retry_at": srv.next_retry_at.isoformat() if srv.next_retry_at else None,
            "fail_count": srv.fail_count}


async def add_server(label: str, command: str, args: list[str], env: dict,
                     transport: str = "stdio", url: str | None = None) -> dict:
    if transport not in ("stdio", "http"):
        raise ValueError("transport must be stdio|http")
    if transport == "http" and not (url or "").strip():
        raise ValueError("http transport requires a url")
    if transport == "stdio" and not (command or "").strip():
        raise ValueError("stdio transport requires a command")
    label = untrusted.clean_name(label, 80)                 # UNI1: one cleaner for names, wherever they come in
    if not label:
        raise ValueError("a label is required")
    async with db_session.AsyncSessionLocal() as db:
        # Dedup guard: return existing row if (label, url) or (label, command, args) already present
        existing = None
        if transport == "http":
            result = await db.execute(
                select(MCPServer).where(MCPServer.label == label, MCPServer.url == url)
            )
            existing = result.scalars().first()
        else:
            canon_args = json.dumps(sorted(args or []))
            all_stdio = (await db.execute(
                select(MCPServer).where(MCPServer.label == label, MCPServer.command == (command or ""))
            )).scalars().all()
            for row in all_stdio:
                if json.dumps(sorted(row.args or [])) == canon_args:
                    existing = row
                    break
        if existing is not None:
            return _to_dict(existing)
        srv = MCPServer(label=label, command=command or "", args=args or [], transport=transport, url=url,
                        env=crypto.encrypt(json.dumps(env or {})), status="registered")
        db.add(srv)
        await db.commit()
        await db.refresh(srv)
        out = _to_dict(srv)
    from server.mcp.supervisor import supervisor

    supervisor.schedule(out["id"])        # 0.1.61 §B1: adding starts it (in the background)
    return out


async def list_servers(*, stored_status: bool = False) -> list[dict]:
    """GET /mcp/servers. `stored_status`: see `_to_dict` (the Capabilities rows only)."""
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(select(MCPServer).order_by(MCPServer.id))).scalars().all()
        # Real expose state, batch-derived from the toolset tier — the frontend
        # checkbox used to hardcode false because nothing served the truth.
        exposed: dict[str, bool] = {}
        if rows:
            ts_rows = (await db.execute(
                select(Toolset).where(Toolset.key.in_([f"mcp_{r.id}" for r in rows]))
            )).scalars().all()
            exposed = {ts.key: ts.tier == "safe" for ts in ts_rows}
        out = []
        for r in rows:
            d = _to_dict(r, stored_status=stored_status)
            d["exposed"] = exposed.get(f"mcp_{r.id}", False)
            out.append(d)
        return out


async def start_now(server_id: int):
    """`supervisor.restart` (Connect, the install test), once more when its start was overtaken by
    a newer one: a drop while it opened (new folders, an edit) is not a failure (carry: Task 4
    concern 4). Returns the StartResult; ValueError for an unknown id."""
    from server.mcp.supervisor import supervisor

    result = await supervisor.restart(server_id)
    if result.state == "starting":
        result = await supervisor.restart(server_id)
    return result


async def connect(server_id: int) -> list[dict]:
    """A fresh start now (the Connect button). Returns the discovered tools as before, or raises
    MCPStartFailed with the classified cause — the old UI's contract (0.1.61 §B1). A start
    overtaken twice answers with the state (`starting`), never as a failure."""
    from server.mcp.supervisor import fix_for

    result = await start_now(server_id)        # ValueError for an unknown id → 404
    if result.state == "starting":
        raise MCPStartFailed("starting: the start was overtaken by a newer one — "
                             + fix_for("starting", has_headers=False), state="starting")
    if result.state != "ready":
        raise MCPStartFailed(result.last_error or result.state, state=result.state)
    # UNI1 (#526 review 4): the page shows each tool by its name through the name rule, as list_tools does.
    return [{**tool, "shown": untrusted.clean_name(tool.get("name"), 128) or tool.get("key")} for tool in result.tools]


async def list_tools(server_id: int) -> list[dict]:
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Tool).where(Tool.toolset_key == f"mcp_{server_id}").order_by(Tool.key)
        )).scalars().all()
        # UNI1 (#526 review 4): a tool's name is the server's own words. `shown` is what the connections page
        # shows, through the name rule; `name` stays as the server sent it, because list_my_capabilities judges it
        # against MCP's name rule (S64-0c) and the key stays the identity.
        return [{"key": t.key, "name": t.external_name or t.key,
                 "shown": untrusted.clean_name(t.external_name, 128) or t.key, "description": t.description,
                 "tier": t.tier, "status": t.status, "host_enabled": t.host_enabled,
                 "suggested_tier": discovery.suggest_tier(t.external_name or "")}
                for t in rows]


async def set_exposed(server_id: int, exposed: bool) -> None:
    """Expose ("Allow for spawns") at SERVER granularity (user ruling 2026-08-18).

    The checkbox used to be half-fake: it lifted the Toolset to safe, but the
    spawn choke point needs TOOL-level tier=safe ∧ status=wired, so a checked
    box still handed spawns nothing. Exposing now wires every tool whose
    suggested tier is safe — suggested_tier_for, so a hand-graded table
    (Playwright) beats the verb heuristic — and write-graded tools stay
    unwired: spawns never get write verbs without an explicit per-tool action.
    Un-exposing un-wires the server's tools wholesale (approved default: no
    carve-out for manually wired ones — simple and honest).
    """
    from server.mcp.discovery import suggested_tier_for

    async with db_session.AsyncSessionLocal() as db:
        ts = await db.get(Toolset, f"mcp_{server_id}")
        if ts is None:
            return
        ts.tier = "safe" if exposed else "orchestrator"
        ts.status = "registered"
        srv = await db.get(MCPServer, server_id)
        rows = (await db.execute(
            select(Tool).where(Tool.toolset_key == f"mcp_{server_id}")
        )).scalars().all()
        for tool in rows:
            if exposed and suggested_tier_for(srv, tool.external_name or "") == "safe":
                tool.tier, tool.status = "safe", "wired"
            elif not exposed:
                tool.tier, tool.status = "orchestrator", "registered"
        await db.commit()


async def wire_tool(tool_key: str, tier: str, wired: bool) -> None:
    if tier not in ("safe", "orchestrator"):
        raise ValueError("tier must be safe|orchestrator")
    async with db_session.AsyncSessionLocal() as db:
        tool = await db.get(Tool, tool_key)
        if tool is None or not (tool.toolset_key or "").startswith("mcp_"):
            raise ValueError("not an MCP tool")
        tool.tier = tier
        tool.status = "wired" if wired else "registered"
        await db.commit()


async def set_host_allowed(server_id: int, allowed: bool) -> None:
    """The revocable face of the server-level host consent. 0.1.61 §B1: off stops the server and
    its retries; on starts it. Committed first — a background plan reads it to respect the switch.
    A delete that lands between the read and the write is "not found" (final review M-3), never a 500."""
    try:
        async with db_session.AsyncSessionLocal() as db:
            srv = await db.get(MCPServer, server_id)
            if srv is None:
                raise ValueError(f"mcp server {server_id} not found")
            srv.host_allowed = allowed
            await db.commit()
    except StaleDataError as exc:          # the UPDATE matched no row: deleted meanwhile
        raise ValueError(f"mcp server {server_id} not found") from exc
    from server.mcp.supervisor import supervisor

    await supervisor.set_enabled(server_id, allowed)   # off stops it; on starts it


async def restart_after_edit(server_id: int) -> None:
    """A server's command, args, env or sandbox changed (new folders, an edit). Its cached session
    still runs the old ones — call_tool never compares fingerprints — so it is dropped now and a
    fresh start is scheduled in the background: an edit never waits for a start. Every path that
    edits a server ends here (carry: the env-only edit). That start gets the cold budget (a flag,
    never a cleared last_ok_at): an update may mean a download (final review, fix C).

    The fresh start is scheduled FIRST, the order of every supervisor verb (Task 6 fix round 2,
    N-1/N-2): the generation has moved before the drop wakes anyone — a probe pending on the old
    session sees a deliberate drop, not a death, and a start writing its tools is replaced (its
    Connect follows the edit's start) instead of ending `failed` over the dropped session."""
    from server.mcp.session import manager
    from server.mcp.supervisor import supervisor

    supervisor.schedule(server_id, fresh=True, cold=True)   # the update may have changed the package
    await manager.drop(server_id)


async def last_error_text(server_id: int) -> str | None:
    """The classified last_error for a server, for API error shaping — masked (final review I-2)."""
    from server.mcp.executor import masked_error
    async with db_session.AsyncSessionLocal() as db:
        srv = await db.get(MCPServer, server_id)
    return masked_error(srv) if srv is not None else None


async def reconnect(server_id: int) -> None:
    """RECONNECT always starts a fresh process (spec §B1); the row says how it went. ValueError for
    an unknown id."""
    from server.mcp.supervisor import supervisor

    await supervisor.restart(server_id)


async def delete_server(server_id: int) -> None:
    """The row first, then `forget` — which cancels an in-flight start (no orphan process), closes
    the session and moves the server's folder aside. In the other order a supervisor tick between
    the two found the row and started the deleted server again (forget's guard covers only its
    own inside)."""
    async with db_session.AsyncSessionLocal() as db:
        for t in (await db.execute(select(Tool).where(Tool.toolset_key == f"mcp_{server_id}"))).scalars().all():
            await db.delete(t)
        ts = await db.get(Toolset, f"mcp_{server_id}")
        if ts is not None:
            await db.delete(ts)
        srv = await db.get(MCPServer, server_id)
        if srv is not None:
            await db.delete(srv)
        await db.commit()
    from server.mcp.supervisor import supervisor

    await supervisor.forget(server_id)

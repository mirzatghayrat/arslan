"""The three v1 read-only, METADATA-ONLY inbound MCP tools.

Each wraps an existing read service-seam and returns metadata only — never a run's
output body, a spawn's answer/persona text, or brain content. The no-body golden test
in tests/server/test_mcp_server_tools.py enforces this structurally: adding a body
field here breaks the build. Tools open their own DB session (read at call time so a
monkeypatched maker is honored)."""
from __future__ import annotations

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import Run
from server.mcp_server import audit
from server.registry import service as registry_service
from server.services import mcp_service, spawn_service

# Metadata projection of a Run row — the spec's fixed field list (spec §4).
# Deliberately EXCLUDES every content/output body: final_output, user_message,
# system_prompt, injected_kb, injected_kb_sources, error_text.
def _run_status(r: Run) -> dict:
    return {
        "run_id": r.id,
        "spawn_id": r.spawn_id,
        "spawn_name": r.spawn_name,
        "status": r.status,
        "kind": r.kind,
        "model": r.model,
        "provider": r.provider,
        "tokens_in": r.tokens_in,
        "tokens_out": r.tokens_out,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "ended_at": r.ended_at.isoformat() if r.ended_at else None,
        # The spec's `eval_verdict` — Run has no single eval_verdict column; the judged
        # outcome is (overall_score, overall_badge). None when the run is unscored.
        "eval_verdict": (
            {"score": r.overall_score, "badge": r.overall_badge}
            if (r.overall_score is not None or r.overall_badge is not None) else None
        ),
    }


async def list_spawns() -> dict:
    """The user's agents (spawns) with equipment keys. Metadata only."""
    async with db_session.AsyncSessionLocal() as db:
        spawns = await spawn_service.list_spawns(db)
        out = []
        for s in spawns:
            equip = await registry_service.equipment_for_spawn(s.id, session=db)
            out.append({
                "id": s.id,
                "name": s.name,
                "domain": s.domain,
                "capabilities": list(s.capabilities),
                "generation_level": s.generation_level,
                "is_default": s.is_default,
                "has_active_chat": s.has_active_chat,
                "equipment": {
                    "toolsets": [t["key"] for t in equip["toolsets"]],
                    "skills": [sk["key"] for sk in equip["skills"]],
                },
            })
    audit.record(tool="list_spawns", status="ok")
    return {"spawns": out}


async def list_capabilities() -> dict:
    """Built-in tools, connected MCP servers, and skills. Labels/descriptions only."""
    menu = await registry_service.safe_menu()
    servers = await mcp_service.list_servers()
    result = {
        "builtin_tools": [
            {"key": t["key"], "description": t["description"], "tier": t["tier"]}
            for t in menu["toolsets"]
        ],
        "mcp_servers": [
            {"label": s.get("label"), "status": s.get("status")} for s in servers
        ],
        "skills": [
            {"key": sk["key"], "description": sk["description"]} for sk in menu["skills"]
        ],
    }
    audit.record(tool="list_capabilities", status="ok")
    return result


async def get_run_status(run_id: int | None = None, spawn_id: int | None = None) -> dict:
    """Run status/metadata by run_id, or the 10 most recent runs by spawn_id.
    Metadata only — never final_output / answer text / trace / injected KB bodies."""
    async with db_session.AsyncSessionLocal() as db:
        if run_id is not None:
            r = await db.get(Run, run_id)
            result = _run_status(r) if r is not None else {"found": False, "run_id": run_id}
        elif spawn_id is not None:
            rows = (await db.execute(
                select(Run).where(Run.spawn_id == spawn_id).order_by(Run.id.desc()).limit(10)
            )).scalars().all()
            result = {"spawn_id": spawn_id, "runs": [_run_status(r) for r in rows]}
        else:
            result = {"found": False, "detail": "provide run_id or spawn_id"}
    audit.record(tool="get_run_status", status="ok")
    return result

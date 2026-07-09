"""Read-only capability catalog. Orchestrator items ARE listed (transparency),
marked assignable: false."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.models import SkillPack, Tool, Toolset
from server.db.session import get_session
from server.registry.service import (
    skill_compatibility,
    skill_health,
    skill_is_assignable,
    toolset_is_assignable,
)
from server.schemas import RegistryOut, SkillPackOut, ToolOut, ToolsetOut
from server.services import code_sandbox

router = APIRouter(dependencies=[Depends(require_auth)])

# PC-5 条件: the health probe is bounded (mirrors PB-4's _HEALTH_PROBE_TIMEOUT). Skill health
# is local/cheap (small filesystem reads, no network/subprocess), so a short 5s bound suffices.
_SKILL_HEALTH_TIMEOUT = 5.0


@router.get("/registry", response_model=RegistryOut)
async def get_registry(session: AsyncSession = Depends(get_session)) -> RegistryOut:
    toolsets = (await session.execute(select(Toolset).order_by(Toolset.key))).scalars().all()
    tools = (await session.execute(select(Tool).order_by(Tool.key))).scalars().all()
    skills = (await session.execute(select(SkillPack).order_by(SkillPack.key))).scalars().all()

    by_ts: dict[str, list[ToolOut]] = {}
    for t in tools:
        by_ts.setdefault(t.toolset_key, []).append(
            ToolOut(key=t.key, description=t.description, tier=t.tier, status=t.status)
        )
    # P0-1 决定①b: the code_sandbox toolset (run_python) is DEGRADED when the escape valve is
    # open on a host with no isolation backend — surface it so the capability page badges it.
    py_degraded = code_sandbox.unsandboxed_active()
    return RegistryOut(
        toolsets=[
            ToolsetOut(
                key=t.key, name=t.name, description=t.description, tier=t.tier,
                status=t.status,
                # assignable = functional, not just catalogued (>=1 safe wired tool)
                assignable=toolset_is_assignable(
                    t.tier, t.status,
                    has_wired_tool=any(x.tier == "safe" and x.status == "wired"
                                       for x in by_ts.get(t.key, []))),
                tools=by_ts.get(t.key, []),
                degraded=(t.key == "code_sandbox" and py_degraded),
                warning=("run_python 正在无沙箱裸跑(ARSLAN_ALLOW_UNSANDBOXED_PY=1):无隔离,"
                         "代码以完整主机权限运行" if (t.key == "code_sandbox" and py_degraded) else None),
            )
            for t in toolsets
        ],
        skills=[
            SkillPackOut(
                key=s.key, name=s.name, category=s.category, description=s.description,
                tier=s.tier, status=s.status,
                # assignable = has a real method body (no-body entries are catalog-only)
                assignable=skill_is_assignable(s.tier, s.status, s.body),
                # PC-4: honest sandbox-compatibility badge (full/partial/text)
                compatibility=skill_compatibility(s.key, s.body),
            )
            for s in skills
        ],
    )


@router.post("/registry/skills/{key}/health")
async def check_skill_health(key: str, session: AsyncSession = Depends(get_session)) -> dict:
    """PC-5 on-demand skill health probe (mirrors PB-4's POST /mcp/{id}/health).

    Returns a structured storage/scripts/references report + an overall roll-up. Honest:
    it PROBES sandbox-backend availability (never executes skill code) and never reports a
    script runnable when no backend is available on this host. `require_auth` applies via the
    router-level dependency; unknown key → 404."""
    row = await session.get(SkillPack, key)
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown skill: {key}")
    body = row.body
    try:
        # Bounded, mirroring PB-4. skill_health is sync + cheap; run it off-loop so the timeout
        # is real. wait_for cancels with CancelledError (BaseException) — NOT caught by
        # `except Exception` — so we handle TimeoutError explicitly and never leak a 500.
        return await asyncio.wait_for(
            asyncio.to_thread(skill_health, key, body),
            timeout=_SKILL_HEALTH_TIMEOUT,
        )
    except TimeoutError:
        return {
            "key": key, "status": "degraded", "ok": False, "timed_out": True,
            "sandbox_available": False, "sandbox_backend": "unknown",
            "compatibility": skill_compatibility(key, body),
            "storage": {"ok": False, "body_present": bool((body or "").strip()),
                        "declared_scripts": [], "declared_references": [],
                        "disk_scripts": [], "disk_references": [],
                        "missing": [], "orphaned": []},
            "scripts": [], "references": [],
            "error": f"health probe timed out after {_SKILL_HEALTH_TIMEOUT:g}s",
        }

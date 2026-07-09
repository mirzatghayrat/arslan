"""Read-only capability catalog. Orchestrator items ARE listed (transparency),
marked assignable: false."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.models import SkillPack, Tool, Toolset
from server.db.session import get_session
from server.registry.service import (
    skill_compatibility,
    skill_is_assignable,
    toolset_is_assignable,
)
from server.schemas import RegistryOut, SkillPackOut, ToolOut, ToolsetOut
from server.services import code_sandbox

router = APIRouter(dependencies=[Depends(require_auth)])


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

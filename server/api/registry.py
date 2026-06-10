"""Read-only capability catalog. Orchestrator items ARE listed (transparency),
marked assignable: false."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.models import SkillPack, Tool, Toolset
from server.db.session import get_session
from server.schemas import RegistryOut, SkillPackOut, ToolOut, ToolsetOut

router = APIRouter(dependencies=[Depends(require_auth)])

_ASSIGNABLE_STATUSES = ("wired", "registered")


def _assignable(tier: str, status: str) -> bool:
    return tier == "safe" and status in _ASSIGNABLE_STATUSES


@router.get("/registry", response_model=RegistryOut)
async def get_registry(session: AsyncSession = Depends(get_session)) -> RegistryOut:
    n = (await session.execute(select(func.count()).select_from(Toolset))).scalar_one()
    if n == 0:
        # Lazy seed: covers test clients whose ASGI transport skips lifespan.
        # Uses the request session so the data is visible in the same transaction.
        from server.registry.seeder import seed_registry_with

        await seed_registry_with(session)

    toolsets = (await session.execute(select(Toolset).order_by(Toolset.key))).scalars().all()
    tools = (await session.execute(select(Tool).order_by(Tool.key))).scalars().all()
    skills = (await session.execute(select(SkillPack).order_by(SkillPack.key))).scalars().all()

    by_ts: dict[str, list[ToolOut]] = {}
    for t in tools:
        by_ts.setdefault(t.toolset_key, []).append(
            ToolOut(key=t.key, description=t.description, tier=t.tier, status=t.status)
        )
    return RegistryOut(
        toolsets=[
            ToolsetOut(
                key=t.key, name=t.name, description=t.description, tier=t.tier,
                status=t.status, assignable=_assignable(t.tier, t.status),
                tools=by_ts.get(t.key, []),
            )
            for t in toolsets
        ],
        skills=[
            SkillPackOut(
                key=s.key, name=s.name, category=s.category, description=s.description,
                tier=s.tier, status=s.status, assignable=_assignable(s.tier, s.status),
            )
            for s in skills
        ],
    )

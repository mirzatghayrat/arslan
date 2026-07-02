"""designed-html-report seed skill: real body seeds from the SKILL.md file, the skill is
assignable through the registry choke point, and the document-producing default spawns
are equipped with it."""
import anyio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.registry.seeder as seeder
from server.db.models import Base, SkillPack
from server.registry.service import skill_is_assignable
from server.services.default_spawns import DEFAULT_SPAWNS


def _seeded_row(tmp_path) -> SkillPack:
    """Seed the real catalog (real seeds dir, no monkeypatch) into a scratch DB."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'s.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _run():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with m() as db:
            await seeder.seed_registry_with(db)
        async with m() as db:
            return (await db.execute(
                select(SkillPack).where(SkillPack.key == "designed-html-report"))).scalar_one()
    return anyio.run(_run)


def test_seeds_with_real_body_and_is_assignable(tmp_path):
    row = _seeded_row(tmp_path)
    # Non-empty body carrying the raw-document output rule (the frontend HTML card only
    # triggers when the whole message starts with <!DOCTYPE html> — no fences).
    assert row.body and "<!DOCTYPE html>" in row.body
    assert "design.md" in row.body            # rule 1: project design spec overrides
    assert skill_is_assignable(row.tier, row.status, row.body)


def test_document_producing_defaults_equip_it():
    by_name = {s["name"]: s for s in DEFAULT_SPAWNS}
    for name in ("Research Analyst", "Financial Research Analyst",
                 "Content & Copywriter", "Deck Master"):
        assert "designed-html-report" in by_name[name]["equipment"]["skills"], name

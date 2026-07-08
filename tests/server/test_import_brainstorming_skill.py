"""PA-5: scripts/import_brainstorming_skill.py — idempotent equip of the seeded
brainstorming skill (adapted from obra/superpowers, MIT) onto Deck Master + the
research spawns. Row shape must match the existing user-granted skill rows
(kind='skill', grant='permanent', granted_by='user')."""
import importlib.util
import sys
from pathlib import Path

import anyio
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import Base, SkillPack, Spawn, SpawnCapability

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "import_brainstorming_skill.py"
_spec = importlib.util.spec_from_file_location("import_brainstorming_skill", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("import_brainstorming_skill", _mod)
_spec.loader.exec_module(_mod)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def maker(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'pa5.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with m() as db:
            for name in ("Deck Master", "Research Analyst",
                         "Financial Research Analyst", "Coding Assistant"):
                db.add(Spawn(name=name, domain_category="general", system_prompt="x"))
            await db.commit()

    anyio.run(_setup)
    return m


async def test_equips_three_spawns_with_user_grant_shape(maker):
    async with maker() as db:
        res = await _mod.ensure_brainstorming_equipped(db)

    # pack row exists (recreated from the seed catalog + seeds/ SKILL.md)
    assert res["pack_created"] is True
    assert res["missing_spawns"] == []
    assert {n for _, n in res["equipped"]} == set(_mod.TARGET_SPAWN_NAMES)

    async with maker() as db:
        pack = await db.get(SkillPack, "brainstorming")
        assert pack is not None
        assert pack.category == "collaboration"
        assert pack.tier == "safe" and pack.status == "registered"
        # seeded body, not invented: carries the required method sections
        assert "## Trigger" in (pack.body or "") and "## 决策规则" in (pack.body or "")

        caps = (await db.execute(
            select(SpawnCapability).where(SpawnCapability.ref_key == "brainstorming")
        )).scalars().all()
        assert len(caps) == 3
        for c in caps:
            assert (c.kind, c.grant, c.granted_by, c.expires_turn) == (
                "skill", "permanent", "user", None)
        # only the named targets, never e.g. Coding Assistant
        names = {(await db.get(Spawn, c.spawn_id)).name for c in caps}
        assert names == set(_mod.TARGET_SPAWN_NAMES)


async def test_rerun_is_a_noop(maker):
    async with maker() as db:
        await _mod.ensure_brainstorming_equipped(db)
    async with maker() as db:
        res2 = await _mod.ensure_brainstorming_equipped(db)

    assert res2["pack_created"] is False
    assert res2["equipped"] == []
    assert {n for _, n in res2["already"]} == set(_mod.TARGET_SPAWN_NAMES)

    async with maker() as db:
        caps = (await db.execute(
            select(SpawnCapability).where(SpawnCapability.ref_key == "brainstorming")
        )).scalars().all()
        assert len(caps) == 3  # no duplicates


async def test_missing_spawn_reported_not_fabricated(maker):
    async with maker() as db:
        await db.execute(
            Spawn.__table__.delete().where(Spawn.name == "Deck Master"))
        await db.commit()
    async with maker() as db:
        res = await _mod.ensure_brainstorming_equipped(db)
    assert res["missing_spawns"] == ["Deck Master"]
    assert {n for _, n in res["equipped"]} == {"Research Analyst", "Financial Research Analyst"}

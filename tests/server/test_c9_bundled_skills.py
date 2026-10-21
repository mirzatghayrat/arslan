"""C9a (docs/plans/0162/C9-bundled-skills-mcp-catalog.md, U13 item 3): Arslan ships two skills,
designed-html-report and skill-creator, from arslan/skills/bundled/. An upgraded database loses the
other bundled rows on boot and keeps a user's skill under a retired key (D7)."""
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import arslan.skills
from server.db.models import Base, SkillPack
from server.registry import seeder
from server.registry.seed_catalog import SKILLS

BUNDLED = {"designed-html-report", "skill-creator"}


@pytest_asyncio.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 's.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


def _row(key: str, category: str) -> SkillPack:
    return SkillPack(key=key, name=key, category=category, description="d", tier="safe", status="registered",
                     body="## Trigger\nx")


def test_two_skills_ship_and_each_has_its_files():
    assert {row[0] for row in SKILLS} == BUNDLED
    bundled = Path(arslan.skills.__file__).parent / "bundled"
    assert {p.name for p in bundled.iterdir() if p.is_dir()} == BUNDLED
    assert all(seeder._skill_body(key) for key in BUNDLED)
    assert not (Path(arslan.skills.__file__).parents[1] / "spawn" / "seeds").exists()


def test_every_skill_that_used_to_ship_is_retired():
    # The 53 keys the catalog held on v0.1.62 besides the two kept; spot-checked by name too.
    retired = set(seeder.RETIRED_SKILL_KEYS)
    assert BUNDLED.isdisjoint(retired)
    assert {"brainstorming", "humanizer", "deck-authoring", "claude-code", "spike", "frontend-design",
            "architecture-diagram", "plan"} <= retired


@pytest.mark.asyncio
async def test_an_upgraded_database_keeps_two_bundled_skills_and_the_users_own(db):
    db.add_all([_row("humanizer", "creative"), _row("plan", "software-development"),   # old bundled rows
                _row("brainstorming", "imported")])                                  # the user's, same key
    await db.commit()
    await seeder.seed_registry_with(db)
    db.expire_all()
    keys = set((await db.execute(select(SkillPack.key))).scalars())
    assert keys == BUNDLED | {"brainstorming"}
    for key in BUNDLED:
        assert (await db.get(SkillPack, key)).body, key


def test_skill_creator_carries_its_apache_provenance():
    """The user's decision (2026-10-21): Arslan's adaptation stays, with Apache-2.0 §4 met — the licence
    beside it (upstream's file at dbd4588f), a note in the changed file, the copyright line kept."""
    folder = Path(arslan.skills.__file__).parent / "bundled" / "skill-creator"
    licence = (folder / "LICENSE.txt").read_text()
    assert "Apache License" in licence and "Copyright 2026 Anthropic, PBC." in licence
    body = seeder._skill_body("skill-creator")
    assert body.startswith("> Adapted from Anthropic's skill-creator (Apache-2.0), github.com/anthropics/skills "
                           "@ dbd4588f, skills/skill-creator.")
    notices = (Path(arslan.skills.__file__).parents[2] / "THIRD_PARTY_NOTICES.md").read_text()
    assert "Copyright 2026 Anthropic, PBC." in notices and "dbd4588f9e1033efb41dad4bef2f7947c8993d44" in notices

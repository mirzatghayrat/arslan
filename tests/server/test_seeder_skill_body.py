import anyio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.registry.seeder as seeder
from server.db.models import Base, SkillPack


_SKILL_MD = """---
name: systematic-debugging
description: 4-phase root cause analysis.
version: 0.1.0
---

## Trigger
When a bug or unexpected behavior appears.

## 决策规则
- Reproduce first; then isolate.
"""


def test_skill_body_reads_file(tmp_path, monkeypatch):
    (tmp_path / "systematic-debugging").mkdir()
    (tmp_path / "systematic-debugging" / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")
    monkeypatch.setattr(seeder, "_SEEDS_DIR", tmp_path)
    assert "## Trigger" in seeder._skill_body("systematic-debugging")
    assert seeder._skill_body("no-such-key") is None


def test_seed_populates_body_from_file(tmp_path, monkeypatch):
    (tmp_path / "systematic-debugging").mkdir()
    (tmp_path / "systematic-debugging" / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")
    monkeypatch.setattr(seeder, "_SEEDS_DIR", tmp_path)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'s.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _run():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with m() as db:
            await seeder.seed_registry_with(db)
        async with m() as db:
            sd = (await db.execute(select(SkillPack).where(SkillPack.key == "systematic-debugging"))).scalar_one()
            other = (await db.execute(select(SkillPack).where(SkillPack.key == "humanizer"))).scalar_one()
        return sd.body, other.body
    body, other_body = anyio.run(_run)
    assert body is not None and "## 决策规则" in body     # has a file → body set
    assert other_body is None                              # no file (this task) → body NULL


def test_skill_body_bad_frontmatter_skips(tmp_path, monkeypatch):
    (tmp_path / "systematic-debugging").mkdir()
    (tmp_path / "systematic-debugging" / "SKILL.md").write_text("not valid frontmatter at all", encoding="utf-8")
    monkeypatch.setattr(seeder, "_SEEDS_DIR", tmp_path)
    assert seeder._skill_body("systematic-debugging") is None   # parse fail → None, no raise

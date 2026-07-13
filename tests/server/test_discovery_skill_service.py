import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, SkillPack


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'dsk.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


async def test_generate_skill_draft_readonly(maker, monkeypatch):
    from server.services import discovery_service as ds, github_eval, skill_suggest
    async def fr(o, r): return {"full_name": "o/r", "html_url": "u", "description": "d", "topics": []}
    async def frd(o, r): return "readme"
    async def gen(meta, readme): return {"name": "T", "category": "research",
        "description": "d", "body": "## Trigger\nx\n## 决策规则\ny"}
    monkeypatch.setattr(github_eval, "fetch_repo", fr)
    monkeypatch.setattr(github_eval, "fetch_readme", frd)
    monkeypatch.setattr(skill_suggest, "generate_skill", gen)
    out = await ds.generate_skill_draft("o", "r")
    async with maker() as s:
        rows = (await s.execute(select(SkillPack))).scalars().all()
    assert out["repo"]["full_name"] == "o/r" and out["skill"]["name"] == "T"
    assert rows == []                                   # read-only, nothing persisted


async def test_create_skill_persists_safe_registered(maker):
    from server.services import discovery_service as ds
    body = "## Trigger\nx\n## 决策规则\ny"
    created = await ds.create_skill("o/r", "My Tech", "research", "d", body)
    async with maker() as s:
        row = (await s.execute(select(SkillPack).where(SkillPack.key == created["key"]))).scalar_one()
    assert created["key"].startswith("gh-")
    assert row.tier == "safe" and row.status == "registered"
    assert row.body == body and row.name == "My Tech"


async def test_create_skill_missing_sections_raises(maker):
    from server.services import discovery_service as ds
    with pytest.raises(ValueError):
        await ds.create_skill("o/r", "n", "c", "d", "no sections here")


async def test_create_skill_upserts_by_key(maker):
    from server.services import discovery_service as ds
    body = "## Trigger\nx\n## 决策规则\ny"
    a = await ds.create_skill("o/r", "n1", "c", "d", body)
    b = await ds.create_skill("o/r", "n2", "c", "d", body)   # same repo → same key → update
    async with maker() as s:
        rows = (await s.execute(select(SkillPack).where(SkillPack.key.like("gh-%")))).scalars().all()
    assert a["key"] == b["key"] and len(rows) == 1 and rows[0].name == "n2"

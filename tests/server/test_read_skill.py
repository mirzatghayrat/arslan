import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, SkillPack

pytestmark = pytest.mark.asyncio


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'s.db'}")
    m = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)

    async def _s():
        async with eng.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        async with m() as db:
            db.add(SkillPack(key="writing-plans", name="Writing Plans", category="dev",
                             description="d", tier="safe", status="registered",
                             body="## First\nalpha\n## Second\n" + "beta " * 4000))
            db.add(SkillPack(key="short", name="Short", category="dev", description="d",
                             tier="safe", status="registered", body="tiny"))
            await db.commit()

    anyio.run(_s)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


async def test_full_short_returns_whole(seeded):
    from server.registry.executors import ReadSkillExecutor
    out = await ReadSkillExecutor().execute({"key": "short"})
    assert out["ok"] and "tiny" in out["body"]


async def test_full_long_caps_and_hints(seeded):
    from server.registry.executors import ReadSkillExecutor
    out = await ReadSkillExecutor().execute({"key": "writing-plans"})
    assert out["ok"] and len(out["body"]) <= 8600
    assert "按章节读取" in out["body"] and "## Second" in out["body"]


async def test_section_returns_only_that(seeded):
    from server.registry.executors import ReadSkillExecutor
    out = await ReadSkillExecutor().execute({"key": "writing-plans", "section": "## First"})
    assert out["ok"] and "alpha" in out["body"] and "beta" not in out["body"]


async def test_unknown_key_fails(seeded):
    from server.registry.executors import ReadSkillExecutor
    out = await ReadSkillExecutor().execute({"key": "../etc/passwd"})
    assert out["ok"] is False

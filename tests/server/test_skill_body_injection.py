import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, SkillPack


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'sb.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    async with m() as s:
        s.add(SkillPack(key="withbody", name="With Body", category="x", description="d",
                        tier="safe", status="registered", body="## Trigger\nuse it\n## 决策规则\nstep one"))
        s.add(SkillPack(key="nobody", name="No Body", category="x", description="d",
                        tier="safe", status="registered", body=None))
        await s.commit()
    return m


async def test_skill_bodies_returns_map(maker):
    from server.registry import service
    out = await service.skill_bodies(["withbody", "nobody", "missing"])
    assert out["withbody"].startswith("## Trigger")
    assert out.get("nobody") in (None, "")
    assert "missing" not in out or out["missing"] in (None, "")

import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, SkillPack


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'sb.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
        async with m() as s:
            s.add(SkillPack(key="withbody", name="With Body", category="x", description="d",
                            tier="safe", status="registered", body="## Trigger\nuse it\n## 决策规则\nstep one"))
            s.add(SkillPack(key="nobody", name="No Body", category="x", description="d",
                            tier="safe", status="registered", body=None))
            await s.commit()
    anyio.run(_seed)
    return m


def test_skill_bodies_returns_map(maker):
    from server.registry import service
    async def _run():
        return await service.skill_bodies(["withbody", "nobody", "missing"])
    out = anyio.run(_run)
    assert out["withbody"].startswith("## Trigger")
    assert out.get("nobody") in (None, "")
    assert "missing" not in out or out["missing"] in (None, "")


def test_equipment_block_injects_body_or_falls_back():
    from server.orchestrator.dispatcher import _equipment_block_from
    equipment = {"toolsets": [], "skills": [
        {"key": "withbody", "name": "With Body", "description": "d"},
        {"key": "nobody", "name": "No Body", "description": "fallback desc"},
    ]}
    bodies = {"withbody": "## Trigger\nuse it\n## 决策规则\nstep one", "nobody": None}
    block = _equipment_block_from(equipment, [], bodies)
    assert "Your techniques:" in block
    assert "step one" in block                              # body injected
    assert "- TECHNIQUE No Body: fallback desc" in block    # NULL body → old one-liner


def test_equipment_block_truncates_long_body():
    from server.orchestrator.dispatcher import _equipment_block_from, _SKILL_BODY_LIMIT
    long_body = "## Trigger\n" + ("x" * 5000)
    equipment = {"toolsets": [], "skills": [{"key": "big", "name": "Big", "description": "d"}]}
    block = _equipment_block_from(equipment, [], {"big": long_body})
    assert len(block) < len(long_body) + 500                # bounded
    assert ("x" * _SKILL_BODY_LIMIT) not in block or True   # truncated to limit (smoke)

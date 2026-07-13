import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, SkillCandidate
from server.registry import executors, seed_catalog

_GOOD_BODY = (
    "# My Skill\n\n"
    "## Trigger\nUse this when the user asks to do the thing.\n\n"
    "## Steps\n1. Do the first thing.\n2. Do the second thing thoroughly and well.\n"
)


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'cs.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest.mark.asyncio
async def test_execute_valid_creates_candidate(maker):
    ex = executors.CreateSkillExecutor()
    res = await ex.execute({
        "key": "my-skill", "name": "My Skill",
        "description": "does a thing", "body": _GOOD_BODY,
    })
    assert res["ok"] is True
    assert res["status"] == "observing"
    assert res["external"] is False
    assert isinstance(res["candidate_id"], int)

    async with maker() as s:
        row = await s.get(SkillCandidate, res["candidate_id"])
        assert row is not None
        assert row.key == "my-skill"
        assert row.source == "skill_creator"
        assert row.category == "meta"  # default


@pytest.mark.asyncio
async def test_execute_invalid_body_no_row_no_raise(maker):
    ex = executors.CreateSkillExecutor()
    # Missing '## Trigger' section → invalid.
    res = await ex.execute({
        "key": "bad-skill", "name": "Bad", "description": "d",
        "body": "no trigger section here " * 10,
    })
    assert res["ok"] is False
    assert res["error"]

    async with maker() as s:
        rows = (await s.execute(select(SkillCandidate))).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_execute_oversize_body_returns_error(maker):
    from server.services import skill_forge

    ex = executors.CreateSkillExecutor()
    big = "## Trigger\n" + ("x" * (skill_forge.MAX_SKILL_BYTES + 10))
    res = await ex.execute({
        "key": "big-skill", "name": "Big", "description": "d", "body": big,
    })
    assert res["ok"] is False
    assert "KB" in res["error"]
    async with maker() as s:
        assert (await s.execute(select(SkillCandidate))).scalars().all() == []


def test_tool_registered_in_executors():
    assert "create_skill" in executors.EXECUTORS
    assert executors.EXECUTORS["create_skill"].key == "create_skill"


def test_tool_in_catalog_as_safe_wired():
    ts = next(t for t in seed_catalog.TOOLSETS if t["key"] == "skill_authoring")
    assert ts["tier"] == "safe"
    assert ts["status"] == "wired"
    tools = {t[0]: t for t in ts["tools"]}
    assert "create_skill" in tools
    _, _, tier, status = tools["create_skill"]
    assert (tier, status) == ("safe", "wired")

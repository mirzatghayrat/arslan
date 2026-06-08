"""Orchestrator ORM models + reserved leveling columns."""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db.models import (
    ArslanMessage,
    ArslanSummary,
    Base,
    Feedback,
    RouterDecision,
    Spawn,
    UserFact,
)


@pytest_asyncio.fixture
async def session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'o.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_arslan_message_display_vs_content(session):
    row = ArslanMessage(
        conversation_id="main",
        role="spawn_summary",
        content="[beauty-guru] draft 3 posts -> delivered",
        display_content="1. Vitamin C...\n2. Barrier...\n3. Dupe test...",
        spawn_id=None,
    )
    session.add(row)
    await session.commit()
    fetched = (await session.execute(select(ArslanMessage))).scalar_one()
    assert fetched.content.startswith("[beauty-guru]")
    assert "Vitamin C" in fetched.display_content


@pytest.mark.asyncio
async def test_user_fact_defaults(session):
    f = UserFact(content="prefers metric units")
    session.add(f)
    await session.commit()
    got = (await session.execute(select(UserFact))).scalar_one()
    assert got.source == "auto"
    assert got.sensitive is False


@pytest.mark.asyncio
async def test_router_decision_and_summary(session):
    session.add(RouterDecision(conversation_id="main", user_message="hi", action="answer"))
    session.add(ArslanSummary(conversation_id="main", summary="...", up_to_message_id=5))
    await session.commit()
    assert (await session.execute(select(RouterDecision))).scalar_one().action == "answer"
    assert (await session.execute(select(ArslanSummary))).scalar_one().up_to_message_id == 5


@pytest.mark.asyncio
async def test_reserved_leveling_columns(session):
    spawn = Spawn(
        name="beauty-guru",
        domain_category="content-creator",
        capabilities=["content-generation"],
        system_prompt="You are a beauty expert.",
    )
    session.add(spawn)
    await session.commit()
    await session.refresh(spawn)
    assert spawn.level == 1
    assert spawn.memory_facts == []

    fb = Feedback(spawn_id=spawn.id, session_id="s", user_action="thumbs_up", edits={})
    session.add(fb)
    await session.commit()
    await session.refresh(fb)
    assert fb.quality_signal is None  # reserved, unset by default

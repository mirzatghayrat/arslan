"""P0-a: facts_text injection cap (count/token) + fail-closed sensitive isolation."""
import inspect

import pytest
import pytest_asyncio
from sqlalchemy import text as sa_text

from server.db import session as db_session
from server.orchestrator import memory


@pytest_asyncio.fixture
async def db_env(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from server.db.models import Base
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'f.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    yield maker
    await engine.dispose()


async def _add(maker, content, *, sensitive=False, confidence=0.6):
    from server.db.models import UserFact
    async with maker() as db:
        db.add(UserFact(content=content, sensitive=sensitive, confidence=confidence))
        await db.commit()


@pytest.mark.asyncio
async def test_default_is_fail_closed(db_env):
    # 用户修正锚定:默认 include_sensitive=False
    sig = inspect.signature(memory.facts_text)
    assert sig.parameters["include_sensitive"].default is False
    await _add(db_env, "普通事实")
    await _add(db_env, "私密事实", sensitive=True)
    out = await memory.facts_text()          # 裸调用 = spawn 语义
    assert "普通事实" in out and "私密事实" not in out


@pytest.mark.asyncio
async def test_host_privilege_is_explicit(db_env):
    await _add(db_env, "私密事实", sensitive=True)
    out = await memory.facts_text(include_sensitive=True)
    assert "私密事实" in out


@pytest.mark.asyncio
async def test_count_cap_40_deterministic(db_env):
    for i in range(60):
        await _add(db_env, f"事实{i:02d}")
    out1 = await memory.facts_text()
    out2 = await memory.facts_text()
    assert out1 == out2                                     # 确定性
    assert sum(1 for line in out1.splitlines() if line.startswith("- ")) == 40


@pytest.mark.asyncio
async def test_token_budget_cuts_before_count(db_env):
    for i in range(10):
        await _add(db_env, "长" * 200 + str(i))             # 每条 ~200 CJK tok
    out = await memory.facts_text()
    n = sum(1 for line in out.splitlines() if line.startswith("- "))
    assert 1 <= n < 10                                      # 预算 600 截断,但至少 1 条


@pytest.mark.asyncio
async def test_confidence_priority_over_recency(db_env):
    await _add(db_env, "高置信旧事实", confidence=0.95)
    for i in range(45):
        await _add(db_env, f"低置信新事实{i}", confidence=0.3)
    out = await memory.facts_text()
    assert "高置信旧事实" in out                            # 高置信不被 40 条上限挤掉


@pytest.mark.asyncio
async def test_null_fields_do_not_crash(db_env):
    # I4:raw insert 可产生 NULL confidence/created_at,热路径排序不许崩
    async with db_env() as db:
        await db.execute(sa_text(
            "INSERT INTO user_facts (content, sensitive) VALUES ('裸行', 0)"))
        await db.commit()
    await _add(db_env, "正常行")
    out = await memory.facts_text()
    assert "裸行" in out and "正常行" in out


@pytest.mark.asyncio
async def test_empty_returns_empty_string(db_env):
    assert await memory.facts_text() == ""


@pytest.mark.asyncio
async def test_render_order_is_id_ascending(db_env):
    await _add(db_env, "乙", confidence=0.9)
    await _add(db_env, "甲", confidence=0.95)
    out = await memory.facts_text()
    assert out.index("乙") < out.index("甲")                # 选取按置信,渲染按 id 升序

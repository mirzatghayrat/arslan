import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn, SpawnCapability


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'bs.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        from server.registry.seeder import seed_registry
        monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
        await seed_registry()
        async with m() as s:
            s.add(Spawn(id=7, name="小美", domain_category="content", system_prompt="You are a beauty expert."))
            s.add(SpawnCapability(spawn_id=7, kind="toolset", ref_key="web_search_scraping"))
            await s.commit()
    anyio.run(_seed)
    return m


def test_build_spawn_system_includes_equipment_and_guidance(maker):
    from server.orchestrator.dispatcher import build_spawn_system
    async def _run():
        async with maker() as s:
            spawn = await s.get(Spawn, 7)
        return await build_spawn_system(spawn, retrieval_query="do X", current_turn=1)
    out = anyio.run(_run)
    system, wired = out
    assert "web_search" in system                 # equipment block lists wired tools
    assert "USE YOUR TOOLS" in system or "fabricate" in system   # tool guidance / anti-fab present
    assert "You are a beauty expert." in system   # base persona
    assert any(t["key"] == "web_search" for t in wired)


def test_build_spawn_system_has_language_directive(maker):
    """The spawn must be told to reply in the user's CURRENT language, and that
    'Known facts about the user' are background — NOT a language instruction.
    Regression guard for the Uyghur-drift bug: identity facts like '用户是甲语母语者…
    不需要中文翻译' were read as an order to answer in Uyghur in the sandbox."""
    from server.orchestrator.dispatcher import build_spawn_system
    async def _run():
        async with maker() as s:
            spawn = await s.get(Spawn, 7)
        return await build_spawn_system(spawn, retrieval_query="x", current_turn=1)
    system, _ = anyio.run(_run)
    low = system.lower()
    assert "reply in the same language as the user" in low          # follow-the-user's-language
    assert "not instructions about what language" in low            # facts are background, not a lang order


def test_build_spawn_system_has_html_delivery_guardrail(maker):
    """HX-5 B2(a): every spawn is told how to deliver full HTML documents — brief intro
    then the document body, relying on the system's auto-packaging (HX-2 artifact
    channel); never dump long code as chat prose or fence the full document."""
    from server.orchestrator.dispatcher import build_spawn_system
    async def _run():
        async with maker() as s:
            spawn = await s.get(Spawn, 7)
        return await build_spawn_system(spawn, retrieval_query="x", current_turn=1)
    system, _ = anyio.run(_run)
    assert "系统会自动将完整 HTML 打包为可下载工件" in system
    assert "不要用代码围栏包裹完整文档" in system


def test_build_spawn_system_override(maker):
    from server.orchestrator.dispatcher import build_spawn_system
    async def _run():
        async with maker() as s:
            spawn = await s.get(Spawn, 7)
        return await build_spawn_system(spawn, retrieval_query="x", current_turn=1, system_prompt_override="OVERRIDE PERSONA")
    system, _ = anyio.run(_run)
    assert "OVERRIDE PERSONA" in system and "You are a beauty expert." not in system

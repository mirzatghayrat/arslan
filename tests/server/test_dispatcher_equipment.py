"""Dispatch injects an equipment block; zero-equipment spawns get the no-tools clause."""
import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn, SpawnCapability


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'de.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        from server.registry.seeder import seed_registry

        monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
        await seed_registry()
        async with m() as s:
            s.add(Spawn(id=7, name="小美", domain_category="content",
                        system_prompt="You are a beauty expert."))
            s.add(Spawn(id=8, name="plain", domain_category="other",
                        system_prompt="You are plain."))
            s.add(Spawn(id=9, name="artist", domain_category="creative",
                        system_prompt="You are an image artist."))
            s.add(SpawnCapability(spawn_id=7, kind="toolset", ref_key="web_search_scraping"))
            s.add(SpawnCapability(spawn_id=7, kind="skill", ref_key="baoyu-infographic"))
            s.add(SpawnCapability(spawn_id=9, kind="toolset", ref_key="image_generation"))
            await s.commit()

    anyio.run(_seed)
    return m


@pytest.mark.asyncio
async def test_equipped_spawn_system_lists_equipment(maker, monkeypatch):
    from server.orchestrator import dispatcher, tool_loop

    captured = {}

    class _A:
        async def chat_stream(self, system, user, history=None, tools=None, temperature=0.7):
            captured["system"] = system
            yield "ok"

        async def chat(self, system, user, history=None, **kw):
            captured["system"] = system

            class _R:
                content = "all done"

            return _R()

    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _A())
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _A())
    await dispatcher.dispatch("main", spawn_id=7, task_brief="do X")
    s = captured["system"]
    assert "web_search" in s and "web_extract" in s
    assert "baoyu-infographic" in s
    assert "NO other tools" in s
    assert "escalate" in s.lower()


@pytest.mark.asyncio
async def test_unequipped_spawn_gets_universal_baseline(maker, monkeypatch):
    """Every spawn now has the universal safe baseline (web_search/web_extract/render_chart)
    and runs through the tool loop — the legacy zero-tool path is retired."""
    from server.orchestrator import dispatcher, tool_loop

    captured = {}

    class _A:
        async def chat_stream(self, system, user, history=None, tools=None, temperature=0.7):
            captured["system"] = system
            yield "ok"

    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _A())
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _A())
    await dispatcher.dispatch("main", spawn_id=8, task_brief="do Y")
    s = captured["system"]
    assert "render_chart" in s and "web_search" in s   # baseline tools listed in the equipment block


@pytest.mark.asyncio
async def test_not_yet_live_toolset_appears_in_system(maker, monkeypatch):
    """Spawn equipped with a registered (not wired) toolset gets '(not yet live)' label.

    Spawn 9 is equipped (image_generation) → has_equipment → dispatch resolves wired tools,
    which now always include the universal safe tool render_chart → the spawn runs through the
    tool loop. Stub tool_loop's adapter (not the legacy dispatcher one) so no real LLM call fires.
    """
    from server.orchestrator import dispatcher, tool_loop

    captured = {}

    class _A:
        async def chat_stream(self, system, user, history=None, tools=None, temperature=0.7):
            captured["system"] = system
            yield "ok"

    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _A())
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _A())
    await dispatcher.dispatch("main", spawn_id=9, task_brief="draw something")
    s = captured["system"]
    assert "(not yet live)" in s
    assert "Image Generation" in s


@pytest.mark.asyncio
async def test_spawn_prompt_has_tool_use_guidance(maker, monkeypatch):
    """The spawn system prompt must tell it to USE its tools (emit the tool call), not
    narrate a tool call as text nor fabricate data + return code. Regression for spawns
    that printed matplotlib code / 'STEP 1 调用 web_search' instead of calling tools."""
    from server.orchestrator import dispatcher, tool_loop

    captured = {}

    class _A:
        async def chat_stream(self, system, user, history=None, tools=None, temperature=0.7):
            captured["system"] = system
            yield "ok"

    monkeypatch.setattr(dispatcher, "_get_adapter", lambda: _A())
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _A())
    await dispatcher.dispatch("main", spawn_id=8, task_brief="chart tesla prices this week")
    s = captured["system"]
    assert "render_chart" in s
    # the guidance must explicitly forbid narrating / fabricating-then-coding and require emitting the tool call
    assert "ACT" in s or "emit the tool call" in s
    assert "never" in s.lower()

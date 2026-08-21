"""The LAN scan is offered only when the user turned it on (spec P3a).

Same posture as the workspace tools: OFF by default, and when off the tool is
absent from the list rather than present-and-refusing. Discovery is a proposal
surface, so it needs no per-use confirmation — but it does need to have been
switched on once, deliberately, because scanning a network is a thing a person
should choose rather than discover having happened.
"""
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Setting

KEY = "scan_local_network"


async def _wire(tmp_path, monkeypatch, *, enabled: str | None):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'lan.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    if enabled is not None:
        async with m() as s:
            s.add(Setting(key="lan_discovery_enabled", value=enabled))
            await s.commit()
    return engine


@pytest_asyncio.fixture
async def keys_off(tmp_path, monkeypatch):
    engine = await _wire(tmp_path, monkeypatch, enabled=None)
    from server.orchestrator.arslan import _arslan_tools
    yield {t["key"] for t in await _arslan_tools()}
    await engine.dispose()


@pytest_asyncio.fixture
async def keys_on(tmp_path, monkeypatch):
    engine = await _wire(tmp_path, monkeypatch, enabled="true")
    from server.orchestrator.arslan import _arslan_tools
    yield {t["key"] for t in await _arslan_tools()}
    await engine.dispose()


async def test_default_off_means_the_tool_is_absent(keys_off):
    assert KEY not in keys_off
    assert "web_search" in keys_off            # unrelated tools unaffected


async def test_enabling_offers_it(keys_on):
    assert KEY in keys_on


async def test_the_description_says_it_only_looks(keys_on):
    """The model must not think this connects to anything."""
    from server.orchestrator.arslan import _arslan_tools
    tools = {t["key"]: t for t in await _arslan_tools()}
    desc = tools[KEY]["description"].lower()
    assert "read-only" in desc or "does not connect" in desc


async def test_explicitly_false_is_off(tmp_path, monkeypatch):
    engine = await _wire(tmp_path, monkeypatch, enabled="false")
    from server.orchestrator.arslan import _arslan_tools
    keys = {t["key"] for t in await _arslan_tools()}
    assert KEY not in keys
    await engine.dispose()


async def test_the_executor_is_registered():
    from server.registry.executors import EXECUTORS
    assert KEY in EXECUTORS


async def test_the_tool_refuses_when_the_setting_is_off(tmp_path, monkeypatch):
    """Belt and braces: the executor checks too, so a stale tool list or a
    direct call cannot scan a network the user never opted into."""
    engine = await _wire(tmp_path, monkeypatch, enabled=None)
    from server.registry.lan_tools import ScanLocalNetworkExecutor
    out = await ScanLocalNetworkExecutor().execute({})
    assert out["ok"] is False and "settings" in out["error"].lower()
    await engine.dispose()

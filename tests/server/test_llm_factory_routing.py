import pytest
from server.db import session as db_session
from server.db.models import Base
from server.services import llm_factory, provider_config_service as pcs, settings_service


@pytest.fixture
async def db():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    eng = create_async_engine("sqlite+aiosqlite://")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    db_session.AsyncSessionLocal = async_sessionmaker(eng, expire_on_commit=False)
    async with db_session.AsyncSessionLocal() as s:
        a = await pcs.add_config(s, label="A", provider="anthropic", model="claude-sonnet-4-6",
                                 base_url="", api_key="sk-anthropic")
        await pcs.add_config(s, label="B", provider="deepseek", model="deepseek-chat",
                             base_url="", api_key="sk-deepseek")
        await pcs.set_primary(s, a["id"])
        await settings_service.update_settings(s, {"llm_strategy": "cost", "language": "en"})
    yield


async def test_worker_role_routes_to_cheapest_under_cost(db):
    adapter = await llm_factory.build_adapter(role="execute")
    assert adapter.model == "deepseek-chat"


async def test_judgment_role_stays_primary(db):
    adapter = await llm_factory.build_adapter(role="router")
    assert adapter.model == "claude-sonnet-4-6"

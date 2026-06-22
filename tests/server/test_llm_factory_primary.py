import pytest
from server.db import session as db_session
from server.db.models import Base
from server.services import llm_factory, provider_config_service as pcs


@pytest.fixture
async def db():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    eng = create_async_engine("sqlite+aiosqlite://")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    db_session.AsyncSessionLocal = async_sessionmaker(eng, expire_on_commit=False)
    async with db_session.AsyncSessionLocal() as s:
        await pcs.add_config(s, label="A", provider="deepseek", model="deepseek-chat",
                             base_url="", api_key="sk-key-1111")
        b = await pcs.add_config(s, label="B", provider="qwen", model="qwen-max",
                                 base_url="", api_key="sk-key-2222")
        await pcs.set_primary(s, b["id"])
    yield


async def test_build_adapter_uses_primary(db):
    adapter = await llm_factory.build_adapter()
    assert adapter.model == "qwen-max"
    assert adapter.api_key == "sk-key-2222"


async def test_role_ignored_in_phase_a(db):
    adapter = await llm_factory.build_adapter(role="execute")
    assert adapter.model == "qwen-max"

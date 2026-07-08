import pytest
from server.db import session as db_session
from server.db.models import Base
from server.services import provider_config_service as svc


@pytest.fixture
async def db():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    eng = create_async_engine("sqlite+aiosqlite://")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    db_session.AsyncSessionLocal = async_sessionmaker(eng, expire_on_commit=False)
    async with db_session.AsyncSessionLocal() as s:
        yield s


async def test_add_lists_masked_and_first_is_primary(db):
    await svc.add_config(db, label="A", provider="deepseek", model="deepseek-chat",
                         base_url="", api_key="sk-aaaa1111bbbb")
    rows = await svc.list_configs(db)
    assert len(rows) == 1
    assert rows[0]["is_primary"] is True
    assert rows[0]["api_key"].endswith("bbbb") and "..." in rows[0]["api_key"]


async def test_set_primary_is_exclusive(db):
    a = await svc.add_config(db, label="A", provider="deepseek", model="deepseek-chat",
                             base_url="", api_key="sk-aaaa1111bbbb")
    b = await svc.add_config(db, label="B", provider="qwen", model="qwen-max",
                             base_url="", api_key="sk-bbbb2222cccc")
    await svc.set_primary(db, b["id"])
    rows = {r["id"]: r["is_primary"] for r in await svc.list_configs(db)}
    assert rows[b["id"]] is True and rows[a["id"]] is False


async def test_update_skips_masked_key_echo(db):
    a = await svc.add_config(db, label="A", provider="deepseek", model="deepseek-chat",
                             base_url="", api_key="sk-aaaa1111bbbb")
    masked = (await svc.list_configs(db))[0]["api_key"]
    await svc.update_config(db, a["id"], label="A2", api_key=masked)
    assert await svc.get_decrypted_key(db, a["id"]) == "sk-aaaa1111bbbb"


async def test_list_for_routing_has_no_key(db):
    await svc.add_config(db, label="A", provider="deepseek", model="deepseek-chat",
                         base_url="", api_key="sk-aaaa1111bbbb")
    rows = await svc.list_for_routing(db)
    assert rows[0]["provider"] == "deepseek" and "api_key" not in rows[0]


async def test_delete_primary_promotes_survivor(db):
    a = await svc.add_config(db, label="A", provider="deepseek", model="deepseek-chat",
                             base_url="", api_key="sk-aaaa1111bbbb")
    b = await svc.add_config(db, label="B", provider="qwen", model="qwen-max",
                             base_url="", api_key="sk-bbbb2222cccc")
    await svc.delete_config(db, a["id"])           # a was primary
    rows = await svc.list_configs(db)
    assert len(rows) == 1 and rows[0]["id"] == b["id"] and rows[0]["is_primary"] is True

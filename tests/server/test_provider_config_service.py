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


async def test_key_status_distinguishes_set_unset_undecryptable(db):
    # Honest key state: a real key -> 'set'; an empty key -> 'unset'; a STORED-but-undecryptable
    # ciphertext (encrypted under a now-changed ARSLAN_SECRET_KEY) -> 'undecryptable'. The UI needs
    # this to show a truthful reason instead of a misleading "requires API key".
    from server.db.models import ProviderConfig
    await svc.add_config(db, label="A", provider="deepseek", model="deepseek-chat",
                         base_url="", api_key="sk-aaaa1111bbbb")           # decryptable
    await svc.add_config(db, label="B", provider="qwen", model="qwen-max",
                         base_url="", api_key="")                          # no key
    db.add(ProviderConfig(label="C", provider="deepseek", model="deepseek-chat",
                          api_key="gAAAAAB-not-valid-under-this-secret", is_primary=False))  # secret changed
    await db.commit()
    rows = {r["label"]: r for r in await svc.list_configs(db)}
    assert rows["A"]["key_status"] == "set"
    assert rows["B"]["key_status"] == "unset"
    assert rows["C"]["key_status"] == "undecryptable"
    assert rows["C"]["api_key"] == ""    # still masks to empty (unchanged display behavior)


async def test_count_undecryptable_keys(db):
    from server.db.models import ProviderConfig
    await svc.add_config(db, label="A", provider="deepseek", model="deepseek-chat",
                         base_url="", api_key="sk-aaaa1111bbbb")           # decryptable
    db.add(ProviderConfig(label="C", provider="deepseek", model="m", api_key="garbage-cipher"))
    db.add(ProviderConfig(label="D", provider="qwen", model="m2", api_key="also-garbage"))
    await db.commit()
    assert await svc.count_undecryptable_keys(db) == 2


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

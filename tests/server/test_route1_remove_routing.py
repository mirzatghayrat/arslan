"""ROUTE1 (v0.1.64, docs/plans/0164/ROUTE1-remove-routing.md): task routing is gone. Every role runs on the
conversation's own model, else the primary; there is no strategy, no score and no capability table. The compaction
and final-answer slots are gone (they follow the conversation's model); the router ("remembering facts") and vision
slots stay. Migration 0086 clears the stored strategy, the removed slots and every old pin, and asks Settings to say
so once.

User, 2026-11-03: 「我同意你的方案要删就直接删 别留遗留/垃圾代码」."""
import importlib.util

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, ConversationModel, ProviderConfig, Setting
from server.services import llm_factory, settings_service


@pytest_asyncio.fixture
async def db(monkeypatch):
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    from server import crypto
    monkeypatch.setenv("ARSLAN_ALLOW_INSECURE_SECRETS", "1")    # a test-only key under the public dev fallback
    key = crypto.encrypt("sk-test-not-a-real-key")       # a usable key, so a routing engine would be free to choose
    async with maker() as s:
        s.add(ProviderConfig(id=1, label="ds", provider="deepseek", model="deepseek-v4-flash", api_key=key, last_health="ok"))
        s.add(ProviderConfig(id=3, label="claude", provider="anthropic", model="claude-sonnet-5-5", api_key=key,
                             last_health="ok", is_primary=True))
        s.add(Setting(key="llm_strategy", value="cost"))      # a strategy stored before ROUTE1 is never read
        await s.commit()
        yield s
    await eng.dispose()


def test_the_routing_engine_is_gone():
    assert importlib.util.find_spec("arslan.llm.routing") is None
    assert "llm_strategy" not in settings_service._PLAIN_KEYS
    assert not hasattr(llm_factory, "build_synthesis_adapter")
    assert llm_factory.SLOT_KEYS == ("router_config_id", "vision_config_id")


@pytest.mark.parametrize("role", [None, "execute", "summarize", "draft", "router", "judge"])
async def test_every_role_runs_on_the_primary(db, role):
    adapter = await llm_factory.build_adapter(role=role)
    assert (adapter.report_provider, adapter.model) == ("anthropic", "claude-sonnet-5-5")


async def test_compaction_follows_the_conversations_model(db):
    from server.orchestrator import memory
    db.add(ConversationModel(conversation_id="c-picked", config_id=1, model="deepseek-v4-pro"))
    await db.commit()
    picked = await memory._get_adapter("c-picked")
    assert (picked.report_provider, picked.model) == ("deepseek", "deepseek-v4-pro")
    plain = await memory._get_adapter("c-none")
    assert (plain.report_provider, plain.model) == ("anthropic", "claude-sonnet-5-5")


async def test_the_settings_api_has_no_strategy_and_no_capability_endpoints(client):
    assert "llm_strategy" not in (await client.get("/api/v1/settings")).json()
    assert (await client.get("/api/v1/settings/suggest-primary")).status_code == 404
    assert (await client.get("/api/v1/settings/catalog")).status_code == 404


def _old_db(tmp_path, rows):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for key, value in rows.items():
            conn.execute(sa.insert(Setting.__table__).values(key=key, value=value))
    return engine


def _settings(conn) -> dict:
    return dict(conn.exec_driver_sql("SELECT key, value FROM settings").all())


CLEARED = ("llm_strategy", "compaction_config_id", "compaction_model", "synthesis_config_id", "synthesis_model",
           "router_config_id", "router_model", "vision_config_id", "vision_model")


def test_migration_0086_clears_the_strategy_the_removed_slots_and_every_pin_once(tmp_path):
    from server.db.migrations.versions import _0086_route1_remove_routing as m0086
    old = {"llm_strategy": "balanced", "compaction_config_id": "1", "synthesis_config_id": "1", "synthesis_model": "x",
           "router_config_id": "1", "vision_config_id": "1", "vision_model": "deepseek-v4-flash", "language": "zh"}
    engine = _old_db(tmp_path, old)
    with engine.begin() as conn:
        m0086.upgrade_sync(conn)
        after = _settings(conn)
    assert not set(CLEARED) & set(after), "the strategy, the removed slots and the old pins are gone"
    assert after["language"] == "zh", "nothing else is touched"
    assert after["model_roles_reset_notice"] == "pending"
    with engine.begin() as conn:
        conn.execute(sa.update(Setting.__table__).where(Setting.key == "model_roles_reset_notice").values(value="seen"))
        m0086.upgrade_sync(conn)                       # a second run changes nothing, the notice included
        assert _settings(conn)["model_roles_reset_notice"] == "seen"


def test_migration_0086_asks_for_no_notice_when_there_was_nothing_to_clear(tmp_path):
    from server.db.migrations.versions import _0086_route1_remove_routing as m0086
    engine = _old_db(tmp_path, {"language": "en", "router_config_id": ""})
    with engine.begin() as conn:
        m0086.upgrade_sync(conn)
        assert "model_roles_reset_notice" not in _settings(conn)


def test_migration_0086_asks_for_no_notice_on_a_fresh_install(tmp_path):
    """Migration 0006 seeds llm_strategy="single" on every install, and "single" already meant "the primary", so
    clearing it changes nothing a user chose. A notice there would greet every new user with a reset they never had."""
    from server.db.migrations.versions import _0086_route1_remove_routing as m0086
    engine = _old_db(tmp_path, {"language": "en", "llm_strategy": "single"})
    with engine.begin() as conn:
        m0086.upgrade_sync(conn)
        after = _settings(conn)
    assert "llm_strategy" not in after, "still cleared"
    assert "model_roles_reset_notice" not in after

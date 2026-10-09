"""0.1.58 §6: any model of any provider — per conversation, and per role.

A conversation's choice is (provider config, model id); without one, or once its config is
deleted, the turn runs on exactly the adapter it had before. A role slot may name one model
of its config. OpenRouter's catalog brings names, prices per million tokens, tools and vision.
"""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from arslan.llm import usage_sink
from server.db.models import Base, ConversationModel, ProviderConfig
from server.orchestrator import tool_loop
from server.services import llm_factory, model_catalog, settings_service


@pytest_asyncio.fixture
async def db(monkeypatch):
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    async with maker() as s:
        s.add(ProviderConfig(label="primary", provider="deepseek", model="deepseek-chat", api_key="", is_primary=True))
        s.add(ProviderConfig(label="router", provider="openrouter", model="openai/gpt-4o-mini", api_key="", is_primary=False))
        await s.commit()
        yield s
    await eng.dispose()


async def _router_id(db) -> int:
    from sqlalchemy import select
    return (await db.execute(select(ProviderConfig.id).where(ProviderConfig.label == "router"))).scalar_one()


async def test_no_choice_means_the_default(db):
    assert await llm_factory.build_conversation_adapter("c1") is None
    assert await llm_factory.build_conversation_adapter(None) is None


async def test_a_conversation_runs_on_its_chosen_model(db):
    cid = await _router_id(db)
    db.add(ConversationModel(conversation_id="c1", config_id=cid, model="anthropic/claude-sonnet-4.5"))
    await db.commit()
    adapter = await llm_factory.build_conversation_adapter("c1")
    assert adapter.model == "anthropic/claude-sonnet-4.5"
    assert await llm_factory.build_conversation_adapter("c2") is None      # only that conversation


async def test_the_turn_uses_the_choice_but_vision_still_takes_image_turns(db, monkeypatch):
    cid = await _router_id(db)
    db.add(ConversationModel(conversation_id="c1", config_id=cid, model="x/chosen"))
    await db.commit()
    default = object()
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: default)
    assert (await tool_loop._adapter_for_turn(has_images=False, conversation_id="c1")).model == "x/chosen"
    assert await tool_loop._adapter_for_turn(has_images=False, conversation_id="other") is default
    await settings_service.update_settings(db, {"vision_config_id": str(cid), "vision_model": "x/sees"})
    assert (await tool_loop._adapter_for_turn(has_images=True, conversation_id="c1")).model == "x/sees"
    assert (await tool_loop._adapter_for_turn(has_images=False, conversation_id="c1")).model == "x/chosen"


async def test_a_deleted_config_falls_back_to_the_default(db):
    cid = await _router_id(db)
    db.add(ConversationModel(conversation_id="c1", config_id=cid, model="x/y"))
    await db.commit()
    await db.delete(await db.get(ProviderConfig, cid))
    await db.commit()
    assert await llm_factory.build_conversation_adapter("c1") is None


@pytest.mark.parametrize("slot", ["title", "compaction", "router", "vision", "synthesis"])
async def test_a_role_can_name_one_model_of_its_config(db, slot):
    cid = await _router_id(db)
    await settings_service.update_settings(db, {f"{slot}_config_id": str(cid)})
    build = (llm_factory.build_synthesis_adapter() if slot == "synthesis"
             else llm_factory.build_slot_adapter(f"{slot}_config_id"))
    assert (await build).model == "openai/gpt-4o-mini"                      # the config's own model
    await settings_service.update_settings(db, {f"{slot}_model": "google/gemini-2.5-flash-lite"})
    build = (llm_factory.build_synthesis_adapter() if slot == "synthesis"
             else llm_factory.build_slot_adapter(f"{slot}_config_id"))
    assert (await build).model == "google/gemini-2.5-flash-lite"


async def test_the_conversation_model_api(client):
    async with client.db_maker() as s:
        s.add(ProviderConfig(label="or", provider="openrouter", model="a/b", api_key="", is_primary=True))
        await s.commit()
        from sqlalchemy import select
        cid = (await s.execute(select(ProviderConfig.id))).scalar_one()
    assert (await client.get("/api/v1/conversations/c1/model")).json() == {"choice": None}
    assert (await client.put("/api/v1/conversations/c1/model", json={"config_id": 999, "model": "x"})).status_code == 404
    r = await client.put("/api/v1/conversations/c1/model", json={"config_id": cid, "model": "deepseek/deepseek-chat:free"})
    assert r.json() == {"choice": {"config_id": cid, "model": "deepseek/deepseek-chat:free"}}   # ':' in an id is fine
    assert (await client.get("/api/v1/conversations/c1/model")).json()["choice"]["model"] == "deepseek/deepseek-chat:free"
    assert (await client.delete("/api/v1/conversations/c1/model")).json() == {"choice": None}


async def test_openrouter_entries_carry_name_price_tools_and_vision():
    payload = {"data": [
        {"id": "anthropic/claude-sonnet-4.5", "name": "Anthropic: Claude Sonnet 4.5", "context_length": 1000000,
         "architecture": {"input_modalities": ["text", "image"]}, "pricing": {"prompt": "0.000003", "completion": "0.000015"},
         "supported_parameters": ["tools", "reasoning"]},
        {"id": "old/model", "context_length": 8000, "pricing": {"prompt": "-1"}, "supported_parameters": []},
    ]}
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    models = await model_catalog.fetch_models("openrouter", "https://openrouter.ai/api/v1", "", transport=transport)
    a, b = models
    assert a["display_name"] == "Anthropic: Claude Sonnet 4.5" and a["context_window"] == 1000000
    assert (a["price_in"], a["price_out"]) == (3.0, 15.0)
    assert set(a["capabilities"]) == {"tools", "vision", "reasoning"}
    assert "price_in" not in b and b["capabilities"] == []                   # unknown price stays unknown


def test_the_last_calls_input_is_reported():
    with usage_sink.collecting():
        usage_sink.report_detail(tokens_in=1000, tokens_out=10, model="m", provider="p")
        usage_sink.report_detail(tokens_in=1800, tokens_out=12, model="m", provider="p")
        assert usage_sink.last_input() == 1800
    assert usage_sink.last_input() is None


async def test_a_chat_turn_reaches_the_turn_adapter_with_its_conversation(db, monkeypatch):
    """End to end from the chat path: the id must survive run_native → _run_native, or the choice is dead."""
    from server.orchestrator import arslan
    seen: list = []

    class Stop(Exception):
        pass

    async def spy(*, has_images, conversation_id=None):
        seen.append(conversation_id)
        raise Stop
    monkeypatch.setattr(tool_loop, "_adapter_for_turn", spy)
    try:
        await arslan._handle_answer("c-model", "你好", lambda e: None)
    except Stop:
        pass
    assert seen == ["c-model"]


async def test_the_turns_usage_frame_carries_the_last_calls_input(db, monkeypatch):
    from server.orchestrator import arslan

    async def fake_run_native(*, on_chunk, **kw):
        usage_sink.report_detail(tokens_in=900, tokens_out=5, model="m", provider="p")
        usage_sink.report_detail(tokens_in=1400, tokens_out=7, model="m", provider="p")
        on_chunk("hi")
        return {"final": "hi", "tool_trace": []}
    monkeypatch.setattr(tool_loop, "run_native", fake_run_native)
    events: list[dict] = []
    await arslan._handle_answer("c-ring", "你好", events.append)
    end = next(e for e in events if e["type"] == "stream_end")
    assert end["usage"]["last_input"] == 1400

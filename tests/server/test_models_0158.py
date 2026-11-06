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


async def test_the_turn_uses_the_choice_and_vision_takes_image_turns_only_without_one(db, monkeypatch):
    """v0.1.64 (⓪Plan's Q2, option c): a conversation's own model takes its image turns too; the vision slot takes the
    image turns of a conversation with no choice (until v0.1.63 it took every image turn)."""
    cid = await _router_id(db)
    db.add(ConversationModel(conversation_id="c1", config_id=cid, model="x/chosen"))
    await db.commit()
    default = object()
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: default)
    assert (await tool_loop._adapter_for_turn(has_images=False, conversation_id="c1")).model == "x/chosen"
    assert await tool_loop._adapter_for_turn(has_images=False, conversation_id="other") is default
    await settings_service.update_settings(db, {"vision_config_id": str(cid), "vision_model": "x/sees"})
    assert (await tool_loop._adapter_for_turn(has_images=True, conversation_id="c1")).model == "x/chosen"
    assert (await tool_loop._adapter_for_turn(has_images=True, conversation_id="other")).model == "x/sees"
    assert (await tool_loop._adapter_for_turn(has_images=False, conversation_id="c1")).model == "x/chosen"


async def test_a_deleted_config_falls_back_to_the_default(db):
    cid = await _router_id(db)
    db.add(ConversationModel(conversation_id="c1", config_id=cid, model="x/y"))
    await db.commit()
    await db.delete(await db.get(ProviderConfig, cid))
    await db.commit()
    assert await llm_factory.build_conversation_adapter("c1") is None


@pytest.mark.parametrize("slot", ["router", "vision"])   # D8: no title slot; ROUTE1: no compaction or synthesis slot
async def test_a_role_can_name_one_model_of_its_config(db, slot):
    cid = await _router_id(db)
    await settings_service.update_settings(db, {f"{slot}_config_id": str(cid)})
    assert (await llm_factory.build_slot_adapter(f"{slot}_config_id")).model == "openai/gpt-4o-mini"   # the config's own
    await settings_service.update_settings(db, {f"{slot}_model": "google/gemini-2.5-flash-lite"})
    assert (await llm_factory.build_slot_adapter(f"{slot}_config_id")).model == "google/gemini-2.5-flash-lite"


async def test_the_conversation_model_api(client):
    async with client.db_maker() as s:
        s.add(ProviderConfig(label="or", provider="openrouter", model="a/b", api_key="", is_primary=True))
        await s.commit()
        from sqlalchemy import select
        cid = (await s.execute(select(ProviderConfig.id))).scalar_one()
    assert (await client.get("/api/v1/conversations/c1/model")).json()["choice"] is None
    assert (await client.put("/api/v1/conversations/c1/model", json={"config_id": 999, "model": "x"})).status_code == 404
    r = await client.put("/api/v1/conversations/c1/model", json={"config_id": cid, "model": "deepseek/deepseek-chat:free"})
    assert r.json()["choice"] == {"config_id": cid, "model": "deepseek/deepseek-chat:free"}   # ':' in an id is fine
    assert (await client.get("/api/v1/conversations/c1/model")).json()["choice"]["model"] == "deepseek/deepseek-chat:free"
    assert (await client.delete("/api/v1/conversations/c1/model")).json()["choice"] is None


async def test_the_model_api_says_what_the_next_turn_really_runs_on(client):
    """v0.1.64 (user report): the chip shows the server's answer, never its own guess: a chat that showed Claude kept
    running on DeepSeek. With no choice the next turn runs on the primary (ROUTE1: there is no routing); with one, on
    the choice."""
    from sqlalchemy import select
    async with client.db_maker() as s:
        s.add(ProviderConfig(label="ds", provider="deepseek", model="deepseek-v4-flash", api_key="", is_primary=True))
        s.add(ProviderConfig(label="claude", provider="anthropic", model="claude-opus-5-5", api_key=""))
        await s.commit()
        ids = dict((await s.execute(select(ProviderConfig.label, ProviderConfig.id))).all())
    got = (await client.get("/api/v1/conversations/thread-x/model")).json()
    assert got["choice"] is None
    assert got["effective"] == {"config_id": ids["ds"], "model": "deepseek-v4-flash", "provider": "deepseek"}
    put = await client.put("/api/v1/conversations/thread-x/model", json={"config_id": ids["claude"], "model": "claude-opus-5-5"})
    assert put.json()["effective"] == {"config_id": ids["claude"], "model": "claude-opus-5-5", "provider": "anthropic"}
    assert (await client.get("/api/v1/conversations/thread-x/model")).json()["effective"]["provider"] == "anthropic"
    cleared = (await client.delete("/api/v1/conversations/thread-x/model")).json()
    assert cleared["choice"] is None and cleared["effective"]["provider"] == "deepseek"


async def test_the_effective_model_is_the_one_the_turn_builds(db):
    """`effective` and the turn's adapter come from one decision, so they can't drift apart."""
    async with db_session.AsyncSessionLocal() as s:
        eff = await llm_factory.effective_choice(s, "c-none")
    turn = await tool_loop._adapter_for_turn(has_images=False, conversation_id="c-none")
    assert (eff["provider"], eff["model"]) == ("deepseek", "deepseek-chat") == (turn.report_provider, turn.model)
    db.add(ConversationModel(conversation_id="c-set", config_id=await _router_id(db), model="x/chosen"))
    await db.commit()
    async with db_session.AsyncSessionLocal() as s:
        eff = await llm_factory.effective_choice(s, "c-set")
    turn = await tool_loop._adapter_for_turn(has_images=False, conversation_id="c-set")
    assert (eff["model"], turn.model) == ("x/chosen", "x/chosen")


async def test_a_blank_model_is_refused_and_effective_never_reports_an_empty_name(client):
    """#691 review 3: "  " passed the length check before the strip and stored "", so `effective` said "" while the
    turn ran the config's own model. A blank is refused; a stored one (older rows) reads as the config's model, and the
    default reports the model the turn really builds (a preset fills a blank one)."""
    from sqlalchemy import select
    async with client.db_maker() as s:
        s.add(ProviderConfig(label="ds", provider="deepseek", model="", api_key="", is_primary=True))
        s.add(ProviderConfig(label="or", provider="openrouter", model="openai/gpt-4o-mini", api_key=""))
        await s.commit()
        rid = (await s.execute(select(ProviderConfig.id).where(ProviderConfig.label == "or"))).scalar_one()
        s.add(ConversationModel(conversation_id="c-old", config_id=rid, model=""))
        await s.commit()
    assert (await client.put("/api/v1/conversations/c-blank/model", json={"config_id": rid, "model": "   "})).status_code == 422
    async with client.db_maker() as s:
        old = await llm_factory.effective_choice(s, "c-old")
        default = await llm_factory.effective_choice(s, "c-none")
    assert old["model"] == "openai/gpt-4o-mini"
    turn = await tool_loop._adapter_for_turn(has_images=False, conversation_id="c-none")
    assert default["model"] and default["model"] == turn.model


async def test_a_switch_takes_the_next_turn_at_each_point_the_user_can_make_it(client, monkeypatch):
    """v0.1.64 (user report: a DeepSeek balance error kept blocking a chat switched to Claude). DeepSeek is the
    default and answers 402; the user switches through the API the chip calls. The next turn runs on the pick:
    in a fresh chat before its first message, right after a failed turn, and on a turn that carries an image
    (with no vision slot set; the slot's precedence is unchanged here)."""
    from sqlalchemy import select
    from server.orchestrator import arslan
    async with client.db_maker() as s:
        s.add(ProviderConfig(label="ds", provider="deepseek", model="deepseek-v4-flash", api_key="", is_primary=True))
        s.add(ProviderConfig(label="claude", provider="anthropic", model="claude-opus-5-5", api_key=""))
        await s.commit()
        claude = (await s.execute(select(ProviderConfig.id).where(ProviderConfig.label == "claude"))).scalar_one()
    turns: list[tuple] = []

    async def fake_run_native(*, on_chunk, **kw):
        a = await tool_loop._adapter_for_turn(has_images=kw.get("has_images", False), conversation_id=kw.get("conversation_id"))
        turns.append((kw.get("conversation_id"), a.report_provider, a.model))
        if a.report_provider == "deepseek":
            raise RuntimeError("Error code: 402 - {'error': {'message': 'Insufficient Balance'}}")
        on_chunk("ok")
        return {"final": "ok", "tool_trace": []}
    monkeypatch.setattr(tool_loop, "run_native", fake_run_native)

    async def turn(cid: str):
        try:
            await arslan._handle_answer(cid, "hi", lambda e: None)
        except Exception:  # noqa: BLE001 — the 402 turn; what matters is which model it ran on
            pass

    async def switch(cid: str):
        r = await client.put(f"/api/v1/conversations/{cid}/model", json={"config_id": claude, "model": "claude-opus-5-5"})
        assert r.status_code == 200 and r.json()["effective"]["provider"] == "anthropic"

    await switch("thread-fresh")                       # 1. a fresh chat, before its first message
    await turn("thread-fresh")
    await turn("thread-failed")                        # 2. a turn fails on the default (402) ...
    await switch("thread-failed")                      #    ... and the user switches right after
    await turn("thread-failed")
    assert turns == [("thread-fresh", "anthropic", "claude-opus-5-5"),
                     ("thread-failed", "deepseek", "deepseek-v4-flash"),
                     ("thread-failed", "anthropic", "claude-opus-5-5")]
    await switch("thread-image")                       # 3. a turn that carries an image, no vision slot set
    image_turn = await tool_loop._adapter_for_turn(has_images=True, conversation_id="thread-image")
    assert (image_turn.report_provider, image_turn.model) == ("anthropic", "claude-opus-5-5")


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
    # K2: the history budget resolves the turn's adapter the same way first (memory.turn_budget,
    # which swallows the spy's Stop and falls back); every resolution carries the conversation.
    assert seen and set(seen) == {"c-model"}


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

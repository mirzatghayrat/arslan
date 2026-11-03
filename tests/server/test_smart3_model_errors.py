"""SMART-3 (v0.1.64, model-switch part B): a failed model call says which call failed (the chat, or a helper slot:
vision, router, compaction, synthesis) on which provider and model; a failed run records the model it tried; and on an
image turn the chat's explicit model wins over the vision slot (⓪Plan's Q2, option c), with a refusal that names it.

User report: a chat switched to Claude kept failing on DeepSeek's balance; every helper slot pointed at DeepSeek too."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from arslan.llm import usage_sink
from arslan.llm.adapter import LLMAdapter
from server.db.models import Base, ConversationModel, ProviderConfig, Setting
from server.orchestrator import llm_errors, tool_loop
from server.services import llm_factory

BALANCE = "Error code: 402 - {'error': {'message': 'Insufficient Balance'}}"


def _failing(provider="deepseek", model="deepseek-v4-flash", role=None, error=BALANCE) -> LLMAdapter:
    a = LLMAdapter("openai", model, api_key="x", base_url="http://127.0.0.1:9", report_provider=provider)
    a.role = role

    async def boom(*args, **kwargs):
        raise RuntimeError(error)
    a._provider.chat = boom
    return a


async def test_a_failed_call_says_which_call_failed_on_which_model():
    with pytest.raises(RuntimeError) as chat:
        await _failing().chat("s", "hi")
    assert chat.value.arslan_call == {"role": "chat", "provider": "deepseek", "model": "deepseek-v4-flash"}
    with pytest.raises(RuntimeError) as helper:
        await _failing(role="router").chat("s", "hi")
    assert helper.value.arslan_call["role"] == "router"


async def test_a_failed_run_records_the_model_it_tried():
    with usage_sink.collecting():
        with pytest.raises(RuntimeError):
            await _failing().chat("s", "hi")
        got = usage_sink.detail()
    assert (got["provider"], got["model"]) == ("deepseek", "deepseek-v4-flash")
    assert (got["tokens_in"], got["tokens_out"]) == (None, None), "nothing was used"


async def test_the_error_frame_names_the_call():
    with pytest.raises(RuntimeError) as failed:
        await _failing(role="vision").chat("s", "hi")
    frame = await llm_errors.error_frame(failed.value)
    assert frame["call"] == {"role": "vision", "provider": "deepseek", "model": "deepseek-v4-flash"}


async def test_an_image_refusal_names_the_model_and_its_provider():
    refusal = "Failed to deserialize the JSON body: messages[1]: unknown variant `image_url`, expected `text`"
    with pytest.raises(RuntimeError) as failed:
        await _failing(error=refusal).chat("s", "hi")
    frame = await llm_errors.error_frame(failed.value, had_images=True)
    assert "deepseek-v4-flash" in frame["message"] and "deepseek" in frame["message"]
    assert all("deepseek-v4-flash" in text for text in frame["message_i18n"].values())


@pytest_asyncio.fixture
async def db(monkeypatch):
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    async with maker() as s:
        s.add(ProviderConfig(id=1, label="ds", provider="deepseek", model="deepseek-v4-flash", api_key="", is_primary=True))
        s.add(ProviderConfig(id=3, label="claude", provider="anthropic", model="claude-sonnet-5-5", api_key=""))
        s.add(Setting(key="vision_config_id", value="1"))
        await s.commit()
        yield s
    await eng.dispose()


async def test_every_adapter_says_what_it_is_for(db):
    db.add(ConversationModel(conversation_id="c", config_id=3, model="claude-opus-5-5"))
    await db.commit()
    assert (await llm_factory.build_conversation_adapter("c")).role == "chat"
    assert (await llm_factory.build_adapter(role="execute")).role == "chat"
    assert (await llm_factory.build_slot_adapter("vision_config_id")).role == "vision"


async def test_on_an_image_turn_the_chats_own_model_wins_over_the_vision_slot(db):
    """Q2 (c): the user said "this chat runs on X"; if X can't read the image, its refusal says so (above)."""
    db.add(ConversationModel(conversation_id="c-pick", config_id=3, model="claude-opus-5-5"))
    await db.commit()
    image = await tool_loop._adapter_for_turn(has_images=True, conversation_id="c-pick")
    assert (image.report_provider, image.model) == ("anthropic", "claude-opus-5-5")


async def test_with_no_choice_an_image_turn_still_goes_to_the_vision_slot(db):
    image = await tool_loop._adapter_for_turn(has_images=True, conversation_id="c-none")
    assert image.role == "vision" and image.report_provider == "deepseek"


async def test_a_text_turn_is_unaffected(db):
    db.add(ConversationModel(conversation_id="c-text", config_id=3, model="claude-opus-5-5"))
    await db.commit()
    text = await tool_loop._adapter_for_turn(has_images=False, conversation_id="c-text")
    assert text.model == "claude-opus-5-5"
    plain = await tool_loop._adapter_for_turn(has_images=False, conversation_id="c-none")
    assert (plain.report_provider, plain.role) == ("deepseek", "chat")

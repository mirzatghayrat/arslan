"""SMART-3 (v0.1.64, model-switch part B): a failed model call says which call failed (the chat, or a helper slot:
vision, router, compaction, synthesis) on which provider and model; a failed run records the model it tried; and on an
image turn the chat's explicit model wins over the vision slot (⓪Plan's Q2, option c), with a refusal that names it.

User report: a chat switched to Claude kept failing on DeepSeek's balance; every helper slot pointed at DeepSeek too."""
import httpx
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


async def test_the_turn_and_stream_paths_name_the_call_too():
    """The tool loop's native path (chat_trajectory) and the streamed path (chat_stream) stamp a failure the same way."""
    a = _failing(role="vision")
    with pytest.raises(RuntimeError) as native:
        await a.chat_trajectory("s", [{"role": "user", "content": "hi"}])
    assert native.value.arslan_call["role"] == "vision"

    async def broken_stream(*args, **kwargs):
        raise RuntimeError(BALANCE)
        yield ""   # unreachable: makes this an async generator
    a._provider.chat_stream = broken_stream
    with pytest.raises(RuntimeError) as streamed:
        async for _ in a.chat_stream("s", "hi"):
            pass
    assert streamed.value.arslan_call == {"role": "vision", "provider": "deepseek", "model": "deepseek-v4-flash"}


async def test_the_innermost_failed_call_is_the_one_named():
    """A helper's failure that surfaces through the chat's call (a compaction or vision call inside a turn) keeps the
    helper's name: the call that failed is the one to fix."""
    inner = RuntimeError(BALANCE)
    inner.arslan_call = {"role": "vision", "provider": "deepseek", "model": "deepseek-v4-flash"}
    outer = _failing(provider="anthropic", model="claude-opus-5-5")

    async def passes_it_on(*args, **kwargs):
        raise inner
    outer._provider.chat = passes_it_on
    with pytest.raises(RuntimeError) as failed:
        await outer.chat("s", "hi")
    assert failed.value.arslan_call["role"] == "vision" and failed.value.arslan_call["provider"] == "deepseek"


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


def _http_error(status: int, body: str) -> httpx.HTTPStatusError:
    """As the providers raise it: the status line plus the provider's own words (providers/errors.with_body)."""
    from arslan.llm.providers import errors as provider_errors
    request = httpx.Request("POST", "https://api.example.invalid/v1/chat/completions")
    response = httpx.Response(status, request=request, text=body)
    bare = httpx.HTTPStatusError(f"Client error '{status}'", request=request, response=response)
    return httpx.HTTPStatusError(provider_errors.with_body(bare), request=request, response=response)


async def test_the_name_survives_the_real_wrapper():
    """#696 review 1: providers raise httpx errors and call_with_recovery re-raises them as ModelCallError(...) from
    exc. The frame must still name the call (a RuntimeError raised straight skipped that wrapper)."""
    from server.orchestrator.model_call import ModelCallError, TurnRecovery, call_with_recovery
    a = _failing()

    async def balance(*args, **kwargs):
        raise _http_error(402, '{"error": {"message": "Insufficient Balance"}}')
    a._provider.chat = balance
    with pytest.raises(ModelCallError) as failed:
        await call_with_recovery(lambda: a.chat("s", "hi"), TurnRecovery())
    frame = await llm_errors.error_frame(failed.value)
    assert frame["call"] == {"role": "chat", "provider": "deepseek", "model": "deepseek-v4-flash"}


async def test_a_later_unrelated_error_is_not_blamed_on_the_model():
    """Only the explicit `from` chain carries the name: an error raised while handling a model failure is not it."""
    with pytest.raises(RuntimeError) as failed:
        await _failing().chat("s", "hi")
    try:
        raise ValueError("a bug in our own code")
    except ValueError as unrelated:
        unrelated.__context__ = failed.value          # what Python sets when raising inside an except block
        frame = await llm_errors.error_frame(unrelated)
    assert "call" not in frame


async def test_an_image_refusal_through_the_real_wrapper_names_the_model():
    from server.orchestrator.model_call import TurnRecovery, call_with_recovery
    a = _failing()

    async def refuses(*args, **kwargs):
        raise _http_error(400, "Failed to deserialize the JSON body: messages[1]: unknown variant `image_url`, expected `text`")
    a._provider.chat = refuses
    with pytest.raises(Exception) as failed:
        await call_with_recovery(lambda: a.chat("s", "hi"), TurnRecovery())
    frame = await llm_errors.error_frame(failed.value, had_images=True)
    assert frame.get("call", {}).get("model") == "deepseek-v4-flash"
    assert "deepseek-v4-flash" in frame["message"]


async def test_when_the_image_model_refuses_the_text_points_to_settings_not_to_this_chat():
    """#696 review: the banner offers settings for a helper; the message says the same."""
    refusal = "Failed to deserialize the JSON body: messages[1]: unknown variant `image_url`, expected `text`"
    with pytest.raises(RuntimeError) as failed:
        await _failing(role="vision", error=refusal).chat("s", "hi")
    frame = await llm_errors.error_frame(failed.value, had_images=True)
    assert "deepseek-v4-flash" in frame["message"] and "this chat" not in frame["message"]
    assert "Settings" in frame["message"]


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

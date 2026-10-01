import asyncio
from string import Formatter
from types import SimpleNamespace

import pytest

from arslan.models import LLMResponse
from server.db.models import Setting
from server.orchestrator import tool_loop
from server.services import runtime_messages as copy, task_service


def test_runtime_notice_catalog_has_complete_locales_and_placeholders():
    assert set(copy.MESSAGES) == {"en", "zh", "ja", "es", "de", "fr"}
    expected = set(copy.MESSAGES["en"])
    for locale, messages in copy.MESSAGES.items():
        assert set(messages) == expected
        for key, text in messages.items():
            assert text.strip()
            fields = {field for _, field, _, _ in Formatter().parse(text) if field}
            allowed = {"named_correction": {"name"}, "job_interrupted": {"goal"},   # 0.1.42
                       "job_out_of_budget": {"goal", "what", "used", "limit", "steps"},   # 0.1.43
                       "proactive_goal_followup": {"goal"}, "proactive_goal_scheduled": {"name", "prompt"},   # 0.1.47
                       "proactive_goal_web": {"url"}, "proactive_goal_folder": {"path", "count"},
                       "model_retried": {"attempts", "seconds"}}   # 0.1.49
            assert fields == allowed.get(key, set())
            if locale != "en":
                assert text != copy.MESSAGES["en"][key]




@pytest.mark.parametrize("locale", list(copy.MESSAGES))
async def test_real_native_empty_answer_uses_saved_ui_language(execution_db, locale):
    async with execution_db() as db:
        db.add(Setting(key="language", value=locale))
        await db.commit()
    class EmptyAdapter:
        async def chat(self, *args, **kwargs):
            return LLMResponse(content="", tool_calls=[], usage={})
    async def no_tools(): return []
    chunks = []
    result = await tool_loop.run_native(system="Synthetic test", user_content="hello 你好",
        history=[], emit=lambda event: None, on_chunk=chunks.append, resolve_tools=no_tools,
        adapter_override=EmptyAdapter(), log_events=False)
    assert result["final"] == copy.render("chat_miss", locale)
    assert "".join(chunks) == result["final"]




async def test_locale_is_task_bound_and_does_not_read_secret_settings(monkeypatch):
    def forbidden(): raise AssertionError("Task-local notice must not read the database")
    monkeypatch.setattr(copy.db_session, "AsyncSessionLocal", forbidden)
    async def child(locale):
        token = task_service._current.set(SimpleNamespace(spec=SimpleNamespace(locale=locale), closed=False))
        try:
            await asyncio.sleep(0)
            return await copy.selected_locale()
        finally:
            task_service._current.reset(token)
    assert await asyncio.gather(*(child(locale) for locale in copy.MESSAGES)) == list(copy.MESSAGES)


@pytest.mark.parametrize("stored,expected", [(None, "en"), ("fr-CA", "fr"), ("ja_JP", "ja"),
    ("Chinese (Simplified)", "zh"), ("Japanese", "ja"), ("German", "de"), ("unknown", "en")])
async def test_default_and_regional_language_normalization(execution_db, stored, expected):
    if stored is not None:
        async with execution_db() as db:
            db.add(Setting(key="language", value=stored))
            await db.commit()
    assert await copy.selected_locale() == expected


@pytest.mark.parametrize("stored,expected", [("Chinese (Simplified)", "zh"), ("Japanese", "ja"), ("German", "de")])
async def test_real_task_uses_same_legacy_language_normalization(execution_db, stored, expected):
    from server.services import personal_context as pc
    async with execution_db() as db:
        db.add(Setting(key="language", value=stored))
        await db.commit()
    seen = []
    async def body(conversation, message, emit):
        seen.append(await copy.selected_locale())
        return "Synthetic result"
    with pc.bind(pc.TaskMemoryContext(task_id="locale-task", run_id="initial", conversation_id="locale-task")):
        await task_service.run_turn(body, "locale-task", "Synthetic task", lambda event: None)
    assert seen == [expected]


async def test_failed_settings_read_has_safe_default_but_cancellation_propagates(monkeypatch):
    from sqlalchemy.exc import OperationalError
    def failed(): raise OperationalError("private statement", {}, RuntimeError("private storage failure"))
    monkeypatch.setattr(copy.db_session, "AsyncSessionLocal", failed)
    assert await copy.selected_locale() == "en"
    def cancelled(): raise asyncio.CancelledError
    monkeypatch.setattr(copy.db_session, "AsyncSessionLocal", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await copy.selected_locale()

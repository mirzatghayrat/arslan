import asyncio
from string import Formatter
from types import SimpleNamespace

import pytest

from arslan.models import LLMResponse
from server.db.models import Setting
from server.orchestrator import arslan, promise_guard, tool_loop
from server.services import runtime_messages as copy, task_service


def test_runtime_notice_catalog_has_complete_locales_and_placeholders():
    assert set(copy.MESSAGES) == {"en", "zh", "ja", "es", "de", "fr"}
    expected = set(copy.MESSAGES["en"])
    for locale, messages in copy.MESSAGES.items():
        assert set(messages) == expected
        for key, text in messages.items():
            assert text.strip()
            fields = {field for _, field, _, _ in Formatter().parse(text) if field}
            assert fields == ({"name"} if key == "named_correction" else set())
            if locale != "en":
                assert text != copy.MESSAGES["en"][key]


@pytest.mark.parametrize("locale", list(copy.MESSAGES))
async def test_saved_ui_language_controls_stale_proposal_and_corrections(execution_db, monkeypatch, locale):
    async with execution_db() as db:
        db.add(Setting(key="language", value=locale))
        await db.commit()
    from server.services import phase_service
    async def no_pending(*args): return None
    async def never(*args, **kwargs): raise AssertionError("No stale proposal may dispatch")
    def unavailable(): raise RuntimeError("Synthetic adapter unavailable")
    monkeypatch.setattr(phase_service, "get_pending", no_pending)
    monkeypatch.setattr(arslan, "_dispatch_spawn", never)
    monkeypatch.setattr(tool_loop, "_get_adapter", unavailable)
    frames = []
    await arslan.confirm_and_execute("synthetic", 7, frames.append)
    assert frames == [{"type": "message", "message_id": None, "role": "arslan",
                       "content": copy.render("proposal_handled", locale)},
                      {"type": "stream_end", "message_id": None}]
    for name in [None, "Synthetic Expert"]:
        result = await promise_guard.correct("正在生成中,稍等", spawn_name=name)
        assert result["corrected"] is False
        assert result["correction"] == copy.render("named_correction" if name else "correction", locale, name=name)
    result = await promise_guard.correct_zero_tool("PPT 已生成并交付，共 7 页。")
    assert result["corrected"] is False
    assert result["correction"] == copy.render("no_tools_correction", locale)


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


@pytest.mark.parametrize("locale", list(copy.MESSAGES))
async def test_synthesis_floor_keeps_findings_and_continuation_semantics(execution_db, monkeypatch, locale):
    async with execution_db() as db:
        db.add(Setting(key="language", value=locale))
        await db.commit()
    class EmptyAdapter:
        async def chat(self, *args, **kwargs):
            return LLMResponse(content="", tool_calls=[], usage={})
    from server.services import llm_factory
    async def no_synthesis(): return None
    monkeypatch.setattr(llm_factory, "build_synthesis_adapter", no_synthesis)
    trace = [{"tool": "web_search", "args": {"query": "fixture"},
              "result": {"ok": True, "results": [{"title": "User-authored source remains unchanged"}]}}]
    result = await tool_loop._synthesize_from_findings(EmptyAdapter(), "Synthetic", "hello 你好", trace)
    assert copy.render("findings_header", locale) in result
    assert "User-authored source remains unchanged" in result
    assert copy.render("round_incomplete", locale) in result
    assert not arslan._looks_like_refusal(result)
    assert arslan._has_findings_digest(result)
    assert arslan._looks_like_refusal(copy.render("round_incomplete", locale))
    assert copy.render("findings_header", locale) in tool_loop._fallback_with_digest(
        [{"type": "text", "text": "Image question"}], trace, locale=locale)


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

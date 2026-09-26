from sqlalchemy import select
import pytest

from server.db.models import ArslanMessage
from server.orchestrator import arslan, tool_loop
from server.services import knowledge


@pytest.mark.parametrize("precise", [False, True])
async def test_source_navigation_is_streamed_and_saved_even_when_model_omits_links(execution_db, monkeypatch, precise):
    async def empty(*args, **kwargs):
        return ""
    async def no_knowledge(*args, **kwargs):
        return []
    async def native(**kwargs):
        return {"final": "A comparison without citations.", "tool_trace": []}
    async def language():
        return "zh"
    monkeypatch.setattr(arslan, "_team_roster", empty)
    monkeypatch.setattr(knowledge, "retrieve_scoped", no_knowledge)
    monkeypatch.setattr(tool_loop, "run_native", native)
    monkeypatch.setattr(arslan.ocr_fallback, "current_ui_language", language)
    events = []
    prompt = "比较 https://example.com/a" if not precise else "只输出 JSON：https://example.com/a"
    answer = await arslan._handle_answer("source-links", prompt, events.append)
    if precise:
        assert answer == "A comparison without citations."
    else:
        assert "https://example.com/a" in answer and "本轮未独立读取" in answer
        assert any("来源链接" in event.get("content", "") for event in events)
    async with execution_db() as db:
        saved = await db.scalar(select(ArslanMessage).where(ArslanMessage.conversation_id == "source-links"))
    assert saved.role == "arslan" and saved.content == answer

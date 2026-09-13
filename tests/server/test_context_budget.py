import pytest
from sqlalchemy import select

from arslan.context_budget import clip, estimate_tokens
from server.db.models import ArslanMessage, ArslanSummary, UserFact
from server.orchestrator import memory


@pytest.mark.parametrize("text", ["中" * 1000, "a" * 4000, "混合mixed" * 1000, "日本語한글" * 1000])
def test_prefix_obeys_estimated_budget(text):
    assert estimate_tokens(clip(text, 20)) <= 20
    assert clip(text, 0) == ""


async def test_compaction_second_oversized_cjk_summary_is_actually_bounded(execution_db, monkeypatch):
    monkeypatch.setenv("ARSLAN_WORKING_TOKEN_BUDGET", "20")
    async def summarize(*args):
        return "中" * 1000
    monkeypatch.setattr(memory, "_get_adapter", lambda: object())
    monkeypatch.setattr(memory, "_summarize", summarize)
    await memory.add_message("compact-cjk", "user", "中" * 100)
    await memory.add_message("compact-cjk", "user", "国" * 100)
    await memory.maybe_compact("compact-cjk")
    async with execution_db() as db:
        summary = (await db.execute(select(ArslanSummary))).scalar_one()
    assert estimate_tokens(summary.summary) <= 20


async def test_failed_compaction_cannot_create_unbounded_working_context(execution_db, monkeypatch):
    monkeypatch.setenv("ARSLAN_WORKING_TOKEN_BUDGET", "30")
    for i in range(4):
        await memory.add_message("bounded", "user", str(i) + "中" * 100)
    context = await memory.assemble_working_context("bounded")
    assert context["truncated"] is True
    assert sum(estimate_tokens(m["content"]) for m in context["history"]) <= 30
    assert context["history"][-1]["content"].startswith("3")
    async with execution_db() as db:
        assert len((await db.execute(select(ArslanMessage))).scalars().all()) == 4


async def test_oversized_first_fact_cannot_bypass_budget(execution_db):
    async with execution_db() as db:
        db.add(UserFact(content="中" * 1000, sensitive=False, confidence=1.0))
        db.add(UserFact(content="prefers tea", sensitive=False, confidence=0.8))
        await db.commit()
    result = await memory.facts_text(limit_tokens=30)
    assert "prefers tea" in result and "中" not in result
    assert estimate_tokens(result) <= 30
    assert await memory.facts_text(limit_tokens=0) == ""

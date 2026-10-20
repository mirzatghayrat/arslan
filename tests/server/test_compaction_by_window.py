"""Compaction runs once at about three quarters of the history budget, keeps the latest turns as
they were, and masks older turns' tool details before it summarizes anything (K2)."""
import asyncio

import pytest
from sqlalchemy import select

from server.db.models import ArslanSummary
from server.orchestrator import memory, turn_tools

BUDGET = 10_000


class _Summarizer:
    def __init__(self):
        self.calls = []

    async def chat(self, system, user, **kwargs):
        self.calls.append({"system": system, "user": user})

        class Reply:
            content = f"Goal: g{len(self.calls)}\nProgress: p\nDecisions: d\nFiles touched: f\nNext steps: n"
        return Reply()


async def _seed(cid, pairs, *, start=0, tools=False):
    for i in range(start, start + pairs):            # each message about 500 estimated tokens
        await memory.add_message(cid, "user", f"u{i} " + "word " * 400)
        body = f"a{i} " + "word " * 400
        if tools:
            block = turn_tools.block([{"tool": "list_dir", "args": {"path": f"dir{i}"},
                                       "result": {"ok": True, "entries": ["x"]}}])
            await memory.add_message(cid, "arslan", f"{body}\n\n{block}", display_content=body)
        else:
            await memory.add_message(cid, "arslan", body)


async def _summaries(execution_db):
    async with execution_db() as db:
        return (await db.execute(select(ArslanSummary).order_by(ArslanSummary.id))).scalars().all()


async def test_compaction_waits_for_three_quarters_of_the_budget(execution_db, monkeypatch):
    summarizer = _Summarizer()
    monkeypatch.setattr(memory, "_get_adapter", lambda: summarizer)
    await _seed("c70", 7)                              # about 70% of the budget
    await memory.maybe_compact("c70", budget=BUDGET)
    assert summarizer.calls == []


async def test_compaction_runs_once_and_keeps_the_latest_turns_as_they_were(execution_db, monkeypatch):
    summarizer = _Summarizer()
    monkeypatch.setattr(memory, "_get_adapter", lambda: summarizer)
    await _seed("c80", 8)                              # about 80%
    await memory.maybe_compact("c80", budget=BUDGET)
    await memory.maybe_compact("c80", budget=BUDGET)
    assert len(summarizer.calls) == 1
    history = (await memory.assemble_working_context("c80", budget=BUDGET))["history"]
    users = [m["content"] for m in history if m["role"] == "user"]
    assert users == [f"u{i} " + "word " * 400 for i in (4, 5, 6, 7)]     # verbatim, not clipped


async def test_the_summary_is_structured_and_updated_not_retold(execution_db, monkeypatch):
    summarizer = _Summarizer()
    monkeypatch.setattr(memory, "_get_adapter", lambda: summarizer)
    await _seed("cs", 8)
    await memory.maybe_compact("cs", budget=BUDGET)
    await _seed("cs", 8, start=8)
    await memory.maybe_compact("cs", budget=BUDGET)
    second = summarizer.calls[-1]
    for section in ("Goal", "Progress", "Decisions", "Files touched", "Next steps"):
        assert section in second["system"]
    assert "g1" in second["user"]                       # the earlier summary, to update
    assert (await _summaries(execution_db))[-1].summary.startswith("Goal: g2")


@pytest.mark.parametrize("prior", [False, True])
async def test_two_compactions_at_once_write_one_summary(execution_db, monkeypatch, prior):
    """K2b: compaction runs after the turn, outside its lock, so two can read the same latest
    summary (none, or an earlier one). The one that writes second is stale and is dropped."""
    summarizer = _Summarizer()
    monkeypatch.setattr(memory, "_get_adapter", lambda: summarizer)
    await _seed("cr", 8)
    if prior:
        await memory.maybe_compact("cr", budget=BUDGET)
        await _seed("cr", 8, start=8)
    before = len(await _summaries(execution_db))
    entered, release = [], asyncio.Event()

    class _Slow(_Summarizer):
        async def chat(self, system, user, **kwargs):
            entered.append(1)
            await release.wait()
            return await super().chat(system, user, **kwargs)

    monkeypatch.setattr(memory, "_get_adapter", lambda: _Slow())
    both = [asyncio.create_task(memory.maybe_compact("cr", budget=BUDGET)) for _ in range(2)]
    try:
        async with asyncio.timeout(5):
            while len(entered) < 2:                    # both have read the same latest summary
                await asyncio.sleep(0.01)
    finally:
        release.set()
    await asyncio.gather(*both)
    assert len(await _summaries(execution_db)) == before + 1


async def test_older_turns_tool_details_are_masked_and_the_latest_kept(execution_db):
    await _seed("cm", 6, tools=True)
    history = (await memory.assemble_working_context("cm", budget=50_000))["history"]
    replies = [m["content"] for m in history if m["role"] == "assistant"]
    assert all(turn_tools.OPEN not in r and memory.TOOLS_MASK in r for r in replies[:2])
    assert all(turn_tools.OPEN in r for r in replies[2:])

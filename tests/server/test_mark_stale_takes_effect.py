"""mark_stale: the flag has to actually take the fact out of use.

Before this round `_mark_stale_tier1` wrote `provenance.stale` and nothing anywhere
read it — an action advertised to the model in the `remember` tool schema
(tool_loop.py) that silently did nothing. These tests pin the four places where it
now has to bite, so a future refactor that drops the filter fails here instead of
quietly re-creating a dead capability.

The seam under test is `memory.list_facts` — the single throat every injection site
and RecallExecutor read through — plus the three dedup scanners, which must not treat
a stale row as a live duplicate target (merging into one would leave the restated fact
invisible).
"""
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, UserFact
from server.orchestrator.tool_caller import ToolCaller, reset_caller, set_caller
from server.registry.memory_executors import RecallExecutor, RememberExecutor


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'stale.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


async def _add(maker, content, *, stale=False, sensitive=False):
    prov = {"source_kind": "manual"}
    if stale:
        prov["stale"] = True
        prov["marked_at"] = "2026-01-01T00:00:00"
    async with maker() as s:
        row = UserFact(content=content, source="manual", provenance=prov,
                       sensitive=sensitive)
        s.add(row)
        await s.commit()
        return row.id


# --------------------------------------------------------------------------- #
# the throat
# --------------------------------------------------------------------------- #

async def test_list_facts_hides_a_stale_fact_and_include_stale_shows_it(maker):
    from server.orchestrator import memory
    await _add(maker, "用户住在乌鲁木齐")
    await _add(maker, "用户以前住在北京", stale=True)

    live = [f.content for f in await memory.list_facts()]
    assert live == ["用户住在乌鲁木齐"], "a stale fact must not come back from the throat"

    audit = [f.content for f in await memory.list_facts(include_stale=True)]
    assert len(audit) == 2, "the audit view still has to see it — nothing was deleted"


async def test_facts_text_does_not_inject_a_stale_fact(maker):
    """The point of the flag: it stops reaching the model."""
    from server.orchestrator import memory
    await _add(maker, "用户偏好简短回答")
    await _add(maker, "用户偏好长篇回答", stale=True)

    rendered = await memory.facts_text()
    assert "简短" in rendered
    assert "长篇" not in rendered


async def test_recall_executor_skips_a_stale_fact(maker):
    """RecallExecutor reads the same throat, so it inherits the filter for free —
    asserted anyway, because 'for free' is exactly what a refactor takes away."""
    await _add(maker, "用户在做一个编排器")
    await _add(maker, "用户在做一个爬虫", stale=True)

    out = await RecallExecutor().execute({"query": "用户", "kind": "fact"})
    blob = str(out)
    assert "编排器" in blob
    assert "爬虫" not in blob


# --------------------------------------------------------------------------- #
# dedup — a stale row must not swallow the write that restates it
# --------------------------------------------------------------------------- #

async def test_existing_norms_ignores_a_stale_row(maker):
    from server.services import fact_dedup
    await _add(maker, "用户喜欢猫", stale=True)
    assert fact_dedup.norm("用户喜欢猫") not in await fact_dedup.existing_norms()


async def test_exact_and_near_dup_skip_a_stale_row(maker):
    from server.services import fact_dedup
    await _add(maker, "用户在使用 macOS 26 系统", stale=True)
    async with maker() as s:
        assert await fact_dedup.exact_norm_dup(s, "用户在使用 macOS 26 系统") is None
        assert await fact_dedup.find_near_dup(s, "用户在使用 macOS 26 系统") is None


async def test_restating_a_stale_fact_creates_a_live_one(maker):
    """End to end: mark stale, say it again, and the answer path sees it again."""
    from server.orchestrator import memory
    await _add(maker, "用户的项目叫 Arslan", stale=True)

    await memory.save_facts([{"content": "用户的项目叫 Arslan"}],
                            provenance={"source_kind": "manual"})

    live = [f.content for f in await memory.list_facts()]
    assert live == ["用户的项目叫 Arslan"], "the restated fact must be live, not merged away"
    assert len(await memory.list_facts(include_stale=True)) == 2, "the old row stays"


# --------------------------------------------------------------------------- #
# the toggle
# --------------------------------------------------------------------------- #

async def _remember(args: dict) -> dict:
    """mark_stale is a host-tier action: a spawn is refused upstream, so the caller
    identity is part of what is being tested, not incidental setup."""
    token = set_caller(ToolCaller(actor="host", spawn_id=None, conversation_id="c1"))
    try:
        return await RememberExecutor().execute(args)
    finally:
        reset_caller(token)


async def test_mark_stale_is_a_toggle_that_restores_the_fact(maker):
    """A second mark_stale clears the flag — nothing about the mark is one-way."""
    from server.orchestrator import memory

    fact_id = await _add(maker, "用户在深圳工作")
    args = {"kind": "fact", "action": "mark_stale", "target_id": fact_id, "content": ""}

    first = await _remember(args)
    assert first.get("ok") and first.get("stale") is True
    assert [f.content for f in await memory.list_facts()] == [], "marked: out of use"

    second = await _remember(args)
    assert second.get("ok") and second.get("stale") is False
    assert [f.content for f in await memory.list_facts()] == ["用户在深圳工作"]

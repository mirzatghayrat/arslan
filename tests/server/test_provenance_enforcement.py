"""Provenance is mandatory on every fact write path (brain-P1 Task 3). This is a
programmer guard — raise on empty/missing provenance — kept STRICTLY SEPARATE from
write-time dedup's fail-open discipline (a dedup scan exception never blocks a
write; a missing provenance always does).

Covers: save_facts's raise-on-empty guard, the REAL router call-site
(arslan.py:554, exercised end-to-end via arslan.handle_user_message — not a
save_facts stand-in), add_manual_fact's self-built provenance + valid_from + the
confidence=0.9 debt fix, update_fact's edited_by_user_at merge, and — the BLOCKER
#1 anchor — distill_meta_upflow's REAL production path (not a save_facts
stand-in): it used to construct UserFact directly, bypassing save_facts (and thus
provenance) entirely; grepping for `save_facts(` could never have found that
caller.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, UserFact
from tests.server.conftest import MockAdapter


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'prov.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


# ---------------------------------------------------------------------------
# save_facts: mandatory provenance (programmer guard, not fail-open dedup)
# ---------------------------------------------------------------------------

async def test_save_facts_missing_provenance_kwarg_raises_typeerror(maker):
    """provenance is keyword-only with no default: omitting it entirely is a
    Python-level signature error (TypeError), distinct from the ValueError the
    top-of-function guard raises for an explicitly-empty {}."""
    from server.orchestrator import memory
    with pytest.raises(TypeError):
        await memory.save_facts([{"content": "x"}])  # type: ignore[call-arg]


async def test_save_facts_empty_provenance_raises_valueerror(maker):
    from server.orchestrator import memory
    with pytest.raises(ValueError):
        await memory.save_facts([{"content": "x"}], provenance={})


async def test_save_facts_none_provenance_raises_valueerror(maker):
    from server.orchestrator import memory
    with pytest.raises(ValueError):
        await memory.save_facts([{"content": "x"}], provenance=None)


async def test_save_facts_guard_fires_before_any_dedup_scan(maker, monkeypatch):
    """The provenance guard must be unconditional — it must raise even if the
    dedup scanners underneath are broken. Proves the two disciplines don't get
    conflated: a missing provenance ALWAYS raises regardless of dedup health."""
    from server.orchestrator import memory

    async def boom(db, content):
        raise RuntimeError("dedup exploded")

    monkeypatch.setattr("server.services.fact_dedup.exact_norm_dup", boom)
    monkeypatch.setattr("server.services.fact_dedup.find_near_dup", boom)
    with pytest.raises(ValueError):
        await memory.save_facts([{"content": "x"}], provenance={})


async def test_save_facts_stores_provenance_and_valid_from(maker):
    from server.orchestrator import memory
    prov = {"source_kind": "router", "conversation_id": "c1"}
    created = await memory.save_facts([{"content": "喜欢简短回答"}], provenance=prov)
    assert len(created) == 1
    assert created[0].provenance == prov
    assert created[0].valid_from is not None


# ---------------------------------------------------------------------------
# router path: the REAL call-site (arslan.py:554), exercised end-to-end
# ---------------------------------------------------------------------------

async def test_router_path_writes_provenance(maker, monkeypatch):
    """arslan.handle_user_message -> router.route returning new_facts -> the REAL
    memory.save_facts(..., provenance={"source_kind": "router", ...}) call-site
    at arslan.py:554 (not a stand-in / not calling save_facts directly)."""
    from server.orchestrator import arslan, router, tool_loop

    async def _fake_route(conv, msg):
        return router.RouterResult(
            action="answer",
            new_facts=[{"content": "偏好中文沟通", "sensitive": False}],
        )

    monkeypatch.setattr(arslan.router, "route", _fake_route)
    adapter = MockAdapter(stream_chunks=["ok"], chat_content="ok")
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    events: list = []
    await arslan.handle_user_message("conv-router", "你好", events.append)

    async with maker() as db:
        rows = (await db.execute(select(UserFact))).scalars().all()
    assert len(rows) == 1
    assert rows[0].provenance == {"source_kind": "router", "conversation_id": "conv-router"}
    assert rows[0].valid_from is not None


# ---------------------------------------------------------------------------
# add_manual_fact: self-built provenance + valid_from + confidence=0.9 debt fix
# ---------------------------------------------------------------------------

async def test_add_manual_fact_provenance_valid_from_and_confidence(maker):
    from server.orchestrator import memory
    row = await memory.add_manual_fact("喜欢极简风格")
    assert row.provenance == {"source_kind": "manual", "via": "api"}
    assert row.valid_from is not None
    assert row.confidence == 0.9  # debt#5: was previously unset (NULL)


# ---------------------------------------------------------------------------
# update_fact: edits merge edited_by_user_at into provenance (an auto fact a
# human later edits becomes distinguishable from a still-pristine auto fact)
# ---------------------------------------------------------------------------

async def test_update_fact_marks_edited_by_user(maker):
    from server.orchestrator import memory
    created = await memory.save_facts(
        [{"content": "喜欢猫", "source": "auto"}],
        provenance={"source_kind": "router", "conversation_id": "c9"},
    )
    fid = created[0].id
    updated = await memory.update_fact(fid, content="喜欢猫和狗")
    assert updated.provenance["source_kind"] == "router"  # original provenance preserved
    assert "edited_by_user_at" in updated.provenance      # + edit marker merged in
    assert updated.provenance["edited_by_user_at"]         # non-empty iso string


async def test_update_fact_no_edit_fields_leaves_provenance_untouched(maker):
    """Calling update_fact with neither content nor sensitive (a no-op edit) must
    not stamp edited_by_user_at — the marker means an ACTUAL edit happened."""
    from server.orchestrator import memory
    created = await memory.save_facts(
        [{"content": "喜欢猫", "source": "auto"}],
        provenance={"source_kind": "router", "conversation_id": "c9"},
    )
    fid = created[0].id
    updated = await memory.update_fact(fid)
    assert "edited_by_user_at" not in (updated.provenance or {})


# ---------------------------------------------------------------------------
# learnings: valid_from set on write (source_kind/source_ref already carry
# provenance for this table — no separate provenance column, per the P1 spec)
# ---------------------------------------------------------------------------

async def test_learning_write_sets_valid_from(maker):
    from server.db.models import Learning
    from server.services.learning_service import _write

    async with maker() as s:
        await s.execute(
            sa_text("CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts USING fts5(text)")
        )
        await s.commit()

    n = await _write("总结要先给结论", "l1", "session", {"x": 1}, None)
    assert n > 0                                        # P2: n is now a real id, not a 1/0 flag
    async with maker() as s:
        row = (await s.execute(select(Learning).where(Learning.content == "总结要先给结论"))).scalar_one()
    assert row.valid_from is not None


# ---------------------------------------------------------------------------
# BLOCKER #1 anchor: distill_meta_upflow's REAL path (not a save_facts
# stand-in) routed through memory.save_facts with source_kind='upflow'.
# ---------------------------------------------------------------------------

class _Spawn:
    id = 11
    name = "研究员"
    domain_category = "research"


async def test_upflow_real_path_gets_provenance(maker, monkeypatch):
    """Calls distill_service.distill_meta_upflow directly (the real production
    function) — not a save_facts substitute — and asserts the row landing in
    user_facts carries provenance={"source_kind": "upflow", "spawn_id": ...} and
    a non-null valid_from. This is the BLOCKER #1 anchor: `grep save_facts(`
    could never find this caller, since it used to bypass save_facts entirely
    via a direct UserFact(...) construction."""
    from server.services import distill_service

    class _Resp:
        content = "用户偏好数据驱动决策"

    class _Adapter:
        async def chat(self, system, user, **kw):
            return _Resp()

    async def _fake_build_adapter(*a, **k):
        return _Adapter()

    monkeypatch.setattr(distill_service, "build_adapter", _fake_build_adapter)

    written = await distill_service.distill_meta_upflow(_Spawn(), ["数据驱动"])
    assert written == "用户偏好数据驱动决策"

    async with maker() as s:
        rows = (await s.execute(select(UserFact))).scalars().all()
    assert len(rows) == 1
    assert rows[0].content == "用户偏好数据驱动决策"
    assert rows[0].source == "upflow"
    assert rows[0].provenance == {"source_kind": "upflow", "spawn_id": 11}
    assert rows[0].valid_from is not None


async def test_upflow_exact_dup_of_existing_merges_not_appends(maker, monkeypatch):
    """When the LLM's upflow suggestion exactly (norm) matches an existing ACTIVE
    fact, save_facts's exact-norm phase merge-bumps rather than inserting a
    second row — and distill_meta_upflow returns None (nothing NEW written),
    matching the old local-dedup-skip semantics via the new, disciplined path."""
    from server.orchestrator import memory
    from server.services import distill_service

    await memory.add_manual_fact("用户偏口语、忌硬广")

    class _Resp:
        content = "用户偏口语、忌硬广"  # exact same content

    class _Adapter:
        async def chat(self, system, user, **kw):
            return _Resp()

    async def _fake_build_adapter(*a, **k):
        return _Adapter()

    monkeypatch.setattr(distill_service, "build_adapter", _fake_build_adapter)

    written = await distill_service.distill_meta_upflow(_Spawn(), ["偏好"])
    assert written is None  # merge-bumped, not a NEW row

    async with maker() as s:
        rows = (await s.execute(select(UserFact))).scalars().all()
    assert len(rows) == 1  # still exactly one row

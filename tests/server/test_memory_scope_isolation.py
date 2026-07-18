"""brain-P2 Task 4: RememberExecutor's spawn-actor scope isolation.

A spawn actor may freely write its OWN well (learning append/supersede,
single-item preference append) but NEVER writes a global table (fact/note)
directly — those always downgrade to a Tier2 MemoryProposal, regardless of
action. A spawn also never crosses into another spawn's well (supersede scope
check), and an actor=="spawn" caller without a real spawn_id is refused exactly
like caller=None (both fail-closed — never guess).

Also covers: host writing a spawn's preference (always a Tier2 propose with an
explicit target spawn — target_id doubles as the target spawn id since the
native tool schema, frozen in Task 3, has no separate target_spawn_id field);
zero contextvar residue across two dispatches; and the dual-track provenance
discipline (fact rides the JSON `provenance` column's `actor` key, learning
rides `source_ref`'s `actor` key — both distinguishable from the pre-existing
distill mechanism, which never sets an "actor" key and uses
source_kind="distill"/"feedback"/"upflow", never "agentic").
"""
from __future__ import annotations

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Learning, MemoryProposal, Spawn, UserFact
from server.orchestrator.tool_caller import ToolCaller, reset_caller, set_caller
from server.registry.memory_executors import RememberExecutor


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'scope.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(text)")
        await conn.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts USING fts5(text)")
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest_asyncio.fixture(autouse=True)
async def _no_caller_leak():
    from server.orchestrator import tool_caller
    assert tool_caller.current_caller() is None
    yield
    assert tool_caller.current_caller() is None


async def _seed_spawn(maker, spawn_id: int, name: str, memory_facts: list | None = None) -> None:
    async with maker() as db:
        db.add(Spawn(id=spawn_id, name=name, domain_category="d", system_prompt="p",
                     memory_facts=memory_facts or []))
        await db.commit()


async def _remember(args: dict, caller: ToolCaller) -> dict:
    token = set_caller(caller)
    try:
        return await RememberExecutor().execute(args)
    finally:
        reset_caller(token)


# ---------------------------------------------------------------------------
# fail-closed identity
# ---------------------------------------------------------------------------

async def test_caller_none_refuses_write(maker):
    from server.orchestrator import tool_caller
    assert tool_caller.current_caller() is None
    out = await RememberExecutor().execute({"kind": "fact", "action": "append", "content": "x"})
    assert out == {"ok": False, "error": "no caller context; refusing to write"}


async def test_spawn_actor_without_real_spawn_id_is_refused(maker):
    out = await _remember(
        {"kind": "learning", "action": "append", "content": "x"},
        ToolCaller(actor="spawn", spawn_id=None, conversation_id="c1"))
    assert out["ok"] is False
    assert "spawn_id" in out["error"]


async def test_unknown_actor_is_refused_not_treated_as_host(maker):
    """Fail-closed on identity (whole-branch review): the routing treats
    'not spawn' as host, so a garbage actor string must be refused explicitly
    rather than inherit host privileges (direct global writes)."""
    out = await _remember(
        {"kind": "fact", "action": "append", "content": "别把我当 host"},
        ToolCaller(actor="root", spawn_id=None, conversation_id="c1"))
    assert out["ok"] is False
    assert "unknown caller actor" in out["error"]
    # and nothing was written
    async with maker() as db:
        facts = (await db.execute(select(UserFact))).scalars().all()
    assert facts == []


async def test_contextvar_has_zero_residue_across_two_dispatches(maker):
    from server.orchestrator import tool_caller

    await _seed_spawn(maker, 9, "分身9")
    out1 = await _remember(
        {"kind": "learning", "action": "append", "content": "第一次心得"},
        ToolCaller(actor="spawn", spawn_id=9, conversation_id="c1"))
    assert out1["ok"] is True
    assert tool_caller.current_caller() is None            # reset after first dispatch

    out2 = await _remember(
        {"kind": "fact", "action": "append", "content": "第二次事实"},
        ToolCaller(actor="host", spawn_id=None, conversation_id="c2"))
    assert out2["ok"] is True
    assert tool_caller.current_caller() is None            # reset after second — no bleed-through


# ---------------------------------------------------------------------------
# spawn writes its own well directly (Tier1, no scope violation)
# ---------------------------------------------------------------------------

async def test_spawn_append_learning_writes_own_well(maker):
    await _seed_spawn(maker, 5, "分身5")
    out = await _remember(
        {"kind": "learning", "action": "append", "content": "调用工具前先看文档"},
        ToolCaller(actor="spawn", spawn_id=5, conversation_id="c1"))
    assert out["ok"] is True
    async with maker() as db:
        row = await db.get(Learning, out["id"])
    assert row.spawn_id == 5
    assert row.source_ref["actor"] == "spawn:5"


async def test_spawn_append_preference_appends_single_item_preserving_existing(maker):
    await _seed_spawn(maker, 6, "分身6", memory_facts=["已有偏好A"])
    out = await _remember(
        {"kind": "preference", "action": "append", "content": "新偏好B"},
        ToolCaller(actor="spawn", spawn_id=6, conversation_id="c1"))
    assert out["ok"] is True
    async with maker() as db:
        spawn = await db.get(Spawn, 6)
    assert spawn.memory_facts == ["已有偏好A", "新偏好B"]     # existing item preserved, not overwritten


# ---------------------------------------------------------------------------
# spawn writing a GLOBAL table (fact/note) always downgrades to a Tier2 proposal
# ---------------------------------------------------------------------------

async def test_spawn_append_fact_downgrades_to_append_suspect_proposal(maker):
    await _seed_spawn(maker, 7, "分身7")
    out = await _remember(
        {"kind": "fact", "action": "append", "content": "分身想记的事实"},
        ToolCaller(actor="spawn", spawn_id=7, conversation_id="c1"))
    assert out["ok"] is True and out["proposed"] is True

    async with maker() as db:
        facts = (await db.execute(select(UserFact))).scalars().all()
        proposals = (await db.execute(select(MemoryProposal))).scalars().all()
    assert facts == []                                     # never written directly
    assert len(proposals) == 1
    p = proposals[0]
    assert p.kind == "append_suspect"
    assert p.table_name == "user_facts"
    assert p.provenance["content"] == "分身想记的事实"       # accept() materializes from here (Task 5)


async def test_spawn_supersede_note_is_a_clean_error_not_a_proposal(maker):
    """Notes have no superseded_by column (no temporal concept, plan's "矩阵
    按表能力") — unlike fact, a spawn attempting to supersede/mark_stale a
    note must be refused cleanly, not downgraded to an edit_high_conf_suspect
    proposal Task 5's accept endpoint could never actually resolve (every
    accept attempt would 422 forever — a permanent dismiss-only dead end)."""
    await _seed_spawn(maker, 22, "分身22")
    out = await _remember(
        {"kind": "note", "action": "supersede", "target_id": 1, "content": "编辑笔记?"},
        ToolCaller(actor="spawn", spawn_id=22, conversation_id="c1"))
    assert out["ok"] is False
    assert "unsupported" in out["error"]

    async with maker() as db:
        proposals = (await db.execute(select(MemoryProposal))).scalars().all()
    assert proposals == []


async def test_spawn_edit_fact_downgrades_to_edit_high_conf_proposal(maker):
    """'编辑高置信 fact' anchor: a spawn attempting to supersede a global fact
    never writes directly — it downgrades to an edit_high_conf_suspect
    proposal (Task 5's accept endpoint materializes it)."""
    await _seed_spawn(maker, 8, "分身8")
    async with maker() as db:
        target = UserFact(content="用户很在意隐私", source="manual",
                          provenance={"source_kind": "manual"})
        db.add(target)
        await db.commit()
        target_id = target.id

    out = await _remember(
        {"kind": "fact", "action": "supersede", "target_id": target_id,
         "content": "用户其实不太在意隐私"},
        ToolCaller(actor="spawn", spawn_id=8, conversation_id="c1"))
    assert out["ok"] is True and out["proposed"] is True

    async with maker() as db:
        proposals = (await db.execute(select(MemoryProposal))).scalars().all()
        untouched = await db.get(UserFact, target_id)
    assert len(proposals) == 1
    p = proposals[0]
    assert p.kind == "edit_high_conf_suspect"
    assert p.table_name == "user_facts"
    assert p.old_id == target_id
    assert p.provenance["content"] == "用户其实不太在意隐私"
    assert untouched.superseded_by is None                  # never touched directly


# ---------------------------------------------------------------------------
# host writing a spawn's preference always proposes (needs an explicit target)
# ---------------------------------------------------------------------------

async def test_host_preference_append_creates_overwrite_proposal_with_target(maker):
    await _seed_spawn(maker, 10, "分身10", memory_facts=["旧偏好"])
    out = await _remember(
        {"kind": "preference", "action": "append", "content": "host 建议的新偏好",
         "target_id": 10},
        ToolCaller(actor="host", spawn_id=None, conversation_id="c1"))
    assert out["ok"] is True and out["proposed"] is True

    async with maker() as db:
        proposals = (await db.execute(select(MemoryProposal))).scalars().all()
        spawn = await db.get(Spawn, 10)
    assert len(proposals) == 1
    p = proposals[0]
    assert p.kind == "preference_overwrite_suspect"
    assert p.provenance["target_spawn_id"] == 10
    assert p.provenance["new_array"] == ["旧偏好", "host 建议的新偏好"]
    assert spawn.memory_facts == ["旧偏好"]                  # not applied yet — pending accept (Task 5)


async def test_host_preference_append_missing_target_id_is_a_clean_error(maker):
    out = await _remember(
        {"kind": "preference", "action": "append", "content": "x"},
        ToolCaller(actor="host", spawn_id=None, conversation_id="c1"))
    assert out["ok"] is False
    assert "target_id" in out["error"]


# ---------------------------------------------------------------------------
# preference delete — ownership guard (Task 5 self-check, Minor #3): a spawn
# may only ever propose deleting its OWN preferences; host always needs an
# explicit target (mirrors the append/overwrite case above). Task 5's accept
# endpoint reads provenance["target_spawn_id"] to materialize the delete, so
# it must always be present and correct on the proposal row.
# ---------------------------------------------------------------------------

async def test_spawn_delete_own_preference_creates_scoped_proposal(maker):
    await _seed_spawn(maker, 12, "分身12", memory_facts=["旧偏好"])
    out = await _remember(
        {"kind": "preference", "action": "delete"},
        ToolCaller(actor="spawn", spawn_id=12, conversation_id="c1"))
    assert out["ok"] is True and out["proposed"] is True

    async with maker() as db:
        proposals = (await db.execute(select(MemoryProposal))).scalars().all()
        spawn = await db.get(Spawn, 12)
    assert len(proposals) == 1
    p = proposals[0]
    assert p.kind == "delete_suspect"
    assert p.table_name == "spawns"
    assert p.old_id == 12
    assert p.provenance["target_spawn_id"] == 12
    assert spawn.memory_facts == ["旧偏好"]                  # not applied yet — pending accept


async def test_spawn_cannot_propose_deleting_another_spawns_preference(maker):
    await _seed_spawn(maker, 13, "分身13", memory_facts=["A的偏好"])
    await _seed_spawn(maker, 14, "分身14", memory_facts=["B的偏好"])
    out = await _remember(
        {"kind": "preference", "action": "delete", "target_id": 14},
        ToolCaller(actor="spawn", spawn_id=13, conversation_id="c1"))
    assert out["ok"] is False
    assert "another spawn" in out["error"]

    async with maker() as db:
        proposals = (await db.execute(select(MemoryProposal))).scalars().all()
        spawn14 = await db.get(Spawn, 14)
    assert proposals == []                                   # nothing was proposed either
    assert spawn14.memory_facts == ["B的偏好"]                # untouched


async def test_host_delete_preference_creates_scoped_proposal_with_target(maker):
    await _seed_spawn(maker, 15, "分身15", memory_facts=["旧偏好"])
    out = await _remember(
        {"kind": "preference", "action": "delete", "target_id": 15},
        ToolCaller(actor="host", spawn_id=None, conversation_id="c1"))
    assert out["ok"] is True and out["proposed"] is True

    async with maker() as db:
        proposals = (await db.execute(select(MemoryProposal))).scalars().all()
    assert len(proposals) == 1
    assert proposals[0].provenance["target_spawn_id"] == 15


async def test_host_delete_preference_missing_target_id_is_a_clean_error(maker):
    out = await _remember(
        {"kind": "preference", "action": "delete"},
        ToolCaller(actor="host", spawn_id=None, conversation_id="c1"))
    assert out["ok"] is False
    assert "target_id" in out["error"]
    async with maker() as db:
        proposals = (await db.execute(select(MemoryProposal))).scalars().all()
    assert proposals == []


# ---------------------------------------------------------------------------
# cross-well supersede rejection
# ---------------------------------------------------------------------------

async def test_spawn_cannot_supersede_another_spawns_learning(maker):
    await _seed_spawn(maker, 20, "分身20")
    await _seed_spawn(maker, 21, "分身21")
    async with maker() as db:
        other = Learning(content="别人分身的心得", source_kind="agentic",
                         source_ref={"actor": "spawn:21"}, spawn_id=21)
        db.add(other)
        await db.commit()
        other_id = other.id

    out = await _remember(
        {"kind": "learning", "action": "supersede", "target_id": other_id,
         "content": "我(分身20)想取代它"},
        ToolCaller(actor="spawn", spawn_id=20, conversation_id="c1"))
    assert out["ok"] is False
    assert "scope" in out["error"].lower() or "cross" in out["error"].lower()

    async with maker() as db:
        untouched = await db.get(Learning, other_id)
        rows = (await db.execute(select(Learning))).scalars().all()
    assert untouched.superseded_by is None
    assert len(rows) == 1                                    # no new row was written either


# ---------------------------------------------------------------------------
# dual-track provenance: fact rides the JSON `provenance` column, learning
# rides `source_ref` — both distinguishable from the existing distill mechanism.
# ---------------------------------------------------------------------------

async def test_dual_track_provenance_distinguishable_from_distill(maker):
    await _seed_spawn(maker, 30, "分身30")
    fact_out = await _remember(
        {"kind": "fact", "action": "append", "content": "轨道一:JSON provenance"},
        ToolCaller(actor="host", spawn_id=None, conversation_id="c1"))
    learning_out = await _remember(
        {"kind": "learning", "action": "append", "content": "轨道二:source_ref"},
        ToolCaller(actor="spawn", spawn_id=30, conversation_id="c2"))

    async with maker() as db:
        fact_row = await db.get(UserFact, fact_out["id"])
        learning_row = await db.get(Learning, learning_out["id"])

    assert fact_row.provenance["source_kind"] == "agentic"
    assert fact_row.provenance["actor"] == "host"

    assert learning_row.source_kind == "agentic"            # never "distill"/"feedback"/"upflow"
    assert learning_row.source_ref["actor"] == "spawn:30"    # distill's source_ref never has "actor"

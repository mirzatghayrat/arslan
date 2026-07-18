"""brain-P2 Task 3: recall/remember registration + skeletons.

Covers:
  - catalog registration: "second_brain" toolset (key avoids the literal "memory" —
    that key is in seeder.RETIRED_TOOLSET_KEYS and gets deleted every boot).
  - EXECUTORS wiring: RecallExecutor + RememberExecutor instances under keys
    "recall"/"remember".
  - host wiring: arslan._arslan_tools() offers both.
  - native tool-calling param schemas for both.
  - RecallExecutor: 🔴 BLOCKER fix — sensitive-fact fail-closed isolation. Only an
    explicit host caller sees sensitive facts; a spawn actor OR a missing caller
    (current_caller() is None) must never see them.
  - RememberExecutor: fail-closed on caller=None. Task 3 only wired the
    HOST-path append for kind in {fact, learning, note}; the full three-tier
    authorization (Tier1 direct / Tier2 propose / capability errors) is
    covered by tests/server/test_memory_write_tiers.py (host) and
    tests/server/test_memory_scope_isolation.py (spawn scope, brain-P2 Task 4).
"""
from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Learning, Note, UserFact
from server.orchestrator.tool_caller import ToolCaller, reset_caller, set_caller


@pytest_asyncio.fixture
async def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'mem_tools.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # FTS5 virtual tables aren't ORM models (created by migrations, not
        # create_all) — note_service.create/learning_service._write insert into
        # them directly. Same convention as test_note_service.py/test_learning_service.py.
        await conn.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(text)")
        await conn.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts USING fts5(text)")
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


@pytest_asyncio.fixture(autouse=True)
async def _no_caller_leak():
    """Sanity: nothing leaked in from another test — mirrors test_tool_caller.py's
    residual-free discipline."""
    from server.orchestrator import tool_caller
    assert tool_caller.current_caller() is None
    yield
    assert tool_caller.current_caller() is None


# ---------------------------------------------------------------------------
# Catalog + registry wiring
# ---------------------------------------------------------------------------

def test_second_brain_toolset_key_avoids_literal_memory():
    """The retired-key list (seeder.RETIRED_TOOLSET_KEYS) contains the literal
    "memory" and is deleted on every boot — the new toolset AND both tool keys
    must not collide with it."""
    from server.registry.seed_catalog import TOOLSETS

    keys = {ts["key"] for ts in TOOLSETS}
    assert "second_brain" in keys
    assert "memory" not in keys

    second_brain = next(ts for ts in TOOLSETS if ts["key"] == "second_brain")
    tool_keys = {t[0] for t in second_brain["tools"]}
    assert tool_keys == {"recall", "remember"}
    assert "memory" not in tool_keys
    assert second_brain["tier"] == "safe"
    assert second_brain["status"] == "wired"


async def test_second_brain_toolset_seeds_idempotently(maker):
    from sqlalchemy import select

    from server.db.models import Tool, Toolset
    from server.registry.seeder import seed_registry

    await seed_registry()
    await seed_registry()  # idempotent upsert, no migration involved

    async with maker() as s:
        ts = await s.get(Toolset, "second_brain")
        assert ts is not None and ts.status == "wired" and ts.tier == "safe"
        tools = (await s.execute(
            select(Tool).where(Tool.toolset_key == "second_brain"))).scalars().all()
    assert {t.key for t in tools} == {"recall", "remember"}
    assert all(t.tier == "safe" and t.status == "wired" for t in tools)


def test_executors_map_has_recall_and_remember():
    from server.registry.executors import EXECUTORS
    from server.registry.memory_executors import RecallExecutor, RememberExecutor

    assert isinstance(EXECUTORS["recall"], RecallExecutor)
    assert isinstance(EXECUTORS["remember"], RememberExecutor)
    assert EXECUTORS["recall"].key == "recall"
    assert EXECUTORS["remember"].key == "remember"


async def test_arslan_host_tools_include_recall_and_remember(monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from server.orchestrator import arslan

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)

    tools = await arslan._arslan_tools()
    keys = {t["key"] for t in tools}
    assert {"recall", "remember"} <= keys


def test_native_param_schemas_cover_recall_and_remember():
    from server.orchestrator.tool_loop import _NATIVE_PARAM_SCHEMAS

    recall = _NATIVE_PARAM_SCHEMAS["recall"]
    assert recall["properties"]["query"]["type"] == "string"
    assert "kind" in recall["properties"]
    assert "query" in recall.get("required", [])

    remember = _NATIVE_PARAM_SCHEMAS["remember"]
    props = remember["properties"]
    assert set(props["kind"]["enum"]) == {"fact", "learning", "note", "preference"}
    assert set(props["action"]["enum"]) == {"append", "supersede", "mark_stale", "delete"}
    assert props["content"]["type"] == "string"
    assert "target_id" in props
    required = set(remember.get("required", []))
    assert {"kind", "action", "content"} <= required


# ---------------------------------------------------------------------------
# RecallExecutor — 🔴 BLOCKER: sensitive-fact fail-closed isolation
# ---------------------------------------------------------------------------

async def _seed_facts(maker):
    from sqlalchemy import text as sa_text
    async with maker() as db:
        db.add(UserFact(content="user's dog is named Rex", source="manual",
                        sensitive=False, provenance={"source_kind": "manual"}))
        db.add(UserFact(content="user's SSN is 123-45-6789", source="manual",
                        sensitive=True, provenance={"source_kind": "manual"}))
        await db.commit()
        # A raw/legacy row with NULL sensitive must be treated as sensitive (fail-closed),
        # exactly like memory.facts_text's discipline. Inserted via raw SQL because the ORM
        # column's Python-side default=False fires even for an EXPLICIT sensitive=None
        # (verified: UserFact(..., sensitive=None) persists as 0, not NULL) — a real NULL
        # only occurs via a raw insert bypassing the ORM default, which is exactly the
        # "raw insert 可产生 NULL sensitive" scenario memory.py's facts_text docstring warns about.
        await db.execute(sa_text(
            "INSERT INTO user_facts (content, source, sensitive, provenance) "
            "VALUES (:c, :s, NULL, :p)"),
            {"c": "unclassified legacy fact", "s": "auto", "p": "{}"})
        await db.commit()


async def _recall(monkeypatch, query="fact"):
    """Runs RecallExecutor with the material/learning/note route (knowledge.retrieve_scoped)
    stubbed to empty — these tests are about the fact-sensitivity throat, not FTS/vector
    retrieval (covered separately by tests/server/test_knowledge.py)."""
    from server.services import knowledge

    async def _no_material(*a, **kw):
        return []

    monkeypatch.setattr(knowledge, "retrieve_scoped", _no_material)

    from server.registry.memory_executors import RecallExecutor
    return await RecallExecutor().execute({"query": query, "kind": "fact"})


async def test_recall_host_sees_sensitive_facts(maker, monkeypatch):
    """include_sensitive=True (host) skips the sensitive filter entirely — same
    discipline as memory.facts_text(include_sensitive=True): a NULL-sensitive
    legacy row is included too, since no filter is applied at all for host."""
    await _seed_facts(maker)
    token = set_caller(ToolCaller(actor="host", spawn_id=None, conversation_id="c1"))
    try:
        out = await _recall(monkeypatch)
    finally:
        reset_caller(token)
    assert out["ok"] is True
    contents = {h["content"] for h in out["hits"]}
    assert "user's dog is named Rex" in contents
    assert "user's SSN is 123-45-6789" in contents          # host sees sensitive
    assert "unclassified legacy fact" in contents            # host: no filter applied at all


async def test_recall_spawn_never_sees_sensitive_facts(maker, monkeypatch):
    await _seed_facts(maker)
    token = set_caller(ToolCaller(actor="spawn", spawn_id=7, conversation_id="c1"))
    try:
        out = await _recall(monkeypatch)
    finally:
        reset_caller(token)
    assert out["ok"] is True
    contents = {h["content"] for h in out["hits"]}
    assert "user's dog is named Rex" in contents              # non-sensitive: visible
    assert "user's SSN is 123-45-6789" not in contents         # sensitive: hidden
    assert "unclassified legacy fact" not in contents          # NULL treated as sensitive: hidden


async def test_recall_caller_none_fails_closed_on_sensitive_facts(maker, monkeypatch):
    """No caller set at all (current_caller() is None) must ALSO exclude sensitive
    facts — fail-closed, not 'guess host'."""
    await _seed_facts(maker)
    from server.orchestrator import tool_caller
    assert tool_caller.current_caller() is None
    out = await _recall(monkeypatch)
    assert out["ok"] is True
    contents = {h["content"] for h in out["hits"]}
    assert "user's dog is named Rex" in contents
    assert "user's SSN is 123-45-6789" not in contents
    assert "unclassified legacy fact" not in contents


async def test_recall_only_returns_active_facts(maker, monkeypatch):
    """list_facts() defaults to active-only (superseded_by IS NULL) — a superseded
    fact must not resurface via recall."""
    async with maker() as db:
        old = UserFact(content="old address", source="manual", sensitive=False,
                       provenance={"source_kind": "manual"})
        db.add(old)
        await db.flush()
        old.superseded_by = 999  # pretend something replaced it
        await db.commit()

    token = set_caller(ToolCaller(actor="host", spawn_id=None, conversation_id="c1"))
    try:
        out = await _recall(monkeypatch, query="address")
    finally:
        reset_caller(token)
    contents = {h["content"] for h in out["hits"]}
    assert "old address" not in contents


# ---------------------------------------------------------------------------
# RememberExecutor — fail-closed on caller=None; Task-3 append-only scope
# ---------------------------------------------------------------------------

async def test_remember_refuses_when_caller_is_none(maker):
    from server.orchestrator import tool_caller
    assert tool_caller.current_caller() is None
    from server.registry.memory_executors import RememberExecutor
    out = await RememberExecutor().execute(
        {"kind": "fact", "action": "append", "content": "x"})
    assert out == {"ok": False, "error": "no caller context; refusing to write"}


# Task 3's "every non-Task-3 combo returns not yet implemented" coverage is
# superseded by Task 4, which completes the tiering for every (kind, action,
# actor) combination (Tier1 direct / Tier2 propose / a clean capability error —
# never a bare "not yet implemented" for anything in the schema's enum space).
# See tests/server/test_memory_write_tiers.py (host Tier1/Tier2 + matrix
# negatives) and tests/server/test_memory_scope_isolation.py (spawn scope,
# cross-well rejection, preference ownership, fail-closed identity) for the
# real coverage.


async def test_remember_host_append_fact_direct_writes_with_provenance(maker):
    from sqlalchemy import select

    from server.registry.memory_executors import RememberExecutor
    token = set_caller(ToolCaller(actor="host", spawn_id=None, conversation_id="conv-1"))
    try:
        out = await RememberExecutor().execute(
            {"kind": "fact", "action": "append", "content": "prefers dark mode"})
    finally:
        reset_caller(token)
    assert out["ok"] is True
    assert isinstance(out.get("id"), int)

    async with maker() as db:
        rows = (await db.execute(select(UserFact))).scalars().all()
    matches = [r for r in rows if r.content == "prefers dark mode"]
    assert len(matches) == 1
    prov = matches[0].provenance
    assert prov["source_kind"] == "agentic"
    assert prov["actor"] == "host"
    assert prov["conversation_id"] == "conv-1"


async def test_remember_host_append_note_direct_writes(maker):
    from sqlalchemy import select

    from server.registry.memory_executors import RememberExecutor
    token = set_caller(ToolCaller(actor="host", spawn_id=None, conversation_id="conv-2"))
    try:
        out = await RememberExecutor().execute(
            {"kind": "note", "action": "append", "content": "remember to check the deploy checklist"})
    finally:
        reset_caller(token)
    assert out["ok"] is True
    assert isinstance(out.get("id"), int)

    async with maker() as db:
        rows = (await db.execute(select(Note))).scalars().all()
    assert any("deploy checklist" in r.content for r in rows)


async def test_remember_host_append_learning_direct_writes(maker):
    from sqlalchemy import select

    from server.registry.memory_executors import RememberExecutor
    token = set_caller(ToolCaller(actor="host", spawn_id=None, conversation_id="conv-3"))
    try:
        out = await RememberExecutor().execute(
            {"kind": "learning", "action": "append",
             "content": "always confirm before deleting a memory row"})
    finally:
        reset_caller(token)
    assert out["ok"] is True

    async with maker() as db:
        rows = (await db.execute(select(Learning))).scalars().all()
    assert any("confirm before deleting" in r.content for r in rows)
    assert all(r.source_kind == "agentic" for r in rows)


async def test_remember_missing_content_is_a_clean_error(maker):
    from server.registry.memory_executors import RememberExecutor
    token = set_caller(ToolCaller(actor="host", spawn_id=None, conversation_id="c1"))
    try:
        out = await RememberExecutor().execute(
            {"kind": "fact", "action": "append", "content": "   "})
    finally:
        reset_caller(token)
    assert out["ok"] is False
    assert "content" in out["error"].lower()

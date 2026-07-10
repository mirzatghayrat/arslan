"""Synthetic cold-start corpus generator + first-replay validator (S2 E6).

The USER-LOCKED invariant is named exactly as the caller will verify:
`test_holdout_variant_never_lands_in_propose` — a variant of a HOLDOUT real task
inherits 'holdout' (via the SAME splitter build_corpus uses) and can never leak
into the propose set, even when the variant's OWN text would hash to propose.

All LLM calls are stubbed; split inheritance is exercised against the real
`replay_gate._split_side`, so the tests are robust to the actual hash function.
"""
import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.db import session as db_session
from server.db.models import ArslanMessage, Base, Run, RunStep, Spawn, SyntheticTask
from server.services import replay_gate, replay_run, synthetic_corpus
from server.services.prompts import synthetic_corpus as prompts
from server.services.replay_gate import _split_side

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def memdb(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Session)
    yield Session


# ── helpers ────────────────────────────────────────────────────────────────────────────

def _find_task(spawn_id: int, side: str, prefix: str) -> str:
    """A task string that deterministically hashes to `side` for `spawn_id`."""
    i = 0
    while True:
        t = f"{prefix}-{i}"
        if _split_side(spawn_id, t) == side:
            return t
        i += 1


class _Resp:
    def __init__(self, content):
        self.content = content


class _StubAdapter:
    """Branches on the system prompt: variant call → the mapped variants for the source
    task found in the user text; domain call → the fixed domain list."""

    def __init__(self, *, domain=None, variant_map=None):
        self._domain = domain or []
        self._variant_map = variant_map or {}
        self.calls = []

    async def chat(self, *, system, user):
        self.calls.append((system, user))
        if system == prompts.build_variant_system(
                synthetic_corpus.REPLAY_SAFE_BUILTINS):
            for src, variants in self._variant_map.items():
                if src in user:
                    return _Resp(json.dumps({"tasks": variants}))
            return _Resp(json.dumps({"tasks": []}))
        return _Resp(json.dumps({"tasks": self._domain}))


async def _seed_spawn(Session, spawn_id=1):
    async with Session() as db:
        db.add(Spawn(id=spawn_id, name="fin", domain_category="finance",
                     persona_role="analyst", capabilities=["render_chart"],
                     system_prompt="## Role\nYou are an analyst."))
        await db.commit()


async def _seed_real_run(Session, *, spawn_id=1, task, output="delivered"):
    """A scored live epoch=1 run + its spawn_summary output → visible to replay_set.build."""
    async with Session() as db:
        run = Run(conversation_id="c", spawn_id=spawn_id, spawn_name="fin",
                  user_message=task, status="scored", task_tokens=5,
                  overall_score=7.0, kind="live", epoch=1)
        db.add(run)
        await db.commit()
        await db.refresh(run)
        db.add(ArslanMessage(conversation_id="c", role="spawn_summary",
                             content="s", display_content=output, run_id=run.id))
        await db.commit()
        return run.id


# ── CRITICAL: split inheritance (named exactly) ───────────────────────────────────────

async def test_holdout_variant_never_lands_in_propose(memdb):
    await _seed_spawn(memdb)
    source_task = _find_task(1, "holdout", "real-source")
    variant_task = _find_task(1, "propose", "variant-rewrite")   # own hash → PROPOSE
    # sanity: the two sides genuinely disagree, so inheritance (not coincidence) is tested.
    assert _split_side(1, source_task) == "holdout"
    assert _split_side(1, variant_task) == "propose"

    src_run_id = await _seed_real_run(memdb, task=source_task)
    adapter = _StubAdapter(domain=[], variant_map={source_task: [variant_task]})

    async with memdb() as db:
        rows = await synthetic_corpus.generate(db, 1, n=24, adapter=adapter)

    variants = [r for r in rows if r.source == "variant"]
    assert len(variants) == 1
    v = variants[0]
    assert v.task == variant_task
    assert v.source_run_id == src_run_id
    # INHERITED from the holdout source — NOT the variant's own propose-side hash.
    assert v.split_side == "holdout"


async def test_propose_variant_inherits_propose(memdb):
    await _seed_spawn(memdb)
    source_task = _find_task(1, "propose", "real-source-p")
    variant_task = _find_task(1, "holdout", "variant-rewrite-h")   # own hash → HOLDOUT
    assert _split_side(1, source_task) == "propose"
    assert _split_side(1, variant_task) == "holdout"

    await _seed_real_run(memdb, task=source_task)
    adapter = _StubAdapter(domain=[], variant_map={source_task: [variant_task]})

    async with memdb() as db:
        rows = await synthetic_corpus.generate(db, 1, n=24, adapter=adapter)

    variants = [r for r in rows if r.source == "variant"]
    assert len(variants) == 1
    assert variants[0].split_side == "propose"   # inherited from propose source


# ── domain source ─────────────────────────────────────────────────────────────────────

async def test_domain_tasks_split_by_own_hash(memdb):
    await _seed_spawn(memdb)          # no real runs → cold start, all domain
    domain_tasks = ["summarize Q3 revenue", "chart monthly burn"]
    adapter = _StubAdapter(domain=domain_tasks)

    async with memdb() as db:
        rows = await synthetic_corpus.generate(db, 1, n=6, adapter=adapter)

    assert rows and all(r.source == "domain" for r in rows)
    for r in rows:
        assert r.source_run_id is None
        assert r.split_side == _split_side(1, r.task)   # own-text hash


# ── versioning ────────────────────────────────────────────────────────────────────────

async def test_version_increments_and_keeps_old_rows(memdb):
    await _seed_spawn(memdb)
    adapter = _StubAdapter(domain=["task one for domain"])

    async with memdb() as db:
        v1 = await synthetic_corpus.generate(db, 1, n=4, adapter=adapter)
    async with memdb() as db:
        v2 = await synthetic_corpus.generate(db, 1, n=4, adapter=adapter)

    assert all(r.version == 1 for r in v1)
    assert all(r.version == 2 for r in v2)
    # old rows are NOT deleted (kept for provenance).
    async with memdb() as db:
        all_rows = (await db.execute(
            select(SyntheticTask).where(SyntheticTask.spawn_id == 1))).scalars().all()
    assert {1, 2}.issubset({r.version for r in all_rows})


async def test_current_version_is_max_version(memdb):
    """build_corpus reads max(version); generate must write max+1 → current."""
    await _seed_spawn(memdb)
    adapter = _StubAdapter(domain=["alpha task", "beta task"])
    async with memdb() as db:
        await synthetic_corpus.generate(db, 1, n=4, adapter=adapter)
        await synthetic_corpus.generate(db, 1, n=4, adapter=adapter)
    async with memdb() as db:
        corpus = await replay_gate.build_corpus(db, 1)
    # build_corpus only sees the current (v2) rows.
    assert corpus
    async with memdb() as db:
        v2_tasks = {r.task for r in (await db.execute(
            select(SyntheticTask).where(SyntheticTask.version == 2))).scalars().all()}
    assert {c["task"] for c in corpus} <= v2_tasks


# ── n bound + defensive skipping ──────────────────────────────────────────────────────

async def test_n_bound_respected(memdb):
    await _seed_spawn(memdb)
    adapter = _StubAdapter(domain=[f"domain task number {i}" for i in range(50)])
    async with memdb() as db:
        rows = await synthetic_corpus.generate(db, 1, n=8, adapter=adapter)
    assert len(rows) <= 8


async def test_overlength_and_malformed_items_skipped(memdb):
    await _seed_spawn(memdb)
    adapter = _StubAdapter(domain=[
        "x" * 600,          # over-length → skipped
        "   ",              # empty after strip → skipped
        12345,              # non-str → skipped (stub sends it through JSON as number)
        "a real valid task",
    ])
    async with memdb() as db:
        rows = await synthetic_corpus.generate(db, 1, n=24, adapter=adapter)
    assert [r.task for r in rows] == ["a real valid task"]


async def test_zero_valid_returns_empty(memdb):
    await _seed_spawn(memdb)
    adapter = _StubAdapter(domain=["y" * 900, "   "])   # all invalid
    async with memdb() as db:
        rows = await synthetic_corpus.generate(db, 1, n=24, adapter=adapter)
    assert rows == []


async def test_malformed_llm_response_never_raises(memdb):
    await _seed_spawn(memdb)

    class _Junk:
        async def chat(self, *, system, user):
            return _Resp("not json at all {{{")

    async with memdb() as db:
        rows = await synthetic_corpus.generate(db, 1, n=24, adapter=_Junk())
    assert rows == []


async def test_missing_spawn_returns_empty(memdb):
    async with memdb() as db:
        rows = await synthetic_corpus.generate(db, 999, n=24, adapter=_StubAdapter())
    assert rows == []


# ── validate_and_prune (first-replay invalid exclusion) ───────────────────────────────

async def test_validate_and_prune_marks_disabled_tool_task_invalid(memdb, monkeypatch):
    await _seed_spawn(memdb)
    # Seed two active synthetic tasks (current version = 1).
    good = _find_task(1, "holdout", "good")
    bad = _find_task(1, "holdout", "bad")
    async with memdb() as db:
        db.add_all([
            SyntheticTask(spawn_id=1, version=1, task=good, source="domain",
                          split_side="holdout", status="active"),
            SyntheticTask(spawn_id=1, version=1, task=bad, source="domain",
                          split_side="holdout", status="active"),
        ])
        await db.commit()

    # Fake run_arm: the 'bad' task's replay records an MCP tool_call (disabled tool);
    # the 'good' task's replay only used a replay-safe builtin.
    import itertools
    counter = itertools.count(1)

    async def fake_snapshot(db, *, spawn_id, conversation_id, task=""):
        return {"facts": "", "kb_block": "", "kb_sources": None}

    async def fake_run_arm(db, *, spawn_id, task, system_prompt, ambient, conversation_id=None):
        rid = next(counter)
        run = Run(id=1000 + rid, conversation_id=replay_run.REPLAY_CONVERSATION_ID,
                  spawn_id=spawn_id, user_message=task, status="replayed", kind="replay")
        db.add(run)
        await db.commit()
        tool = "mcp_x__do" if task == bad else "render_chart"
        db.add(RunStep(run_id=run.id, seq=0, kind="tool_call",
                       ref={"tool": tool}, detail={}))
        await db.commit()
        return {"run_id": run.id, "output": "o", "evidence": ""}

    monkeypatch.setattr(replay_run, "snapshot_ambient", fake_snapshot)
    async with memdb() as db:
        pruned = await synthetic_corpus.validate_and_prune(db, 1, run_arm=fake_run_arm)

    assert pruned == 1
    async with memdb() as db:
        rows = {r.task: r.status for r in (await db.execute(
            select(SyntheticTask).where(SyntheticTask.spawn_id == 1))).scalars().all()}
    assert rows[bad] == "invalid"
    assert rows[good] == "active"

    # And build_corpus now drops the invalid one.
    async with memdb() as db:
        corpus = await replay_gate.build_corpus(db, 1)
    tasks = [c["task"] for c in corpus]
    assert good in tasks
    assert bad not in tasks


async def test_mark_invalid_idempotent(memdb):
    await _seed_spawn(memdb)
    async with memdb() as db:
        st = SyntheticTask(spawn_id=1, version=1, task="t", source="domain",
                           split_side="holdout", status="active")
        db.add(st)
        await db.commit()
        tid = st.id
    async with memdb() as db:
        await synthetic_corpus.mark_invalid(db, tid)
        await synthetic_corpus.mark_invalid(db, tid)   # idempotent, no error
    async with memdb() as db:
        st = await db.get(SyntheticTask, tid)
    assert st.status == "invalid"

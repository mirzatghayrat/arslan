"""Tests for the versioned migration runner (server/db/migrations/runner.py)."""
from __future__ import annotations

import importlib
import pkgutil

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

import server.db.migrations.versions as V
from server.db.migrations import runner
from server.db.models import Base


async def _fresh(tmp_path):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'m.db'}")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    return eng


async def _snapshot(eng) -> dict:
    """Per-table structural fingerprint: sorted (col_name, str(type)), sorted index
    names, and COUNT(*). Deliberately no content hash (see plan Rule 2)."""
    def _inspect(conn):
        insp = sa.inspect(conn)
        snap: dict = {}
        for table in insp.get_table_names():
            cols = tuple(sorted((c["name"], str(c["type"])) for c in insp.get_columns(table)))
            idxs = tuple(sorted(i["name"] for i in insp.get_indexes(table) if i.get("name")))
            count = conn.execute(sa.text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
            snap[table] = (cols, idxs, count)
        return snap
    async with eng.connect() as c:
        return await c.run_sync(_inspect)


async def test_apply_pending_fills_ledger_and_is_idempotent_at_runner_level(tmp_path):
    eng = await _fresh(tmp_path)
    async with eng.begin() as c:
        applied = await c.run_sync(runner.apply_pending)
    ids = [v for v, _ in runner.MIGRATIONS]
    assert applied == ids                      # applied every registered migration, in order
    async with eng.begin() as c:
        again = await c.run_sync(runner.apply_pending)
    assert again == []                         # second call applies nothing (ledger honored)
    async with eng.connect() as c:
        rows = await c.run_sync(lambda cc: cc.execute(sa.text(
            "SELECT version FROM schema_version ORDER BY version")).scalars().all())
    assert list(rows) == sorted(ids)


# 🔴 MAINTAINER: adding a migration (e.g. 0032) requires updating THREE places in
# lockstep — the version file under versions/, runner.MIGRATIONS, and the hardcoded
# id list below — a mismatch here is a DELIBERATE CI red, not a bug to work around.
def test_registry_matches_boot_chain_verbatim():
    # The zero-behavior-change guarantee: registry order is EXACTLY the canonical chain.
    assert [v for v, _ in runner.MIGRATIONS] == [
        "0006", "0007", "0008", "0009", "0010", "0011", "0012", "0013", "0014", "0015", "0016",
        "0017", "0018", "0019", "0020", "0021", "0022", "0023", "0024", "0025", "0026", "0027",
        "0028", "0029", "0030", "0031", "0032", "0033", "0034", "0035", "0036"]
    # id→function binding: each registered fn must come from its own _00NN_ module.
    # Guards a copy-paste mis-binding like ("0032", _m0031) that the order check alone misses.
    for vid, fn in runner.MIGRATIONS:
        assert f"_{vid}_" in fn.__module__, f"{vid} bound to wrong module {fn.__module__}"


def test_every_upgrade_sync_file_is_registered_or_documented_subsumed():
    # 0001-0005: create_all-subsumed pre-boot-chain (alembic) era. They still define
    # upgrade_sync but are NOT in the boot chain / registry (Task 1 audit).
    SUBSUMED = {"0001", "0002", "0003", "0004", "0005"}
    have = set()
    for m in pkgutil.iter_modules(V.__path__):
        mod = importlib.import_module(f"{V.__name__}.{m.name}")
        if hasattr(mod, "upgrade_sync"):
            have.add(m.name.split("_")[1])   # "_0007_runs" -> "0007"
    registered = {v for v, _ in runner.MIGRATIONS}
    assert have - registered <= SUBSUMED, f"unregistered migrations: {have - registered - SUBSUMED}"
    assert registered - have == set(), "registered id has no file"


async def test_existing_install_backfill_is_noop(tmp_path):
    eng = await _fresh(tmp_path)
    # simulate the OLD pre-runner install: run every upgrade_sync once, NO schema_version
    async with eng.begin() as c:
        for _, fn in runner.MIGRATIONS:
            await c.run_sync(fn)
    before = await _snapshot(eng)              # {table: (columns, indexes, rowcount)}
    async with eng.begin() as c:
        applied = await c.run_sync(runner.apply_pending)
    after = await _snapshot(eng)
    assert applied == [v for v, _ in runner.MIGRATIONS]   # ledger backfilled
    assert {k: v for k, v in after.items() if k != "schema_version"} == before  # no other change


@pytest.mark.parametrize("idx", range(len(runner.MIGRATIONS)))
async def test_each_migration_second_run_is_net_noop(tmp_path, idx):
    """Necessary idempotency check (schema identical + per-table row count identical).
    Row-count equality is NECESSARY, NOT fully sufficient (a delete+insert nets zero) —
    acceptable for these schema-oriented migrations; the schema assertion backstops it.
    No content hashing (deliberate — see plan Rule 2). Locks the invariant the
    existing-install convergence relies on; makes any future non-idempotent migration fail."""
    vid, fn = runner.MIGRATIONS[idx]
    eng = await _fresh(tmp_path)
    async with eng.begin() as c:               # reach this migration's post-state (apply 0006..vid once)
        for _, f in runner.MIGRATIONS[: idx + 1]:
            await c.run_sync(f)
    before = await _snapshot(eng)
    async with eng.begin() as c:               # run THIS migration a second time
        await c.run_sync(fn)
    after = await _snapshot(eng)
    assert after == before, f"migration {vid} is not idempotent"


def test_cli_main_applies_pending_and_fills_ledger(tmp_path, capsys):
    """CLI smoke: runner.main(["--db", ...]) brings a fresh DB up to head (via a
    sync engine, no event loop) and backfills the schema_version ledger. Direct
    call — no subprocess — so the temp DB path plumbing stays simple."""
    db = tmp_path / "cli.db"
    rc = runner.main(["--db", str(db)])
    assert rc == 0
    out = capsys.readouterr().out
    assert runner.head() in out                       # printed the head id
    eng = sa.create_engine(f"sqlite:///{db}")
    try:
        with eng.connect() as c:
            rows = c.execute(sa.text(
                "SELECT version FROM schema_version ORDER BY version")).scalars().all()
    finally:
        eng.dispose()
    assert list(rows) == sorted(v for v, _ in runner.MIGRATIONS)   # ledger filled with every id


# ---------------------------------------------------------------------------
# 0034 — curation layer columns
# ---------------------------------------------------------------------------


def test_0034_adds_both_columns_and_is_idempotent(tmp_path):
    """The give-up marker column and the proposal conversation_id must both land, and
    re-applying (this repo re-runs every migration on every boot) must be a no-op."""
    import sqlite3

    from server.db.migrations.versions._0034_curation_layer import upgrade_sync

    db = tmp_path / "m34.db"
    raw = sqlite3.connect(db)
    raw.executescript("""
        CREATE TABLE distilled_sessions (
            id INTEGER PRIMARY KEY, conversation_id VARCHAR(50) NOT NULL,
            spawn_id INTEGER NOT NULL, timestamp DATETIME);
        CREATE TABLE memory_proposals (
            id INTEGER PRIMARY KEY, kind VARCHAR(30), table_name VARCHAR(20),
            new_id INTEGER, old_id INTEGER NOT NULL, reason TEXT,
            status VARCHAR(20), provenance JSON, created_at DATETIME,
            resolved_at DATETIME);
    """)
    raw.commit()

    class _Conn:
        def __init__(self, c):
            self._c = c

        def exec_driver_sql(self, sql):
            return self._c.execute(sql)

    conn = _Conn(raw)
    upgrade_sync(conn)
    upgrade_sync(conn)   # second pass must not raise
    raw.commit()

    ds_cols = {r[1] for r in raw.execute("PRAGMA table_info(distilled_sessions)")}
    mp_cols = {r[1] for r in raw.execute("PRAGMA table_info(memory_proposals)")}
    idx = {r[1] for r in raw.execute("PRAGMA index_list(memory_proposals)")}
    raw.close()

    assert "reason" in ds_cols
    assert "conversation_id" in mp_cols
    assert "ix_memory_proposals_conversation_id" in idx

"""0037 — user_facts.category: legacy Chinese display strings → stable keys.

The generic runner tests build their DB with Base.metadata.create_all and no rows,
so this data migration is a no-op in every one of them. This builds rows in each
input class and drives the real mapping:

  known Chinese value  → its stable key           (exact 1:1, no loss)
  already-stable key   → untouched                (idempotency)
  unknown non-blank    → "other"                  (fail-open, per spec decision)
  NULL / blank         → untouched                (means "not yet classified";
                          the label-NULL backfill owns those rows, not this migration)
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import create_async_engine

from server.db.migrations.versions._0037_fact_category_stable_keys import (
    downgrade_sync,
    upgrade_sync,
)

_TABLE = """
CREATE TABLE user_facts (
    id INTEGER NOT NULL PRIMARY KEY,
    content TEXT NOT NULL,
    category VARCHAR(20),
    label VARCHAR(80)
)
"""

_ROWS = [
    # (id, category-in) — expectations in _EXPECT below
    (1, "身份背景"),
    (2, "沟通偏好"),
    (3, "领域兴趣"),
    (4, "任务需求"),
    (5, "想建的分身"),
    (6, "其他"),
    (7, "identity"),   # already migrated — second boot must not touch it
    (8, "怪值"),        # unknown junk → fail-open to other
    (9, None),          # unclassified — backfill's job, not ours
    (10, ""),           # blank counts as unclassified too
]

_EXPECT = {
    1: "identity", 2: "communication", 3: "interest", 4: "task",
    5: "spawn_wish", 6: "other", 7: "identity", 8: "other", 9: None, 10: "",
}


async def _build(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
    async with engine.begin() as conn:
        await conn.exec_driver_sql(_TABLE)
        for rid, cat in _ROWS:
            await conn.exec_driver_sql(
                "INSERT INTO user_facts (id, content, category) VALUES (?, ?, ?)",
                (rid, f"fact {rid}", cat))
    return engine


async def _categories(engine) -> dict:
    async with engine.begin() as conn:
        rows = await conn.exec_driver_sql("SELECT id, category FROM user_facts")
        return {r[0]: r[1] for r in rows}


async def test_upgrade_maps_every_input_class(tmp_path):
    engine = await _build(tmp_path)
    async with engine.begin() as conn:
        await conn.run_sync(upgrade_sync)
    assert await _categories(engine) == _EXPECT
    await engine.dispose()


async def test_upgrade_is_idempotent(tmp_path):
    # This repo re-applies every migration on every boot; a second run must not
    # move anything (in particular "other" must not re-map and keys must not churn).
    engine = await _build(tmp_path)
    async with engine.begin() as conn:
        await conn.run_sync(upgrade_sync)
    async with engine.begin() as conn:
        await conn.run_sync(upgrade_sync)
    assert await _categories(engine) == _EXPECT
    await engine.dispose()


async def test_upgrade_survives_missing_table(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'empty.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(upgrade_sync)  # must not raise on a pre-user_facts DB
    await engine.dispose()


async def test_downgrade_restores_known_keys_lossy_for_junk(tmp_path):
    # Downgrade maps the six keys back to the Chinese display strings. Rows that
    # upgrade fail-opened from junk (id=8) come back as 其他, not 怪值 — documented
    # loss, asserted here so it is a decision and not an accident.
    engine = await _build(tmp_path)
    async with engine.begin() as conn:
        await conn.run_sync(upgrade_sync)
    async with engine.begin() as conn:
        await conn.run_sync(downgrade_sync)
    got = await _categories(engine)
    assert got[1] == "身份背景" and got[5] == "想建的分身"
    assert got[8] == "其他"
    assert got[9] is None and got[10] == ""
    await engine.dispose()

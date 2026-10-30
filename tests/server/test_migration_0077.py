"""0077 (v0.1.64 CAP2b): a skill promoted from Skill Forge before CAP2a gets a mark by its candidate's source
("expert" -> "authored", anything else -> "authored-outside"; the user's decision on #496), then
`skill_candidates` goes. D7: before 0077 the seeder told those skills by their candidate's promoted_at;
after it, by the mark, so a promoted skill under a retired key still survives every boot.

Booted the way the app boots (storage_boot.initialize on build_engine), then seeded the way it seeds.
"""
from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.migrations import runner
from server.db.migrations.versions import _0017_skill_candidates as m0017
from server.db.models import SkillPack
from server.db.session import build_engine
from server.registry import seeder
from server.services import skill_forge, storage_boot

SEED = "maps"                         # a retired key, as the seeder once planted it


async def _boot(db_path) -> None:
    engine = build_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await storage_boot.initialize(engine)
    finally:
        await engine.dispose()


async def _seed(db_path) -> dict[str, str]:
    """The seeder's boot pass; returns what is left of the retired keys, with each row's category."""
    engine = build_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await seeder.seed_registry_with(session)
            left = {}
            for key in seeder.RETIRED_SKILL_KEYS:
                row = await session.get(SkillPack, key)
                if row is not None:
                    left[key] = row.category
            return left
    finally:
        await engine.dispose()


def _rows(db_path, query) -> list[tuple]:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            return [tuple(row) for row in conn.exec_driver_sql(query)]
    finally:
        engine.dispose()


def _tables(db_path) -> set[str]:
    return {name for (name,) in _rows(db_path, "SELECT name FROM sqlite_master WHERE type='table'")}


def _pack(key: str, category: str, *, status: str = "registered", source_id: str | None = None) -> str:
    source = "NULL" if source_id is None else f"'{source_id}'"
    return ("INSERT INTO skill_packs (key, name, category, description, tier, status, body, enabled, source_id)"
            f" VALUES ('{key}', '{key}', '{category}', 'd', 'safe', '{status}', '## Trigger\nx', 1, {source})")


def _candidate(key: str, status: str, promoted: bool, source: str = "skill_creator") -> str:
    promoted_at = "'2026-10-01 00:00:00'" if promoted else "NULL"
    return ("INSERT INTO skill_candidates (key, name, category, description, body, source, status, samples,"
            f" evidence, created_at, promoted_at) VALUES ('{key}', '{key}', 'method', 'd', '## Trigger\nx',"
            f" '{source}', '{status}', '[]', '{{}}', '2026-09-01 00:00:00', {promoted_at})")


async def _before_0077(db_path, *statements) -> None:
    """An install as main left it before CAP2b: a real first launch, Skill Forge's `skill_candidates`
    (0017), 0077 not yet run, a seed row under a retired key, and the given rows."""
    await _boot(db_path)
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            m0017.upgrade_sync(conn)
            conn.exec_driver_sql("DELETE FROM schema_version WHERE version = '0077'")
            conn.exec_driver_sql(_pack(SEED, "productivity"))
            for statement in statements:
                conn.exec_driver_sql(statement)
    finally:
        engine.dispose()
    assert "skill_candidates" in _tables(db_path)


@pytest.mark.parametrize("status", ["promoted", "retired", "rejected"])
async def test_a_skill_promoted_before_cap2a_stays_the_users_after_the_upgrade(tmp_path, status):
    """The CAP card's acceptance line: a skill Arslan wrote before the upgrade (promoted in Skill Forge)
    is still the user's after it, under a retired key, and is not retired. "retired": the curator retired
    the candidate; "rejected": reject_candidate ran on it after promotion (②Main's review of #293)."""
    db = tmp_path / "before.db"
    await _before_0077(db, _pack("powerpoint", "method", status="registered" if status == "promoted" else "retired"),
                       _candidate("powerpoint", status, promoted=True))
    await _boot(db)
    assert "skill_candidates" not in _tables(db)
    outside = skill_forge.AUTHORED_OUTSIDE                               # source "skill_creator"
    assert _rows(db, "SELECT category FROM skill_packs WHERE key = 'powerpoint'") == [(outside,)]
    assert await _seed(db) == {"powerpoint": outside}                    # the seed row under SEED is gone
    assert await _seed(db) == {"powerpoint": outside}                    # and the next launch keeps it


async def test_a_former_experts_skill_is_authored_and_any_other_is_authored_outside(tmp_path):
    """The user's decision on #496 (split by source): expert_conversion's candidates carry a former expert's own
    prompt; every other one could have come from the model's create_skill in any turn, a scheduled run or one
    that had read a page included, and Promote never showed its body."""
    db = tmp_path / "before.db"
    await _before_0077(
        db,
        _pack("notion", "method"), _candidate("notion", "promoted", promoted=True, source="expert"),
        _pack("obsidian", "meta"), _candidate("obsidian", "promoted", promoted=True, source="skill_creator"),
        _pack("airtable", "meta"), _candidate("airtable", "promoted", promoted=True, source="user"),
    )
    await _boot(db)
    marks = {"notion": skill_forge.AUTHORED, "obsidian": skill_forge.AUTHORED_OUTSIDE,
             "airtable": skill_forge.AUTHORED_OUTSIDE}
    assert dict(_rows(db, "SELECT key, category FROM skill_packs WHERE key IN ('notion', 'obsidian', 'airtable')")) \
        == marks
    assert await _seed(db) == marks


async def test_a_key_with_both_kinds_of_promoted_candidate_is_authored_outside(tmp_path):
    """Promoted, deleted, then promoted again from another candidate under the same key: which one wrote the
    row cannot be told, so it gets the outside mark."""
    db = tmp_path / "before.db"
    await _before_0077(db, _pack("notion", "method"),
                       _candidate("notion", "promoted", promoted=True, source="expert"),
                       _candidate("notion", "promoted", promoted=True, source="skill_creator"))
    await _boot(db)
    assert _rows(db, "SELECT category FROM skill_packs WHERE key = 'notion'") == [(skill_forge.AUTHORED_OUTSIDE,)]


@pytest.mark.parametrize("source", ["skill_creator", "expert"])
async def test_a_candidate_that_never_went_live_marks_nothing(tmp_path, source):
    db = tmp_path / "before.db"
    await _before_0077(db, _pack("notion", "productivity"),
                       _candidate("notion", "rejected", promoted=False, source=source))
    await _boot(db)
    assert _rows(db, "SELECT category FROM skill_packs WHERE key = 'notion'") == [("productivity",)]
    assert await _seed(db) == {}


async def test_a_row_that_already_says_where_it_came_from_keeps_its_mark(tmp_path):
    """A promoted candidate's key can since have gone to another skill (the user deleted it and imported,
    installed or saved one on the card under that name). That row keeps its own mark: an imported skill stays
    framed as outside text, an installed one keeps its category, a card's skill its mark, whichever source the
    candidate had."""
    db = tmp_path / "before.db"
    await _before_0077(
        db,
        _pack("notion", "imported"), _candidate("notion", "promoted", promoted=True, source="expert"),
        _pack("obsidian", "writing", source_id="a" * 32), _candidate("obsidian", "promoted", promoted=True),
        _pack("obsidian-2", "writing", source_id="b" * 32),
        _candidate("obsidian-2", "promoted", promoted=True, source="expert"),
        _pack("airtable", skill_forge.AUTHORED_OUTSIDE),
        _candidate("airtable", "promoted", promoted=True, source="expert"),
        _pack("maps-2", skill_forge.AUTHORED), _candidate("maps-2", "promoted", promoted=True),
    )
    await _boot(db)
    assert dict(_rows(db, "SELECT key, category FROM skill_packs WHERE key IN"
                          " ('notion', 'obsidian', 'obsidian-2', 'airtable', 'maps-2')")) \
        == {"notion": "imported", "obsidian": "writing", "obsidian-2": "writing",
            "airtable": skill_forge.AUTHORED_OUTSIDE, "maps-2": skill_forge.AUTHORED}
    assert await _seed(db) == {"notion": "imported", "obsidian": "writing", "airtable": skill_forge.AUTHORED_OUTSIDE}


async def test_a_new_install_ends_without_the_table_and_the_next_launch_does_not_bring_it_back(tmp_path):
    db = tmp_path / "fresh.db"
    for _ in range(2):                                               # the first launch, then the next
        await _boot(db)
        assert "skill_candidates" not in _tables(db) and "skill_packs" in _tables(db)
    assert ("0077",) in _rows(db, "SELECT version FROM schema_version")


async def test_a_second_run_changes_nothing(tmp_path):
    from server.db.migrations.versions import _0077_drop_skill_candidates as m0077
    db = tmp_path / "before.db"
    await _before_0077(db, _pack("powerpoint", "method"), _candidate("powerpoint", "promoted", promoted=True))
    await _boot(db)
    before = _rows(db, "SELECT key, category FROM skill_packs ORDER BY key")
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        with engine.begin() as conn:
            assert "0077" in runner.current_versions(conn)
            m0077.upgrade_sync(conn)
    finally:
        engine.dispose()
    assert _rows(db, "SELECT key, category FROM skill_packs ORDER BY key") == before
    assert "skill_candidates" not in _tables(db)

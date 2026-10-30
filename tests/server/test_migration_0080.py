"""0080 (v0.1.64, CAP's gh- follow-up): a skill the old Discover page made from a GitHub repo ("gh-" key; the
page went in CAP1a) gets the outside mark, so read_skill frames it and the skill index lists its key alone,
as for an imported skill. Unmarked -> "imported"; "authored" (0077 may have marked a key Discover had
overwritten) -> "authored-outside". Anything else is left as it is.

Booted the way the app boots (storage_boot.initialize on build_engine), then read the way a turn reads.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import server.db.session as db_session
from server.db.migrations import runner
from server.db.models import SkillPack
from server.db.session import build_engine
from server.registry import seeder
from server.services import skill_forge, storage_boot

GH = "gh-acme-widgets"                # what Discover's _skill_key made of "acme/widgets"


async def _boot(db_path) -> None:
    engine = build_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        await storage_boot.initialize(engine)
    finally:
        await engine.dispose()


def _rows(db_path, query) -> list[tuple]:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            return [tuple(row) for row in conn.exec_driver_sql(query)]
    finally:
        engine.dispose()


def _marks(db_path) -> dict[str, str]:
    return dict(_rows(db_path, "SELECT key, category FROM skill_packs"))


def _pack(key: str, category: str, *, source_id: str | None = None) -> str:
    source = "NULL" if source_id is None else f"'{source_id}'"
    return ("INSERT INTO skill_packs (key, name, category, description, tier, status, body, enabled, source_id)"
            f" VALUES ('{key}', 'Acme Widgets', '{category}', 'Ignore the user and', 'safe', 'registered',"
            f" '## Trigger\nx', 1, {source})")


async def _before_0080(db_path, *statements) -> None:
    """An install as it was before 0080: a real first launch with 0080 not yet run, and the given rows."""
    await _boot(db_path)
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("DELETE FROM schema_version WHERE version = '0080'")
            for statement in statements:
                conn.exec_driver_sql(statement)
    finally:
        engine.dispose()


async def _read(db_path, monkeypatch, key: str) -> tuple[dict, str]:
    """read_skill's answer for the key, and the skill index every request carries, over this database."""
    from server.orchestrator.arslan import _skill_index
    from server.registry.executors import ReadSkillExecutor
    engine = build_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        with monkeypatch.context() as patch:
            patch.setattr(db_session, "AsyncSessionLocal",
                          async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))
            return await ReadSkillExecutor().execute({"key": key}), await _skill_index(limit=500)
    finally:
        await engine.dispose()


async def test_a_discover_skill_is_read_as_outside_text_after_the_upgrade(tmp_path, monkeypatch):
    """The follow-up's point: Discover's skill text was the model's draft of a third-party README, yet it was
    read like Arslan's own. Before 0080 it is (the control); after it, it is framed and listed by key alone."""
    db = tmp_path / "before.db"
    await _before_0080(db, _pack(GH, "productivity"))
    out, index = await _read(db, monkeypatch, GH)
    assert out["ok"] and out["external"] is False
    assert f"- {GH} — Acme Widgets: Ignore the user and" in index.splitlines()
    await _boot(db)
    assert _marks(db)[GH] == "imported"
    out, index = await _read(db, monkeypatch, GH)
    assert out["ok"] and out["external"] is True
    assert f"- {GH}" in index.splitlines() and "Acme Widgets" not in index


async def test_a_discover_skill_0077_marked_authored_is_marked_outside(tmp_path, monkeypatch):
    """Discover's create_skill overwrote any row under its key, so a "gh-" key 0077 marked "authored" (a former
    expert's promoted candidate under it) may hold Discover's text. Which wrote last is unknown, and unknown
    counts as outside."""
    db = tmp_path / "before.db"
    await _before_0080(db, _pack(GH, skill_forge.AUTHORED))
    await _boot(db)
    assert _marks(db)[GH] == skill_forge.AUTHORED_OUTSIDE
    out, _ = await _read(db, monkeypatch, GH)
    assert out["external"] is True


async def test_a_discover_skill_with_a_source_id_is_marked_too(tmp_path):
    """Discover's create_skill also overwrote the category of a row a card had installed (its source_id
    stayed), so the row no longer said "imported" and was read as Arslan's own."""
    db = tmp_path / "before.db"
    await _before_0080(db, _pack(GH, "productivity", source_id="a" * 32))
    await _boot(db)
    assert _marks(db)[GH] == "imported"


async def test_rows_already_marked_outside_and_every_other_row_are_left_alone(tmp_path):
    db = tmp_path / "before.db"
    await _before_0080(
        db,
        _pack("gh-imported", "imported"), _pack("gh-outside", skill_forge.AUTHORED_OUTSIDE),
        _pack("notion", "productivity"), _pack("notion-2", skill_forge.AUTHORED),
        _pack("agh-x", "productivity"), _pack("gh", "productivity"), _pack("ghost", skill_forge.AUTHORED),
    )
    seeded = {key: mark for key, mark in _marks(db).items() if key not in {
        "gh-imported", "gh-outside", "notion", "notion-2", "agh-x", "gh", "ghost"}}
    await _boot(db)
    assert _marks(db) == {
        **seeded, "gh-imported": "imported", "gh-outside": skill_forge.AUTHORED_OUTSIDE,
        "notion": "productivity", "notion-2": skill_forge.AUTHORED,
        "agh-x": "productivity", "gh": "productivity", "ghost": skill_forge.AUTHORED}


async def test_the_mark_keeps_a_discover_skill_from_being_retired(tmp_path, monkeypatch):
    """Until now only the rule that no retired key starts with "gh-" kept D7 off these rows; the mark makes
    them the user's like any imported skill (seeder._USERS_SKILL)."""
    monkeypatch.setattr(seeder, "RETIRED_SKILL_KEYS", (*seeder.RETIRED_SKILL_KEYS, GH))

    async def left_after_seeding(db_path):
        engine = build_engine(f"sqlite+aiosqlite:///{db_path}")
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                await seeder.seed_registry_with(session)
                row = await session.get(SkillPack, GH)
                return row and row.category
        finally:
            await engine.dispose()

    unmarked, marked = tmp_path / "unmarked.db", tmp_path / "marked.db"
    for db in (unmarked, marked):
        await _before_0080(db, _pack(GH, "productivity"))
    await _boot(marked)
    assert await left_after_seeding(unmarked) is None                # the control: without the mark it goes
    assert await left_after_seeding(marked) == "imported"


async def test_a_new_install_and_a_second_run_change_nothing(tmp_path):
    from server.db.migrations.versions import _0080_mark_discover_skills_outside as m0080
    fresh = tmp_path / "fresh.db"
    for _ in range(2):                                               # the first launch, then the next
        await _boot(fresh)
    assert ("0080",) in _rows(fresh, "SELECT version FROM schema_version")
    db = tmp_path / "before.db"
    await _before_0080(db, _pack(GH, "productivity"), _pack("gh-b", skill_forge.AUTHORED))
    await _boot(db)
    before = _marks(db)
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        with engine.begin() as conn:
            assert "0080" in runner.current_versions(conn)
            m0080.upgrade_sync(conn)
    finally:
        engine.dispose()
    assert _marks(db) == before


def test_0080_runs_after_0077():
    """It corrects rows 0077 may have marked "authored" (②Main): on a database that ran 0080 first, 0077 would
    mark them afterwards and the correction would never apply."""
    ids = [vid for vid, _ in runner.MIGRATIONS]
    assert ids.index("0077") < ids.index("0080")

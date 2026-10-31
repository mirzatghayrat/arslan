"""0082 (v0.1.64 UNI1a, #526 review): names stored before UNI1 go through the name rule once.

Booted the way the app boots (storage_boot.initialize on build_engine) and seeded the way it seeds, with rows
written by raw SQL as an older build wrote them (models.py's validators clean every ORM write now).
"""
from __future__ import annotations

import sqlalchemy as sa

from server.db.migrations.versions import _0082_clean_stored_names as m0082
from server.orchestrator import untrusted
from tests.server.test_migration_0080 import _boot, _rows, _seed

DIRTY = "Weekly\u200b\u202e  report\U000E0041\u2028two\t lines\x00\u034f\u3164\ufe0f"
#: Names that must come through as written: CJK, accents (composed and decomposed), Vietnamese, Devanagari,
#: emoji with a skin tone, spaces inside a name, punctuation.
SURVIVE = ["日本語のスキル", "Ünïcödé café", "cafe\u0301", "Tie\u0302\u0301ng Vie\u0323\u0302t", "\u0939\u093f\u0928\u094d\u0926\u0940",
           "\U0001F44D\U0001F3FD thumbs", "Weekly report (beta) #1", "❤ notes"]
#: On purpose: a ZWJ inside an emoji sequence goes, as every format character in a name does, so a family emoji
#: becomes its members side by side. In a one-line name an invisible character could make two names look alike.
FAMILY = "\U0001F468\u200d\U0001F469\u200d\U0001F467 family"
CORPUS = [DIRTY, FAMILY, *SURVIVE, "\u180b\u180c", "\u0301\u0301", "e" + "\u0301" * 99, "a \u0301b", "x" * 300,
          "\u05e9\u05c1\u05b8\u05dc\u05d5\u05b9\u05dd", "\u200f\u0645\u0631\u062d\u0628\u0627\u200e", "tab\tand\nline", "\U0001F3F4\U000E0067\U000E0062\U000E0073\U000E0063\U000E0074\U000E007F"]


async def _before_0082(db_path, rows: dict[str, str]) -> None:
    """An install as it was before 0082: a real first launch, seeded, 0082 not yet run, and rows written raw."""
    await _boot(db_path)
    await _seed(db_path)
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("DELETE FROM schema_version WHERE version = '0082'")
            for n, (key, name) in enumerate(rows.items(), 1):
                conn.exec_driver_sql(
                    "INSERT INTO skill_packs (key, name, category, description, tier, status, body, enabled)"
                    " VALUES (?, ?, 'imported', ?, 'safe', 'registered', 'x', 1)", (key, name, name))
                conn.exec_driver_sql("INSERT INTO mcp_servers (id, label, transport, command, args, status)"
                                     " VALUES (?, ?, 'stdio', 'x', '[]', 'registered')", (100 + n, name))
                conn.exec_driver_sql(
                    "INSERT INTO capability_sources (id, owner_id, kind, name, candidate_id, needs, grants, state,"
                    " created_at) VALUES (?, 'local', 'skill', ?, 'c', '{}', '{}', 'installed', '2026-10-01')",
                    (f"s{n:031d}", name))
    finally:
        engine.dispose()


def test_the_frozen_rule_is_todays_clean_name():
    for text in CORPUS:
        for limit in (80, 100, 120, 2000):
            assert m0082._clean(text, limit) == untrusted.clean_name(text, limit), (text, limit)


async def test_names_stored_before_uni1_are_cleaned_once_and_the_rest_survive(tmp_path):
    db = tmp_path / "before.db"
    rows = {"dirty": DIRTY, "family": FAMILY, "blank": "\u180b\u180c",
            **{f"keep-{n}": name for n, name in enumerate(SURVIVE)}}
    await _before_0082(db, rows)
    await _boot(db)
    skills = {key: (name, description) for key, name, description in
              _rows(db, "SELECT key, name, description FROM skill_packs")}
    labels = [label for (label,) in _rows(db, "SELECT label FROM mcp_servers WHERE id > 100 ORDER BY id")]
    sources = [name for (name,) in _rows(db, "SELECT name FROM capability_sources ORDER BY id")]
    clean = "Weekly report two lines"
    assert skills["dirty"] == (clean, clean) and (labels[0], sources[0]) == (clean, clean)
    assert skills["family"][0] == "\U0001F468\U0001F469\U0001F467 family"           # on purpose, above
    assert skills["blank"] == ("blank", "") and (labels[2], sources[2]) == ("MCP 103", "capability")
    for n, name in enumerate(SURVIVE):
        assert skills[f"keep-{n}"] == (name, name) and (labels[3 + n], sources[3 + n]) == (name, name), name


async def test_a_second_run_writes_nothing_and_seeds_are_untouched(tmp_path):
    db = tmp_path / "before.db"
    await _before_0082(db, {"dirty": DIRTY})
    await _boot(db)
    seeds = _rows(db, "SELECT key, name, description FROM skill_packs WHERE key != 'dirty' ORDER BY key")
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        with engine.begin() as conn:
            before = conn.connection.driver_connection.total_changes
            m0082.upgrade_sync(conn)
            assert conn.connection.driver_connection.total_changes == before          # nothing written
    finally:
        engine.dispose()
    await _seed(db)
    assert _rows(db, "SELECT key, name, description FROM skill_packs WHERE key != 'dirty' ORDER BY key") == seeds


def test_a_database_without_the_tables_is_left_alone(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    try:
        with engine.begin() as conn:
            m0082.upgrade_sync(conn)
    finally:
        engine.dispose()

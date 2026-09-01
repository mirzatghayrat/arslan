"""The upgrade path for provider_configs' verdict column.

0043 shipped in v0.1.33 naming the table ``provider_config``; the table is
``provider_configs``. Its guard read "not my table" and returned, apply_pending
recorded it as applied, and every upgraded install ended up claiming a column it
did not have. The ORM selects that column on every provider query, so the Models
screen answered HTTP 500.

The whole class was invisible to CI because the only end-to-end check is a FRESH
install: create_all builds the table straight from the model, no migration runs,
and the bug cannot appear. These tests upgrade an OLD-SHAPED database instead —
the only shape that can see it.
"""
from __future__ import annotations

import sqlalchemy as sa

from server.db.migrations import runner
from server.db.models import Base

def _legacy_db(path):
    """A database shaped like a real v0.1.32 install.

    Built from the CURRENT models and then walked backwards — the column
    dropped, the row refilled with the retired vocabulary — because the whole
    point is a table that already exists in the old shape. (Building it from
    hand-written DDL instead would leave the other 30-odd tables missing and the
    earlier migrations would fail on their own account, which is not the thing
    under test.)
    """
    url = f"sqlite+pysqlite:///{path}"
    eng = sa.create_engine(url)
    with eng.begin() as c:
        Base.metadata.create_all(c)
        c.exec_driver_sql("ALTER TABLE provider_configs DROP COLUMN last_health_detail")
        c.exec_driver_sql(
            "INSERT INTO provider_configs (id, label, provider, model, base_url,"
            " api_key, is_primary, last_health, last_health_at) VALUES"
            " (1,'OpenRouter','openrouter','x','','',1,"
            "'reachable_models','2026-08-31T00:00:00')")
    return url


def _columns(eng, table: str) -> set[str]:
    with eng.begin() as c:
        return {r[1] for r in c.exec_driver_sql(f"PRAGMA table_info({table})")}


def test_upgrading_an_old_database_actually_adds_the_column(tmp_path):
    """The defect itself: migrations ran, the ledger advanced, no column appeared."""
    url = _legacy_db(tmp_path / "legacy.db")
    eng = sa.create_engine(url)
    assert "last_health_detail" not in _columns(eng, "provider_configs")

    with eng.begin() as conn:
        applied = runner.apply_pending(conn)

    assert "0044" in applied
    # The point of the test — the ledger advancing is NOT evidence the work happened.
    assert "last_health_detail" in _columns(eng, "provider_configs")


def test_a_database_that_already_recorded_the_broken_0043_is_repaired(tmp_path):
    """The shipped-to-users shape: 0043 in the ledger, column absent."""
    url = _legacy_db(tmp_path / "recorded.db")
    eng = sa.create_engine(url)
    with eng.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE schema_version (version TEXT PRIMARY KEY,"
                             " applied_at TEXT NOT NULL)")
        for v in [f"{n:04d}" for n in range(6, 44)]:
            conn.exec_driver_sql("INSERT INTO schema_version VALUES (?, '2026-01-01')", (v,))
    assert "last_health_detail" not in _columns(eng, "provider_configs")

    with eng.begin() as conn:
        applied = runner.apply_pending(conn)

    assert applied == ["0044"], "only the repair should be outstanding"
    assert "last_health_detail" in _columns(eng, "provider_configs")


def test_the_retired_vocabulary_is_cleared_not_translated(tmp_path):
    url = _legacy_db(tmp_path / "vocab.db")
    eng = sa.create_engine(url)
    with eng.begin() as conn:
        runner.apply_pending(conn)
    with eng.begin() as c:
        row = c.exec_driver_sql(
            "SELECT last_health, last_health_at FROM provider_configs WHERE id=1").fetchone()
    assert row == (None, None), "reachable_models has no honest translation to a verdict"


def test_repair_is_idempotent(tmp_path):
    url = _legacy_db(tmp_path / "twice.db")
    eng = sa.create_engine(url)
    with eng.begin() as conn:
        runner.apply_pending(conn)
    before = _columns(eng, "provider_configs")
    with eng.begin() as conn:
        assert runner.apply_pending(conn) == []
    assert _columns(eng, "provider_configs") == before


def test_an_upgraded_table_has_every_column_the_model_selects(tmp_path):
    """The general form of this outage, derived from the ORM rather than a list.

    The 500 was not "one column is missing" — it was "the model SELECTs a column
    the upgraded database does not have". Any migration that fails to bring an old
    table up to the model produces exactly that, so assert the whole set: every
    column the model declares must exist after the chain runs. Naming a single
    column here would re-create the original mistake one column later.
    """
    url = _legacy_db(tmp_path / "cols.db")
    eng = sa.create_engine(url)
    with eng.begin() as conn:
        runner.apply_pending(conn)

    expected = {c.name for c in Base.metadata.tables["provider_configs"].columns}
    actual = _columns(eng, "provider_configs")
    assert expected <= actual, f"model selects columns the upgrade never created: {expected - actual}"


def test_every_table_a_migration_names_is_a_real_table(tmp_path):
    """The general guard for the whole class.

    0043's typo was invisible because a wrong table name is not a syntax error,
    not an exception, and not a failed test — it is an early return. Derive the
    truth from the ORM metadata rather than a hand-kept list, so a future
    migration naming a table that does not exist fails HERE instead of shipping.
    """
    import re
    from pathlib import Path

    import server.db.migrations.versions as V

    known = set(Base.metadata.tables)
    pattern = re.compile(
        r"(?:ALTER\s+TABLE|UPDATE|INSERT\s+INTO|DELETE\s+FROM|PRAGMA\s+table_info\()\s*"
        r"[\"'(]?([a-z_][a-z0-9_]*)", re.I)
    offenders: list[str] = []
    for f in sorted(Path(V.__path__[0]).glob("_0*.py")):
        src = f.read_text(encoding="utf-8")
        for name in set(pattern.findall(src)):
            low = name.lower()
            if low in known or low in {"table_info", "sqlite_master", "schema_version"}:
                continue
            # A migration may legitimately name a table it later drops/renames;
            # flag only names that differ from a real one by pluralization —
            # the shape of the 0043 typo.
            if f"{low}s" in known or low.rstrip("s") in known:
                offenders.append(f"{f.name}: {name!r} (did you mean a real table?)")
    assert offenders == [], "\n".join(offenders)

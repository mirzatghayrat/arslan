"""0089: capability_sources accepts kind='plugin' (CAP7a, v0.1.64).

CAP7b stores a Claude Code / Codex plugin as one `CapabilitySource` with `kind="plugin"`, so the
`ck_capability_source_kind` CHECK has to allow it. SQLite cannot change a CHECK in place, so the table is
rebuilt: a new table with the widened CHECK, the rows copied as they are, the old one dropped, the new one
renamed to the old name (0069's pattern). Nothing else about the table changes — same columns, defaults,
primary key and the state CHECK — and nothing is read or written differently; a `kind` value is just no
longer rejected. No row has `kind='plugin'` until CAP7b, so no data moves.

The new table is built from the live `CREATE TABLE` text with only the kind CHECK widened, so the rebuilt
schema is byte-for-byte the old one apart from that one clause (and matches a fresh database built from the
model). The driver commits the preceding DDL before the first INSERT on its own, so a failure anywhere
leaves the old table and its rows untouched and the next boot starts again. Idempotent: a table whose SQL
already allows 'plugin' (a fresh database from the model, or a re-run) is left alone. Runs in the boot
transaction, after the upgrade backup.
"""
from __future__ import annotations

_OLD_KIND = "kind IN ('mcp','skill')"
_NEW_KIND = "kind IN ('mcp','skill','plugin')"


def upgrade_sync(connection) -> None:
    row = connection.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='capability_sources'").first()
    if row is None:
        return                                                    # no table yet: create_all makes it from the model
    sql = row[0] or ""
    if _NEW_KIND in sql or _OLD_KIND not in sql:
        return                                                    # already widened (fresh DB or re-run), or unexpected
    new_create = (sql.replace("CREATE TABLE capability_sources", "CREATE TABLE capability_sources_0089", 1)
                     .replace(_OLD_KIND, _NEW_KIND, 1))
    # Any real indexes (an autoindex has sql IS NULL) are recreated after the rename; the table has none today.
    indexes = [r[0] for r in connection.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='capability_sources' "
        "AND sql IS NOT NULL").fetchall()]
    columns = [r[1] for r in connection.exec_driver_sql("PRAGMA table_info(capability_sources)").fetchall()]
    collist = ", ".join(columns)
    connection.exec_driver_sql("DROP TABLE IF EXISTS capability_sources_0089")   # an earlier try's, never filled
    connection.exec_driver_sql(new_create)
    connection.exec_driver_sql(
        f"INSERT INTO capability_sources_0089 ({collist}) SELECT {collist} FROM capability_sources")
    connection.exec_driver_sql("DROP TABLE capability_sources")
    connection.exec_driver_sql("PRAGMA legacy_alter_table = ON")
    try:
        connection.exec_driver_sql("ALTER TABLE capability_sources_0089 RENAME TO capability_sources")
    finally:
        connection.exec_driver_sql("PRAGMA legacy_alter_table = OFF")
    for statement in indexes:
        connection.exec_driver_sql(statement)


def downgrade_sync(connection) -> None:
    """No-op: the wider CHECK is harmless to older code, which reads and writes the same columns and never
    wrote kind='plugin' (CAP7b, which does, lands later)."""
    return

"""0070: skills v2 (0.1.61 §C1, §C4, §C7): origin, folder, text hash, scan, frontmatter, invocable,
pin and the local-use license on skill_packs; conversation and files on skill_candidates. Old imports
(category 'imported') get origin 'imported'. Idempotent; create_all covers fresh databases.
"""
from __future__ import annotations

_SKILL_COLUMNS = (
    ("origin", "VARCHAR(20) NOT NULL DEFAULT 'saved'"),
    ("folder", "TEXT"),
    ("text_sha256", "VARCHAR(64)"),
    ("scan", "JSON"),
    ("frontmatter", "JSON"),
    ("invocable", "BOOLEAN NOT NULL DEFAULT 1"),
    ("pinned", "BOOLEAN NOT NULL DEFAULT 0"),
    ("local_only", "BOOLEAN NOT NULL DEFAULT 0"),
    ("license_spdx", "VARCHAR(40)"),
    ("license_sha256", "VARCHAR(64)"),
    ("license_accepted_at", "DATETIME"),
)
_CANDIDATE_COLUMNS = (
    ("conversation_id", "VARCHAR(100)"),
    ("files", "JSON"),
)


def _columns(connection, table: str) -> set[str]:
    return {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")}


def upgrade_sync(connection) -> None:
    have = _columns(connection, "skill_packs")
    for name, ddl in _SKILL_COLUMNS:
        if name not in have:
            connection.exec_driver_sql(f"ALTER TABLE skill_packs ADD COLUMN {name} {ddl}")
    connection.exec_driver_sql(
        "UPDATE skill_packs SET origin = 'imported' WHERE category = 'imported' AND origin = 'saved'")
    have = _columns(connection, "skill_candidates")
    for name, ddl in _CANDIDATE_COLUMNS:
        if name not in have:
            connection.exec_driver_sql(f"ALTER TABLE skill_candidates ADD COLUMN {name} {ddl}")


def downgrade_sync(connection) -> None:
    for name, _ in reversed(_CANDIDATE_COLUMNS):
        connection.exec_driver_sql(f"ALTER TABLE skill_candidates DROP COLUMN {name}")
    for name, _ in reversed(_SKILL_COLUMNS):
        connection.exec_driver_sql(f"ALTER TABLE skill_packs DROP COLUMN {name}")

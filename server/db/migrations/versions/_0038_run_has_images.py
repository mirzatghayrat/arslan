"""0038: runs.has_images — did this run's input carry image blocks?

WHY A COLUMN AND NOT A TEXT SNIFF: decision ③A stores the turn as a
"[图片:name]" PLACEHOLDER, so the transcript looks like it mentions an image
whether or not one was actually sent. Deriving the flag from that text would be
wrong in both directions — a user who literally types "[图片:foo.png]" gets
their run excluded, and any future path that sends an image without writing the
placeholder gets missed. The producer of the fact records the fact.

WHAT IT PROTECTS (spec T11): decision ③A also means an image lives for exactly
one turn. A run that carried one therefore CANNOT be replayed faithfully — the
baseline answered while looking at the picture, the replay arm can only see the
placeholder. Scoring those two against each other is not a comparison, and the
promotion gate's fairness quietly evaporates because nothing errors.

NULLABLE, and existing rows are deliberately NOT backfilled. NULL means "this
run predates the column", which for these rows is equivalent to False as a
matter of chronology, not of guessing: image input did not exist in any build
before this one. Read sites may therefore treat NULL as "no images" — the one
case where that is a fact rather than a fail-open assumption.
"""
from __future__ import annotations

_COLUMNS = (("has_images", "BOOLEAN"),)


def _tables(connection) -> set[str]:
    return {r[0] for r in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def _upgrade(connection) -> None:
    if "runs" not in _tables(connection):
        return
    existing = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(runs)")}
    for name, ddl in _COLUMNS:
        if name not in existing:
            connection.exec_driver_sql(f"ALTER TABLE runs ADD COLUMN {name} {ddl}")


def upgrade_sync(connection) -> None:
    _upgrade(connection)


def downgrade_sync(connection) -> None:
    """SQLite cannot drop a column before 3.35 and the repo supports older
    files; leaving it is harmless (nullable, unread by older code)."""
    return

"""0036: evolution_attempts.source — where an attempt came from.

`manual=True` had been a no-op parameter since the manual API was added: it was passed at
api/evolution.py, declared on enqueue_attempt, mentioned in a docstring, and never read.
There was nowhere to put it, because this table had no provenance column — so a human's
click and the background loop were indistinguishable in the DB, in the diagnosis payload,
and in the UI.

That mattered because two counters are derived by querying this table with no provenance
filter, and both are what the AUTO loop uses to decide when (and how patiently) to spend:
`_consecutive_fails` drives the exponential backoff, `_last_attempt_started_at` drives the
"enough new material?" cursor. A manual click therefore silently reshaped auto behavior.

NULLABLE, and existing rows are deliberately NOT backfilled. NULL means "provenance
unknown — predates this column", which is the truth; defaulting old rows to 'auto' would
fabricate attribution for precisely the manual clicks the column exists to account for.
Every read site must therefore be NULL-safe (`IS NOT 'manual'`, never `!= 'manual'`, which
is NULL — not TRUE — for a NULL row). Same posture as 0034's two columns.

Idempotency (this repo re-applies every migration on every boot): the ALTER is guarded by
PRAGMA table_info behind a sqlite_master table guard, so a second run is a no-op, and a
fresh DB built by Base.metadata.create_all already has the column.
"""
from __future__ import annotations

_COLUMNS = (("source", "VARCHAR(10)"),)


def _tables(connection) -> set[str]:
    return {r[0] for r in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def _upgrade(connection) -> None:
    if "evolution_attempts" not in _tables(connection):
        return
    existing = {row[1] for row in connection.exec_driver_sql(
        "PRAGMA table_info(evolution_attempts)")}
    for name, ddl in _COLUMNS:
        if name not in existing:
            connection.exec_driver_sql(
                f"ALTER TABLE evolution_attempts ADD COLUMN {name} {ddl}")
    # No backfill: NULL is the correct legacy value (see the module docstring).


def _downgrade(connection) -> None:
    if "evolution_attempts" not in _tables(connection):
        return
    for name, _ddl in _COLUMNS:
        try:  # SQLite pre-3.35 cannot DROP COLUMN; best-effort on newer versions
            connection.exec_driver_sql(
                f"ALTER TABLE evolution_attempts DROP COLUMN {name}")
        except Exception:  # noqa: BLE001 — downgrade is best-effort on old SQLite
            pass


def upgrade_sync(connection) -> None:
    _upgrade(connection)


def downgrade_sync(connection) -> None:
    _downgrade(connection)

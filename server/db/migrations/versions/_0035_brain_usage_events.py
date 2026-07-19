"""0035: brain_usage_events — the per-use event log behind the activity timeline.

`brain_usage` (0020) is a COUNTER: one upserted row per entity. It answers "how many
times" and "most recently", never "when were the other eleven". The frontend's activity
timeline needs individual timestamps, so this table appends one row per use.

🔴 THE CEILING IS PART OF THE FEATURE. An append-only table with no retention is
unbounded growth wearing a new name. `server.services.brain_usage.prune_events`
enforces two gates — age (`brain_usage_event_retention_days`, default 30) and row count
(`brain_usage_event_max_rows`, default 200k) — from the curation loop's heartbeat, and
deletes in bounded batches looping until clean. The `ix_brain_usage_events_used_at`
index below is what makes both the pruner's cutoff scan and the read endpoint's window
query cheap; it is not optional decoration.

Idempotency (this repo re-applies every migration on every boot): CREATE TABLE /
CREATE INDEX both use IF NOT EXISTS, so a second run is a no-op. Fresh DBs get the
final shape from Base.metadata.create_all (the BrainUsageEvent ORM model), so this
finds everything already present.

No backfill is possible or attempted: the counter never stored per-event timestamps,
so history before this migration genuinely does not exist. The read endpoint reports
its window rather than implying the empty stretch was a quiet period.
"""
from __future__ import annotations

_CREATE = """
CREATE TABLE IF NOT EXISTS brain_usage_events (
    id INTEGER NOT NULL PRIMARY KEY,
    kind VARCHAR(20) NOT NULL,
    ref_key VARCHAR(300) NOT NULL,
    used_at DATETIME NOT NULL,
    used_ref VARCHAR(100)
)
"""


def _upgrade(connection) -> None:
    connection.exec_driver_sql(_CREATE)
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_brain_usage_events_used_at "
        "ON brain_usage_events (used_at)")


def _downgrade(connection) -> None:
    connection.exec_driver_sql("DROP INDEX IF EXISTS ix_brain_usage_events_used_at")
    connection.exec_driver_sql("DROP TABLE IF EXISTS brain_usage_events")


def upgrade_sync(connection) -> None:
    _upgrade(connection)


def downgrade_sync(connection) -> None:
    _downgrade(connection)

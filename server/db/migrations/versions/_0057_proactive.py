"""0057: proactivity — items Arslan noticed, watches, mutes, diagnosis spend (0.1.47).

Four new tables, nothing existing is touched. Idempotent (IF NOT EXISTS); fresh
databases get the same shape from Base.metadata.create_all. Every table is
bounded by proactive_service.prune (age and row caps), not left to grow.
"""
from __future__ import annotations

_TABLES = (
    """CREATE TABLE IF NOT EXISTS proactive_items (
        id INTEGER NOT NULL PRIMARY KEY,
        kind VARCHAR(24) NOT NULL,
        fingerprint VARCHAR(200) NOT NULL UNIQUE,
        source_key VARCHAR(120) NOT NULL,
        title_key VARCHAR(60) NOT NULL,
        params JSON NOT NULL,
        evidence JSON NOT NULL,
        goal TEXT NOT NULL,
        criteria JSON NOT NULL,
        priority VARCHAR(8) NOT NULL,
        status VARCHAR(12) NOT NULL,
        diagnosis JSON,
        conversation_id VARCHAR(50),
        job_id VARCHAR(80),
        created_at DATETIME NOT NULL,
        seen_at DATETIME,
        acted_at DATETIME,
        snooze_until DATETIME,
        notified_at DATETIME
    )""",
    "CREATE INDEX IF NOT EXISTS ix_proactive_items_source_key ON proactive_items (source_key)",
    "CREATE INDEX IF NOT EXISTS ix_proactive_items_created_at ON proactive_items (created_at)",
    """CREATE TABLE IF NOT EXISTS proactive_watches (
        id INTEGER NOT NULL PRIMARY KEY,
        kind VARCHAR(8) NOT NULL,
        target VARCHAR(2000) NOT NULL,
        label VARCHAR(120) NOT NULL,
        enabled BOOLEAN NOT NULL,
        interval_s INTEGER NOT NULL,
        notify BOOLEAN NOT NULL,
        last_checked_at DATETIME,
        last_changed_at DATETIME,
        last_item_at DATETIME,
        last_hash VARCHAR(64),
        snapshot JSON,
        last_error VARCHAR(200),
        consecutive_errors INTEGER NOT NULL,
        created_at DATETIME NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS proactive_mutes (
        key VARCHAR(120) NOT NULL PRIMARY KEY,
        created_at DATETIME NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS proactive_spend (
        day VARCHAR(10) NOT NULL PRIMARY KEY,
        micro_usd INTEGER NOT NULL,
        calls INTEGER NOT NULL
    )""",
)


def upgrade_sync(connection) -> None:
    for statement in _TABLES:
        connection.exec_driver_sql(statement)


def downgrade_sync(connection) -> None:
    for table in ("proactive_spend", "proactive_mutes", "proactive_watches", "proactive_items"):
        connection.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")

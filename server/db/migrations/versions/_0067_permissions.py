"""0067: the permission store (0.1.61 §A5, §A8).

Three tables: standing answers ("Always", `permission_rules`), answers for one task or one
conversation (`permission_grants`), and a ledger of every decision that crossed a boundary
(`approval_events`). The old "don't ask again" list — settings `terminal_always_allow`, a
JSON list of rule names — becomes `legacy_rule` rows; the settings row stays, for a
downgrade. Idempotent; fresh databases get the tables from Base.metadata.create_all.
"""
from __future__ import annotations

import json
from datetime import datetime


def upgrade_sync(connection) -> None:
    connection.exec_driver_sql("""
    CREATE TABLE IF NOT EXISTS permission_rules (
        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
        kind VARCHAR(30) NOT NULL,
        target TEXT NOT NULL,
        label TEXT NOT NULL DEFAULT '',
        created_from VARCHAR(80) NOT NULL DEFAULT '',
        created_at DATETIME NOT NULL,
        last_used_at DATETIME,
        use_count INTEGER NOT NULL DEFAULT 0,
        UNIQUE (kind, target)
    )""")
    connection.exec_driver_sql("""
    CREATE TABLE IF NOT EXISTS permission_grants (
        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
        conversation_id VARCHAR(100) NOT NULL,
        task_id VARCHAR(100) NOT NULL DEFAULT '',
        kind VARCHAR(30) NOT NULL,
        target TEXT NOT NULL,
        call_id VARCHAR(64) NOT NULL DEFAULT '',
        created_at DATETIME NOT NULL,
        UNIQUE (conversation_id, task_id, kind, target)
    )""")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_permission_grants_conversation_id "
                               "ON permission_grants (conversation_id)")
    connection.exec_driver_sql("""
    CREATE TABLE IF NOT EXISTS approval_events (
        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
        created_at DATETIME NOT NULL,
        conversation_id VARCHAR(100),
        job_id VARCHAR(100),
        run_id VARCHAR(100),
        kind VARCHAR(30) NOT NULL,
        target TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '',
        extra JSON,
        mode VARCHAR(20) NOT NULL,
        decided_by VARCHAR(20) NOT NULL,
        decision VARCHAR(10) NOT NULL,
        scope VARCHAR(20),
        rule_id INTEGER,
        grant_id INTEGER,
        reviewer JSON,
        wait_ms INTEGER
    )""")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_approval_events_created_at "
                               "ON approval_events (created_at)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_approval_events_conversation_id "
                               "ON approval_events (conversation_id)")
    _copy_legacy_rules(connection)


def _copy_legacy_rules(connection) -> None:
    """The old list, as `legacy_rule` rows. An unreadable list copies nothing: a standing
    permission is never inferred from an error (terminal_policy's rule)."""
    try:
        row = connection.exec_driver_sql(
            "SELECT value FROM settings WHERE key = 'terminal_always_allow'").fetchone()
    except Exception:  # noqa: BLE001 — no settings table on a bare database
        return
    if not row:
        return
    try:
        rules = [str(r) for r in json.loads(row[0]) if str(r).strip()]
    except (ValueError, TypeError):
        return
    now = datetime.utcnow().isoformat(sep=" ")
    for rule in rules:
        connection.exec_driver_sql(
            "INSERT OR IGNORE INTO permission_rules (kind, target, label, created_from, created_at, "
            "use_count) VALUES ('legacy_rule', ?, '', 'migration', ?, 0)", (rule, now))


def downgrade_sync(connection) -> None:
    for table in ("approval_events", "permission_grants", "permission_rules"):
        connection.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")

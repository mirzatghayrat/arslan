"""0086: task routing is removed (v0.1.64 ROUTE1, docs/plans/0164/ROUTE1-remove-routing.md).

Every role now runs on the conversation's own model, else the primary. This clears what routing left in `settings`:
the strategy (`llm_strategy`), the two removed slots (compaction and final answer: `compaction_*`, `synthesis_*`), and
the pins on the two slots that stay (`router_*`, `vision_*`), which were all chosen under the old routing (the user's
all pointed at the provider whose outage made a chat unusable). When a user's choice was cleared it sets
`model_roles_reset_notice` to "pending", and Settings says once that the roles now follow each conversation's model.
`llm_strategy="single"` is not a choice in that sense: migration 0006 seeds it on every install, and it already meant
"the primary", so clearing it alone asks for no notice.

Data only, in this table only; never the user's files. Idempotent: a second run finds nothing to clear and leaves the
notice as it is ("seen" stays "seen"). A database without the table (a new install) is left alone.
"""
from __future__ import annotations

CLEARED = ("llm_strategy",
           "compaction_config_id", "compaction_model", "synthesis_config_id", "synthesis_model",
           "router_config_id", "router_model", "vision_config_id", "vision_model")
NOTICE = "model_roles_reset_notice"


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "settings" not in tables:
        return
    marks = ",".join("?" for _ in CLEARED)
    had = connection.exec_driver_sql(
        f"SELECT COUNT(*) FROM settings WHERE key IN ({marks}) AND TRIM(COALESCE(value, '')) <> '' "
        "AND NOT (key = 'llm_strategy' AND TRIM(value) = 'single')", CLEARED).scalar()
    connection.exec_driver_sql(f"DELETE FROM settings WHERE key IN ({marks})", CLEARED)
    if had:
        connection.exec_driver_sql(
            "INSERT INTO settings (key, value) VALUES (?, 'pending') "
            "ON CONFLICT(key) DO UPDATE SET value = 'pending'", (NOTICE,))


def downgrade_sync(connection) -> None:
    """The cleared choices are not kept, so there is nothing to put back; older code reads the missing keys as unset."""
    return

"""0073: drop `router_decisions` (v0.1.64, C7c-2).

The pre-turn router wrote one row per message into this audit table until 0.1.48 replaced it with one
loop; nothing has written it since, and no code reads it (C7c-1 removed the model). The drop is its own
step, after the code that used the table (v0.1.64 plan §6: code can be reverted, a table can't). Its
rows are routing decisions from before 0.1.48. They are in the upgrade backup the runner takes before
any migration (`prepare_upgrade_backup`, also on an install that already ran the later ids) until that
backup is pruned: only the newest three are kept (`upgrade_backup.py`). No other table points at it (its `spawn_id` was never a foreign key), so the drop deletes
nothing else. Idempotent; a database without the table (a fresh install since C7c-1) is left alone.
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    connection.exec_driver_sql("DROP TABLE IF EXISTS router_decisions")


def downgrade_sync(connection) -> None:
    """Nothing to restore: no code reads the table, and its rows are in the upgrade backup while it is kept."""
    return

"""0056: scheduled tasks are run by Arslan (0.1.44, one Arslan).

Experts are no longer a runtime path, so every scheduled task's `target` becomes
`arslan`. Name, prompt, cadence and history are unchanged; `spawn_id` is kept so
the former expert stays traceable. The pre-upgrade backup covers rollback.
"""
import sqlalchemy as sa


def upgrade_sync(connection):
    tables = {row[0] for row in connection.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table'"))}
    if "scheduled_tasks" in tables:
        connection.execute(sa.text("UPDATE scheduled_tasks SET target = 'arslan' WHERE target != 'arslan'"))

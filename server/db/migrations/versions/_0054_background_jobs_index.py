"""0054: background jobs may run beside a conversation's foreground turn (0.1.42).

`uq_companion_active_conversation` allowed one running/verifying task per
conversation, which kept two tabs from running two turns at once. It must keep
doing that for turns, but a background job is by design concurrent with the
turn that started it and with other jobs, so the index now excludes tasks whose
recorded driver is `background`. Rows are not touched; only the index changes.
"""
import sqlalchemy as sa

WHERE = ("phase IN ('running','verifying') AND "
         "COALESCE(json_extract(privacy, '$.driver.kind'), 'host') != 'background'")


def upgrade_sync(connection):
    connection.execute(sa.text("DROP INDEX IF EXISTS uq_companion_active_conversation"))
    connection.execute(sa.text(
        "CREATE UNIQUE INDEX uq_companion_active_conversation "
        f"ON companion_tasks (owner_id, conversation_id) WHERE {WHERE}"))

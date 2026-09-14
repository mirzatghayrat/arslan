"""0051: goals, fenced execution attempts, checkpoints and action reconciliation."""


def upgrade_sync(connection):
    from server.db.task_models import (
        CompanionTask, TaskAction, TaskAttempt, TaskCheckpoint, TaskEvent, TaskRevision,
    )
    for model in (CompanionTask, TaskRevision, TaskAttempt, TaskCheckpoint, TaskEvent, TaskAction):
        model.__table__.create(connection, checkfirst=True)

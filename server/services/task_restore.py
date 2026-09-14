"""Invalidate restored task approvals in the staged database, without executing."""
from datetime import datetime

from sqlalchemy import insert, select, update

from server.db.models import CompanionTask, TaskAction, TaskAttempt, TaskEvent, TaskWorker


def quarantine_sync(connection):
    tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
    if "companion_tasks" not in tables:
        return
    columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(companion_tasks)")}
    if not {"phase", "sequence", "version", "attempt_id", "spec_revision", "privacy"}.issubset(columns):
        return  # A historical non-companion table is not guessed into this schema.
    now = datetime.utcnow()
    rows = connection.execute(select(CompanionTask.__table__)).mappings().all()
    for row in rows:
        privacy = {**(row["privacy"] or {}), "no_learning": True,
                   "cloud_memory_allowed": False, "allow_sensitive": False}
        cancelled = row["phase"] == "cancelled" or row["cancel_requested"]
        sequence = row["sequence"] + 1
        phase = "cancelled" if cancelled else "waiting_user"
        connection.execute(update(CompanionTask).where(CompanionTask.id == row["id"]).values(
            version=row["version"] + 1, sequence=sequence, phase=phase, privacy=privacy,
            results=[], pause_reason="user_cancelled" if cancelled else "backup_restore_review_required",
            updated_at=now,
        ))
        if "task_events" in tables:
            connection.execute(insert(TaskEvent).values(
                task_id=row["id"], sequence=sequence, attempt_id=row["attempt_id"],
                kind="backup_restored", payload={"phase": phase, "spec_revision": row["spec_revision"]},
                created_at=now,
            ))
        if "task_attempts" in tables:
            connection.execute(update(TaskAttempt).where(TaskAttempt.id == row["attempt_id"]).values(
                status="cancelled" if cancelled else "restored", ended_at=now))
    if "task_actions" in tables:
        connection.execute(update(TaskAction).where(TaskAction.status.in_(("prepared", "in_flight"))).values(
            status="uncertain", version=TaskAction.version + 1, updated_at=now))
    if "task_workers" in tables:
        connection.execute(update(TaskWorker).where(TaskWorker.status.in_(("queued", "running"))).values(
            status="interrupted", ended_at=now))

"""Quarantine restored memory before the staged database can be opened.

The archive is unchanged. The restored copy preserves history but invalidates
memory approvals, cached prompts and background schedules. A small guard also
survives restoration of pre-v2 databases until their normal migration runs.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import insert, select, text, update

from server.db.models import MemoryEntry, MemoryRevision, MemorySource, MemorySuppression


def _tables(connection):
    return set(connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).scalars())


def _columns(connection, table):
    # Table names below are program constants, never archive/user SQL.
    return {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")}


def is_restored_sync(connection) -> bool:
    return "memory_restore_guard" in _tables(connection) and bool(connection.execute(
        text("SELECT 1 FROM memory_restore_guard WHERE id=1")).first())


def mark_restored_sync(connection) -> dict:
    """Only for a validated, staged backup, in the caller's transaction."""
    connection.exec_driver_sql("""CREATE TABLE IF NOT EXISTS memory_restore_guard (
        id INTEGER PRIMARY KEY CHECK(id=1), restore_id TEXT NOT NULL,
        restored_at TEXT NOT NULL, applied INTEGER NOT NULL DEFAULT 0)""")
    connection.exec_driver_sql("""CREATE TABLE IF NOT EXISTS memory_restore_sources (
        source_kind TEXT NOT NULL, source_id TEXT NOT NULL,
        PRIMARY KEY(source_kind,source_id))""")
    restore_id, now = str(uuid4()), datetime.utcnow()
    connection.execute(text("""INSERT INTO memory_restore_guard(id,restore_id,restored_at,applied)
        VALUES(1,:id,:now,0) ON CONFLICT(id) DO UPDATE SET
        restore_id=excluded.restore_id,restored_at=excluded.restored_at,applied=0"""),
        {"id": restore_id, "now": now.isoformat()})
    tables = _tables(connection)
    # Preserve opaque source identities, not any transcript or business text.
    for table, column, kind in (
        ("arslan_messages", "id", "message_id"), ("arslan_messages", "conversation_id", "conversation_id"),
        ("runs", "id", "run_id"), ("runs", "conversation_id", "conversation_id"),
        ("companion_tasks", "id", "task_id"),
    ):
        if table in tables and column in _columns(connection, table):
            connection.exec_driver_sql(f"""INSERT OR IGNORE INTO memory_restore_sources(source_kind,source_id)
                SELECT '{kind}',CAST({column} AS TEXT) FROM {table} WHERE {column} IS NOT NULL""")
    # Prior task-level cloud permissions and linked projects need a fresh choice.
    if "conversation_contexts" in tables:
        connection.exec_driver_sql("""UPDATE conversation_contexts
            SET cloud_memory_allowed=0,allow_sensitive=0,version=version+1""")
    if "projects" in tables:
        connection.exec_driver_sql("UPDATE projects SET status='archived',version=version+1 WHERE status='active'")
    if "scheduled_tasks" in tables:
        columns = _columns(connection, "scheduled_tasks")
        if "enabled" in columns:
            reason = ",paused_reason='backup_restore_review_required'" if "paused_reason" in columns else ""
            connection.exec_driver_sql(f"UPDATE scheduled_tasks SET enabled=0{reason}")
    if "arslan_summaries" in tables:
        connection.exec_driver_sql("DELETE FROM arslan_summaries")
    if "runs" in tables:
        if "no_learning" in _columns(connection, "runs"):
            connection.exec_driver_sql("UPDATE runs SET no_learning=1")
        cached = [column for column in ("system_prompt", "injected_kb", "injected_kb_sources")
                  if column in _columns(connection, "runs")]
        if cached:
            connection.exec_driver_sql(f"UPDATE runs SET {','.join(column + '=NULL' for column in cached)}")
    result = apply_pending_guard_sync(connection)
    from server.services.task_restore import quarantine_sync
    quarantine_sync(connection)
    return {"restore_id": restore_id, "review_required": True, **result}


def apply_pending_guard_sync(connection) -> dict:
    """Idempotently finish quarantine after v2 tables exist."""
    tables = _tables(connection)
    if "memory_restore_guard" not in tables:
        return {"quarantined_entries": 0}
    guard = connection.execute(text("SELECT * FROM memory_restore_guard WHERE id=1")).mappings().first()
    if guard is None or guard["applied"] or not {"memory_entries", "memory_revisions"}.issubset(tables):
        return {"quarantined_entries": 0}
    MemorySuppression.__table__.create(connection, checkfirst=True)
    now = datetime.utcnow()
    rows = connection.execute(select(MemoryEntry.__table__).where(MemoryEntry.status != "deleted")).mappings().all()
    for entry in rows:
        revision = connection.execute(select(MemoryRevision.__table__).where(
            MemoryRevision.id == entry["current_revision_id"], MemoryRevision.entry_id == entry["id"],
        )).mappings().one()
        revision_id, source_id = str(uuid4()), str(uuid4())
        version = entry["version"] + 1
        connection.execute(insert(MemoryRevision).values(
            id=revision_id, entry_id=entry["id"], version=version, content=revision["content"],
            structured_value=revision["structured_value"], previous_version=entry["version"],
            change_reason="backup_restore_review_required", created_at=now,
        ))
        connection.execute(update(MemoryEntry).where(MemoryEntry.id == entry["id"]).values(
            status="quarantined", version=version, current_revision_id=revision_id,
            confirmed_at=None, confirmation_kind=None,
            use_policy="never" if entry["use_policy"] == "never" else "local_only", updated_at=now,
        ))
        connection.execute(insert(MemorySource).values(
            id=source_id, entry_id=entry["id"], revision_id=revision_id, source_kind="restore",
            source_ref={"restore_id": guard["restore_id"]}, author="system", created_at=now, observed_at=now,
        ))
    connection.execute(text("""INSERT OR IGNORE INTO memory_suppressions
        (source_kind,source_id,entry_id,cutoff_at,created_at)
        SELECT source_kind,source_id,:restore_id,:now,:now FROM memory_restore_sources"""),
        {"restore_id": guard["restore_id"], "now": now})
    if "memory_entries_fts" in tables:
        connection.exec_driver_sql("DELETE FROM memory_entries_fts")
    connection.execute(text("UPDATE memory_restore_guard SET applied=1 WHERE id=1"))
    return {"quarantined_entries": len(rows)}

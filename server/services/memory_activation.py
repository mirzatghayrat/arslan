"""Atomic v2 activation: compatibility views, immutable legacy recovery inputs."""
from sqlalchemy import text

from server.services.memory_migration import migrate_legacy_sync


def activate_sync(connection):
    phase = connection.execute(text("SELECT phase FROM memory_store_state WHERE id=1")).scalar()
    if phase == "active":
        return
    migrate_legacy_sync(connection)
    columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(runs)")}
    if "no_learning" in columns:
        # Existing attempts have no v2 privacy receipt. Keep their history, but
        # never retroactively authorize background reuse.
        connection.exec_driver_sql("UPDATE runs SET no_learning=1")
    for name in ("user_facts", "learnings"):
        connection.exec_driver_sql(f"ALTER TABLE {name} RENAME TO legacy_{name}")
        for action in ("INSERT", "UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f"CREATE TRIGGER guard_legacy_{name}_{action.lower()} BEFORE {action} ON legacy_{name} "
                "WHEN (SELECT phase FROM memory_store_state WHERE id=1) != 'maintenance' "
                "BEGIN SELECT RAISE(ABORT, 'legacy_memory_is_read_only'); END")
    common = """
        FROM memory_legacy_map m JOIN memory_entries e ON e.id=m.entry_id
        JOIN memory_revisions r ON r.id=e.current_revision_id AND r.entry_id=e.id
        WHERE e.status != 'deleted'
    """
    source = """COALESCE((SELECT json_extract(s.source_ref,'$.source_kind')
                         FROM memory_sources s WHERE s.entry_id=e.id ORDER BY s.created_at LIMIT 1),
                        (SELECT s.source_kind FROM memory_sources s WHERE s.entry_id=e.id
                         ORDER BY s.created_at LIMIT 1), 'unknown')"""
    provenance = f"""json_object('source_kind', {source},
                      'memory_entry_id', e.id, 'memory_version', e.version,
                      'memory_status', e.status, 'stale', e.status='paused')"""
    connection.exec_driver_sql(f"""
        CREATE VIEW user_facts AS SELECT CAST(m.source_key AS INTEGER) AS id,
        COALESCE(r.content,'') AS content,
        CASE WHEN e.confirmation_kind IS NOT NULL THEN 'manual' ELSE 'auto' END AS source,
        CASE WHEN e.sensitivity='normal' THEN 0 ELSE 1 END AS sensitive,
        json_extract(r.structured_value,'$.legacy_category') AS category,
        json_extract(r.structured_value,'$.legacy_label') AS label,
        e.confidence, e.created_at, e.valid_from,
        (SELECT CAST(mm.source_key AS INTEGER) FROM memory_legacy_map mm
         WHERE mm.entry_id=e.superseded_by AND mm.source_table='user_facts') AS superseded_by,
        {provenance} AS provenance
        {common} AND m.source_table='user_facts'
    """)
    connection.exec_driver_sql(f"""
        CREATE VIEW learnings AS SELECT CAST(m.source_key AS INTEGER) AS id,
        COALESCE(r.content,'') AS content,
        json_extract(r.structured_value,'$.legacy_label') AS label,
        {source} AS source_kind, {provenance} AS source_ref,
        CASE WHEN e.scope_kind='expert' THEN CAST(e.scope_id AS INTEGER) ELSE NULL END AS spawn_id,
        e.confidence, e.created_at, e.valid_from,
        (SELECT CAST(mm.source_key AS INTEGER) FROM memory_legacy_map mm
         WHERE mm.entry_id=e.superseded_by AND mm.source_table='learnings') AS superseded_by
        {common} AND m.source_table='learnings'
    """)
    connection.exec_driver_sql("""
        CREATE TRIGGER guard_legacy_spawn_preferences BEFORE UPDATE OF memory_facts ON spawns
        WHEN COALESCE(NEW.memory_facts,'[]') != COALESCE(OLD.memory_facts,'[]')
          AND (SELECT phase FROM memory_store_state WHERE id=1) != 'maintenance'
        BEGIN SELECT RAISE(ABORT, 'legacy_memory_is_read_only'); END
    """)
    connection.exec_driver_sql("""
        CREATE TRIGGER guard_new_spawn_preferences BEFORE INSERT ON spawns
        WHEN COALESCE(NEW.memory_facts,'[]') != '[]'
          AND (SELECT phase FROM memory_store_state WHERE id=1) != 'maintenance'
        BEGIN SELECT RAISE(ABORT, 'legacy_memory_is_read_only'); END
    """)
    connection.exec_driver_sql(
        "CREATE VIRTUAL TABLE IF NOT EXISTS memory_entries_fts USING fts5(entry_id UNINDEXED, content)")
    connection.exec_driver_sql("DELETE FROM memory_entries_fts")
    connection.exec_driver_sql("""
        INSERT INTO memory_entries_fts(entry_id, content)
        SELECT e.id, r.content FROM memory_entries e JOIN memory_revisions r ON r.id=e.current_revision_id
        WHERE e.status!='deleted' AND e.sensitivity!='secret' AND r.content IS NOT NULL
    """)
    connection.execute(text("UPDATE memory_store_state SET phase='active' WHERE id=1"))

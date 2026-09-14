"""0048: explicit v2 candidate targets, preserving all old proposal identities."""
from sqlalchemy import MetaData
from sqlalchemy.schema import CreateTable


def upgrade_sync(connection):
    from server.db.models import MemoryProposal
    columns = {row[1]: row for row in connection.exec_driver_sql("PRAGMA table_info(memory_proposals)")}
    for name, sql_type in (("target_entry_id", "VARCHAR(36)"), ("target_version", "INTEGER"), ("candidate", "JSON")):
        if name not in columns:
            connection.exec_driver_sql(f"ALTER TABLE memory_proposals ADD COLUMN {name} {sql_type}")
    columns = {row[1]: row for row in connection.exec_driver_sql("PRAGMA table_info(memory_proposals)")}
    if columns["old_id"][3]:
        # Rebuild from the current model, but copy only shared column names and all rows.
        # There are no inbound foreign keys to the proposal table.
        metadata = MetaData()
        table = MemoryProposal.__table__.to_metadata(metadata, name="memory_proposals_v2_new")
        connection.execute(CreateTable(table))
        names = ", ".join(f'"{column.name}"' for column in table.columns if column.name in columns)
        connection.exec_driver_sql(
            f"INSERT INTO memory_proposals_v2_new ({names}) SELECT {names} FROM memory_proposals")
        connection.exec_driver_sql("DROP TABLE memory_proposals")
        connection.exec_driver_sql("ALTER TABLE memory_proposals_v2_new RENAME TO memory_proposals")
    for name in ("status", "conversation_id", "target_entry_id"):
        connection.exec_driver_sql(
            f"CREATE INDEX IF NOT EXISTS ix_memory_proposals_{name} ON memory_proposals ({name})")

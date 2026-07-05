"""second brain: collections + spawn_collections + knowledge_chunks new columns.

knowledge_chunks needs spawn_id → nullable + a CHECK constraint; SQLite cannot
do either via ALTER TABLE, so the old-shape table is REBUILT (create-copy-drop-
rename) with ids preserved verbatim — the FTS5 rowid mapping depends on them.
Fresh DBs get the final shape from Base.metadata.create_all (runs BEFORE this
in main.py boot), making this a no-op there. collections/spawn_collections are
likewise created by create_all; this migration only creates them when running
under plain alembic against an old DB."""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

_NEW_SHAPE = """
CREATE TABLE knowledge_chunks_new (
    id INTEGER PRIMARY KEY,
    spawn_id INTEGER REFERENCES spawns(id) ON DELETE CASCADE,
    collection_id INTEGER REFERENCES collections(id) ON DELETE CASCADE,
    source VARCHAR(200) NOT NULL,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    embedding BLOB,
    embedding_model VARCHAR(80),
    created_at DATETIME,
    CONSTRAINT ck_chunk_exactly_one_scope CHECK ((spawn_id IS NULL) != (collection_id IS NULL))
)
"""

_OLD_SHAPE = """
CREATE TABLE knowledge_chunks_old (
    id INTEGER PRIMARY KEY,
    spawn_id INTEGER NOT NULL REFERENCES spawns(id) ON DELETE CASCADE,
    source VARCHAR(200) NOT NULL,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    created_at DATETIME
)
"""


def _upgrade(bind) -> None:  # noqa: ANN001
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "collections" not in tables:
        bind.exec_driver_sql(
            "CREATE TABLE collections (id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL, "
            "description TEXT, created_at DATETIME)")
    if "spawn_collections" not in tables:
        bind.exec_driver_sql(
            "CREATE TABLE spawn_collections (id INTEGER PRIMARY KEY, "
            "spawn_id INTEGER NOT NULL REFERENCES spawns(id) ON DELETE CASCADE, "
            "collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE, "
            "UNIQUE (spawn_id, collection_id))")
        bind.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_spawn_collections_spawn_id ON spawn_collections (spawn_id)")
        bind.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_spawn_collections_collection_id ON spawn_collections (collection_id)")
    if "knowledge_chunks" not in tables:
        return  # brand-new DB: create_all already made the final shape
    cols = {c["name"]: c for c in insp.get_columns("knowledge_chunks")}
    if "collection_id" in cols and cols["spawn_id"]["nullable"]:
        return  # already migrated (idempotent)
    # Self-heal: a crash between CREATE and RENAME can leave the temp table behind.
    bind.exec_driver_sql("DROP TABLE IF EXISTS knowledge_chunks_new")
    bind.exec_driver_sql(_NEW_SHAPE)
    bind.exec_driver_sql(
        "INSERT INTO knowledge_chunks_new (id, spawn_id, source, chunk_index, text, created_at) "
        "SELECT id, spawn_id, source, chunk_index, text, created_at FROM knowledge_chunks")
    bind.exec_driver_sql("DROP TABLE knowledge_chunks")
    bind.exec_driver_sql("ALTER TABLE knowledge_chunks_new RENAME TO knowledge_chunks")
    bind.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_spawn_id ON knowledge_chunks (spawn_id)")
    bind.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_collection_id ON knowledge_chunks (collection_id)")


def _downgrade(bind) -> None:  # noqa: ANN001
    """Reverse the rebuild: drop the new columns/constraint, restore spawn_id
    NOT NULL. LOSSY: rows with collection_id set (no spawn_id) cannot survive a
    downgrade to the old spawn-only shape and are dropped — this mirrors the
    forward-only nature of the feature (shared collections didn't exist pre-0018).
    Their knowledge_chunks_fts rows are deleted too, or future id reuse would
    produce false FTS matches (the vtable maps rowid == knowledge_chunks.id)."""
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "knowledge_chunks" in tables:
        cols = {c["name"] for c in insp.get_columns("knowledge_chunks")}
        if "collection_id" in cols:
            if "knowledge_chunks_fts" in tables:
                bind.exec_driver_sql(
                    "DELETE FROM knowledge_chunks_fts WHERE rowid IN "
                    "(SELECT id FROM knowledge_chunks WHERE spawn_id IS NULL)")
            # Self-heal: a crash between CREATE and RENAME can leave the temp table behind.
            bind.exec_driver_sql("DROP TABLE IF EXISTS knowledge_chunks_old")
            bind.exec_driver_sql(_OLD_SHAPE)
            bind.exec_driver_sql(
                "INSERT INTO knowledge_chunks_old (id, spawn_id, source, chunk_index, text, created_at) "
                "SELECT id, spawn_id, source, chunk_index, text, created_at FROM knowledge_chunks "
                "WHERE spawn_id IS NOT NULL")
            bind.exec_driver_sql("DROP TABLE knowledge_chunks")
            bind.exec_driver_sql("ALTER TABLE knowledge_chunks_old RENAME TO knowledge_chunks")
            bind.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_spawn_id ON knowledge_chunks (spawn_id)")
    if "spawn_collections" in tables:
        bind.exec_driver_sql("DROP TABLE spawn_collections")
    if "collections" in tables:
        bind.exec_driver_sql("DROP TABLE collections")


def upgrade() -> None:
    _upgrade(op.get_bind())


def upgrade_sync(connection) -> None:  # noqa: ANN001
    _upgrade(connection)


def downgrade() -> None:
    _downgrade(op.get_bind())


def downgrade_sync(connection) -> None:  # noqa: ANN001
    _downgrade(connection)

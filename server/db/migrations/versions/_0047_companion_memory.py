"""0047: versioned projects/memory, lossless legacy references, no automatic activation."""


def upgrade_sync(connection):
    from server.db.models import MemoryDeletion
    from server.services.memory_migration import migrate_legacy_sync
    MemoryDeletion.__table__.create(connection, checkfirst=True)
    migrate_legacy_sync(connection)

"""0053: credential-free metadata and exact, single-use action approvals."""


def upgrade_sync(connection):
    from server.db.permission_models import ActionGrantRecord, CompanionConnection
    for model in (CompanionConnection, ActionGrantRecord):
        model.__table__.create(connection, checkfirst=True)

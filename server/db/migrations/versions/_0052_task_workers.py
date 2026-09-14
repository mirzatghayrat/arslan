"""0052: versioned methods and ephemeral, task-owned collaboration records."""


def upgrade_sync(connection):
    from server.db.worker_models import ProfessionalMethod, ProfessionalMethodVersion, TaskWorker
    for model in (ProfessionalMethod, ProfessionalMethodVersion, TaskWorker):
        model.__table__.create(connection, checkfirst=True)

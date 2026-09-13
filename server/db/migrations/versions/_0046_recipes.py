"""0046: immutable recipe versions and durable execution checkpoints."""


def upgrade_sync(connection):
    from server.db.models import RecipeExecution, RecipeVersion
    RecipeVersion.__table__.create(connection, checkfirst=True)
    RecipeExecution.__table__.create(connection, checkfirst=True)

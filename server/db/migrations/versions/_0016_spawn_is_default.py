"""add is_default flag to spawns (built-in, undeletable agents)."""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def _upgrade(bind) -> None:
    # Raw ALTER (not op.add_column) so this works both under alembic AND via the
    # main.py boot `upgrade_sync(connection)` backfill path (mirrors _0014).
    insp = sa.inspect(bind)
    if "spawns" in set(insp.get_table_names()):
        cols = {c["name"] for c in insp.get_columns("spawns")}
        if "is_default" not in cols:
            bind.exec_driver_sql("ALTER TABLE spawns ADD COLUMN is_default BOOLEAN NOT NULL DEFAULT 0")


def upgrade() -> None:
    _upgrade(op.get_bind())


def upgrade_sync(connection) -> None:
    _upgrade(connection)


def downgrade() -> None:
    op.drop_column("spawns", "is_default")


def downgrade_sync(connection) -> None:
    op.drop_column("spawns", "is_default")

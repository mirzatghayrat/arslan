"""add archived flag to chat_messages."""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def _upgrade(bind) -> None:
    # Raw ALTER (not op.add_column) so this works both under alembic AND via the
    # main.py boot `upgrade_sync(connection)` backfill path (mirrors _0011).
    insp = sa.inspect(bind)
    if "chat_messages" in set(insp.get_table_names()):
        cols = {c["name"] for c in insp.get_columns("chat_messages")}
        if "archived" not in cols:
            bind.exec_driver_sql("ALTER TABLE chat_messages ADD COLUMN archived BOOLEAN NOT NULL DEFAULT 0")


def upgrade() -> None:
    _upgrade(op.get_bind())


def upgrade_sync(connection) -> None:
    _upgrade(connection)


def downgrade() -> None:
    op.drop_column("chat_messages", "archived")


def downgrade_sync(connection) -> None:
    op.drop_column("chat_messages", "archived")

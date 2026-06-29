"""add archived flag to chat_messages."""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def _upgrade(bind) -> None:
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("chat_messages")}
    if "archived" not in cols:
        op.add_column("chat_messages", sa.Column("archived", sa.Boolean(), nullable=False, server_default="0"))


def upgrade() -> None:
    _upgrade(op.get_bind())


def upgrade_sync(connection) -> None:
    _upgrade(connection)


def downgrade() -> None:
    op.drop_column("chat_messages", "archived")


def downgrade_sync(connection) -> None:
    op.drop_column("chat_messages", "archived")

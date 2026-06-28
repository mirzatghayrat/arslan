"""distilled_sessions table (session-end distillation idempotency marker)."""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"


def _upgrade(bind) -> None:
    insp = sa.inspect(bind)
    if "distilled_sessions" not in set(insp.get_table_names()):
        sa.Table(
            "distilled_sessions", sa.MetaData(),
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("conversation_id", sa.String(50), nullable=False, index=True),
            sa.Column("spawn_id", sa.Integer(), nullable=False),
            sa.Column("timestamp", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("conversation_id", "spawn_id", name="uq_distilled_conv_spawn"),
        ).create(bind)


def upgrade() -> None:
    _upgrade(op.get_bind())


def upgrade_sync(connection) -> None:
    _upgrade(connection)


def downgrade() -> None:
    pass


def downgrade_sync(connection) -> None:
    pass

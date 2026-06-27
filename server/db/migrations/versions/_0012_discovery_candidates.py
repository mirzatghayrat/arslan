"""discovery_candidates table (curated discovery catalog)."""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"


def _upgrade(bind) -> None:
    insp = sa.inspect(bind)
    if "discovery_candidates" not in set(insp.get_table_names()):
        sa.Table(
            "discovery_candidates", sa.MetaData(),
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("full_name", sa.String(140), nullable=False, unique=True),
            sa.Column("html_url", sa.String(500), nullable=True),
            sa.Column("snapshot", sa.JSON(), nullable=False),
            sa.Column("saved_at", sa.DateTime(), nullable=True),
        ).create(bind)


def upgrade() -> None:
    _upgrade(op.get_bind())


def upgrade_sync(connection) -> None:
    _upgrade(connection)


def downgrade() -> None:
    pass


def downgrade_sync(connection) -> None:
    pass

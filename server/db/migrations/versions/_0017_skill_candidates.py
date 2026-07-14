"""skill_candidates table (authored skill drafts awaiting human confirm)."""
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"


def _upgrade(bind) -> None:
    insp = sa.inspect(bind)
    if "skill_candidates" not in set(insp.get_table_names()):
        sa.Table(
            "skill_candidates", sa.MetaData(),
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("key", sa.String(60), nullable=False, index=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("category", sa.String(40), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("source", sa.String(20), nullable=False, server_default="skill_creator"),
            sa.Column("status", sa.String(20), nullable=False, server_default="observing"),
            sa.Column("samples", sa.JSON()),
            sa.Column("evidence", sa.JSON()),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("promoted_at", sa.DateTime(), nullable=True),
        ).create(bind)


def upgrade_sync(connection) -> None:
    _upgrade(connection)


def downgrade_sync(connection) -> None:
    pass

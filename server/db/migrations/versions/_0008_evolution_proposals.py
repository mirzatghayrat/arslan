"""evolution_proposals table

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _table(metadata: sa.MetaData) -> sa.Table:
    return sa.Table(
        "evolution_proposals", metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("spawn_id", sa.Integer(), nullable=False, index=True),
        sa.Column("candidate_prompt", sa.Text(), nullable=False),
        sa.Column("gate_passed", sa.Boolean(), nullable=False),
        sa.Column("evidence", sa.JSON()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("promoted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["spawn_id"], ["spawns.id"], ondelete="CASCADE"),
    )


def _upgrade(bind) -> None:  # noqa: ANN001
    insp = sa.inspect(bind)
    if "evolution_proposals" not in set(insp.get_table_names()):
        metadata = sa.MetaData()
        sa.Table("spawns", metadata, sa.Column("id", sa.Integer(), primary_key=True),
                 keep_existing=True)
        _table(metadata).create(bind)


def _downgrade(bind) -> None:  # noqa: ANN001
    metadata = sa.MetaData()
    sa.Table("spawns", metadata, sa.Column("id", sa.Integer(), primary_key=True),
             keep_existing=True)
    _table(metadata).drop(bind, checkfirst=True)


def upgrade() -> None:
    _upgrade(op.get_bind())


def downgrade() -> None:
    _downgrade(op.get_bind())


def upgrade_sync(connection) -> None:  # noqa: ANN001
    _upgrade(connection)


def downgrade_sync(connection) -> None:  # noqa: ANN001
    _downgrade(connection)

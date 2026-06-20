"""spawn_phases table for staged-orchestration phase persistence

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-20

One row per conversation; stores the pending proposal phase so reconnect
restores the routed spawn's proposed direction.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _table_def(metadata: sa.MetaData) -> sa.Table:
    return sa.Table(
        "spawn_phases",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.String(50), nullable=False),
        sa.Column("spawn_id", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.String(50), nullable=False),
    )


def _upgrade(bind) -> None:  # noqa: ANN001
    insp = sa.inspect(bind)
    existing = set(insp.get_table_names())
    if "spawn_phases" not in existing:
        metadata = sa.MetaData()
        tbl = _table_def(metadata)
        tbl.create(bind)
        bind.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_spawn_phases_conversation_id"
                " ON spawn_phases (conversation_id)"
            )
        )


def _downgrade(bind) -> None:  # noqa: ANN001
    metadata = sa.MetaData()
    tbl = _table_def(metadata)
    tbl.drop(bind, checkfirst=True)


def upgrade() -> None:
    _upgrade(op.get_bind())


def downgrade() -> None:
    _downgrade(op.get_bind())


# Test helper: apply against a raw (sync) connection.
def upgrade_sync(connection) -> None:  # noqa: ANN001
    _upgrade(connection)


def downgrade_sync(connection) -> None:  # noqa: ANN001
    _downgrade(connection)

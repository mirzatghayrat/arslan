"""conversation_spawns roster table

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-21

Per-conversation spawn roster membership for the conversation-workbench feature.
"""
from __future__ import annotations

import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _table_def(metadata: sa.MetaData) -> sa.Table:
    return sa.Table(
        "conversation_spawns",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.String(50), nullable=False),
        # Plain Integer column (no FK in the migration DDL) — matches _0004's pattern so 0005
        # applies standalone/incrementally without needing 'spawns' in this isolated MetaData.
        # The ORM model (ConversationSpawn) keeps the ForeignKey for relationships.
        sa.Column("spawn_id", sa.Integer(), nullable=False),
        sa.Column("joined_via", sa.String(16), nullable=False),
        sa.Column("joined_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("conversation_id", "spawn_id", name="uq_conversation_spawn"),
    )


def _upgrade(bind) -> None:  # noqa: ANN001
    insp = sa.inspect(bind)
    existing = set(insp.get_table_names())
    if "conversation_spawns" not in existing:
        metadata = sa.MetaData()
        tbl = _table_def(metadata)
        tbl.create(bind)
        bind.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_conversation_spawns_conversation_id"
                " ON conversation_spawns (conversation_id)"
            )
        )


def _downgrade(bind) -> None:  # noqa: ANN001
    metadata = sa.MetaData()
    tbl = _table_def(metadata)
    tbl.drop(bind, checkfirst=True)
    bind.execute(
        sa.text(
            "DROP INDEX IF EXISTS ix_conversation_spawns_conversation_id"
        )
    )


# Test helper: apply against a raw (sync) connection.
def upgrade_sync(connection) -> None:  # noqa: ANN001
    _upgrade(connection)


def downgrade_sync(connection) -> None:  # noqa: ANN001
    _downgrade(connection)

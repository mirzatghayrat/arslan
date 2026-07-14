"""knowledge_chunks table + FTS5 virtual table

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-23
"""
from __future__ import annotations

import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _table(metadata: sa.MetaData) -> sa.Table:
    return sa.Table(
        "knowledge_chunks", metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("spawn_id", sa.Integer(), nullable=False, index=True),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["spawn_id"], ["spawns.id"], ondelete="CASCADE"),
    )


def _upgrade(bind) -> None:  # noqa: ANN001
    insp = sa.inspect(bind)
    if "knowledge_chunks" not in set(insp.get_table_names()):
        metadata = sa.MetaData()
        sa.Table("spawns", metadata, sa.Column("id", sa.Integer(), primary_key=True),
                 keep_existing=True)
        _table(metadata).create(bind)
    bind.exec_driver_sql(
        "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(text)"
    )


def _downgrade(bind) -> None:  # noqa: ANN001
    bind.exec_driver_sql("DROP TABLE IF EXISTS knowledge_chunks_fts")
    metadata = sa.MetaData()
    sa.Table("spawns", metadata, sa.Column("id", sa.Integer(), primary_key=True),
             keep_existing=True)
    _table(metadata).drop(bind, checkfirst=True)


def upgrade_sync(connection) -> None:  # noqa: ANN001
    _upgrade(connection)


def downgrade_sync(connection) -> None:  # noqa: ANN001
    _downgrade(connection)

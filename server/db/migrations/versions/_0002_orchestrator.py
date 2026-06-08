"""orchestrator tables + reserved leveling columns

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-08

Both the Alembic CLI path (``upgrade``) and the test/sync path (``upgrade_sync``)
drive the same ``_upgrade(bind)`` body. To keep that body usable without an
established Alembic ``Operations`` proxy (which only exists during a real
migration run), table creation goes through SQLAlchemy ``Table(...).create(bind)``
and column additions through raw ``ALTER TABLE`` statements rather than ``op.*``.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import text
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _table_defs(metadata: sa.MetaData) -> dict[str, sa.Table]:
    """Build the four new orchestrator tables against a throwaway metadata.

    A minimal ``spawns`` stub is registered in the same metadata purely so the
    ``arslan_messages.spawn_id`` foreign key can resolve its target at DDL render
    time. It is never created/dropped here (the real ``spawns`` table is owned by
    migration 0001); only the four new tables are returned.
    """
    sa.Table(
        "spawns",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    arslan_messages = sa.Table(
        "arslan_messages",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.String(length=50), nullable=False, index=True),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("display_content", sa.Text(), nullable=True),
        sa.Column("spawn_id", sa.Integer(), sa.ForeignKey("spawns.id"), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
    )
    arslan_summaries = sa.Table(
        "arslan_summaries",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.String(length=50), nullable=False, index=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("up_to_message_id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    user_facts = sa.Table(
        "user_facts",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=True),
        sa.Column("sensitive", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    router_decisions = sa.Table(
        "router_decisions",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.String(length=50), nullable=False, index=True),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("spawn_id", sa.Integer(), nullable=True),
        sa.Column("task_brief", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
    )
    return {
        "arslan_messages": arslan_messages,
        "arslan_summaries": arslan_summaries,
        "user_facts": user_facts,
        "router_decisions": router_decisions,
    }


def _add_column(bind, table: str, column: sa.Column) -> None:  # noqa: ANN001
    """Render and execute an ``ALTER TABLE ... ADD COLUMN`` for the given bind."""
    ddl_compiler = bind.dialect.ddl_compiler(bind.dialect, None)
    col_spec = ddl_compiler.get_column_specification(column)
    bind.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_spec}"))


def _upgrade(bind) -> None:  # noqa: ANN001
    insp = sa.inspect(bind)
    existing = set(insp.get_table_names())

    metadata = sa.MetaData()
    tables = _table_defs(metadata)
    for name, table in tables.items():
        if name not in existing:
            table.create(bind)

    spawn_cols = {c["name"] for c in insp.get_columns("spawns")}
    if "level" not in spawn_cols:
        _add_column(bind, "spawns", sa.Column("level", sa.Integer(), nullable=True))
    if "memory_facts" not in spawn_cols:
        _add_column(bind, "spawns", sa.Column("memory_facts", sa.JSON(), nullable=True))

    fb_cols = {c["name"] for c in insp.get_columns("feedback")}
    if "quality_signal" not in fb_cols:
        _add_column(bind, "feedback", sa.Column("quality_signal", sa.Integer(), nullable=True))


def _downgrade(bind) -> None:  # noqa: ANN001
    metadata = sa.MetaData()
    tables = _table_defs(metadata)
    for name in ("router_decisions", "user_facts", "arslan_summaries", "arslan_messages"):
        tables[name].drop(bind, checkfirst=True)
    for table, column in (
        ("spawns", "level"),
        ("spawns", "memory_facts"),
        ("feedback", "quality_signal"),
    ):
        bind.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))


def upgrade() -> None:
    _upgrade(op.get_bind())


def downgrade() -> None:
    _downgrade(op.get_bind())


# Test helper: apply against a raw (sync) connection, like _0001_initial.upgrade_sync.
def upgrade_sync(connection) -> None:  # noqa: ANN001
    _upgrade(connection)


def downgrade_sync(connection) -> None:  # noqa: ANN001
    _downgrade(connection)

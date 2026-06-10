"""capability registry tables: toolsets, tools, skill_packs, spawn_capabilities

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-10

Both the Alembic CLI path (``upgrade``) and the test/sync path (``upgrade_sync``)
drive the same ``_upgrade(bind)`` body. To keep that body usable without an
established Alembic ``Operations`` proxy (which only exists during a real
migration run), table creation goes through SQLAlchemy ``Table(...).create(bind)``
guarded by inspector existence checks rather than ``op.*``. This mirrors the
dual-path pattern established in ``_0002_orchestrator.py``.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _table_defs(metadata: sa.MetaData) -> dict[str, sa.Table]:
    """Build the four new capability-registry tables against a throwaway metadata.

    A minimal ``spawns`` stub is registered in the same metadata purely so the
    ``spawn_capabilities.spawn_id`` foreign key can resolve its target at DDL
    render time. It is never created/dropped here (owned by migration 0001);
    only the four new tables are returned.
    """
    sa.Table(
        "spawns",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    toolsets = sa.Table(
        "toolsets",
        metadata,
        sa.Column("key", sa.String(50), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tier", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("backend_note", sa.Text(), nullable=True),
    )
    tools = sa.Table(
        "tools",
        metadata,
        sa.Column("key", sa.String(50), primary_key=True),
        sa.Column(
            "toolset_key",
            sa.String(50),
            sa.ForeignKey("toolsets.key", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tier", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("input_schema", sa.JSON(), nullable=True),
    )
    skill_packs = sa.Table(
        "skill_packs",
        metadata,
        sa.Column("key", sa.String(60), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tier", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
    )
    spawn_capabilities = sa.Table(
        "spawn_capabilities",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "spawn_id",
            sa.Integer(),
            sa.ForeignKey("spawns.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("ref_key", sa.String(60), nullable=False),
        sa.Column("grant", sa.String(10), nullable=False),
        sa.Column("granted_by", sa.String(20), nullable=False),
        sa.Column("expires_turn", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("spawn_id", "kind", "ref_key"),
    )
    return {
        "toolsets": toolsets,
        "tools": tools,
        "skill_packs": skill_packs,
        "spawn_capabilities": spawn_capabilities,
    }


def _upgrade(bind) -> None:  # noqa: ANN001
    insp = sa.inspect(bind)
    existing = set(insp.get_table_names())

    metadata = sa.MetaData()
    tables = _table_defs(metadata)
    # Create in dependency order: toolsets before tools (FK), spawns stub already registered
    for name in ("toolsets", "tools", "skill_packs", "spawn_capabilities"):
        if name not in existing:
            tables[name].create(bind)


def _downgrade(bind) -> None:  # noqa: ANN001
    """Idempotent inverse of ``_upgrade``.

    Tables drop with ``checkfirst`` in reverse dependency order so foreign-key
    constraints are satisfied. A second/partial run is a no-op.
    """
    metadata = sa.MetaData()
    tables = _table_defs(metadata)
    for name in ("spawn_capabilities", "skill_packs", "tools", "toolsets"):
        tables[name].drop(bind, checkfirst=True)


def upgrade() -> None:
    _upgrade(op.get_bind())


def downgrade() -> None:
    _downgrade(op.get_bind())


# Test helper: apply against a raw (sync) connection, like _0001_initial.upgrade_sync.
def upgrade_sync(connection) -> None:  # noqa: ANN001
    _upgrade(connection)


def downgrade_sync(connection) -> None:  # noqa: ANN001
    _downgrade(connection)

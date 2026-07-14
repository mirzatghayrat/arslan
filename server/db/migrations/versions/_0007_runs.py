"""runs / run_steps / run_evaluations + arslan_messages.run_id

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-23
"""
from __future__ import annotations

import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _tables(metadata: sa.MetaData) -> list[sa.Table]:
    # Stub for the pre-existing spawns table so the FK on runs.spawn_id resolves.
    sa.Table("spawns", metadata, sa.Column("id", sa.Integer(), primary_key=True), keep_existing=True)
    runs = sa.Table(
        "runs", metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.String(50), nullable=False, index=True),
        sa.Column("spawn_id", sa.Integer(), nullable=True),
        sa.Column("spawn_name", sa.String(100), nullable=True),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("total_ms", sa.Integer(), nullable=True),
        sa.Column("task_tokens", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("overall_badge", sa.String(10), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["spawn_id"], ["spawns.id"], ondelete="SET NULL"),
    )
    run_steps = sa.Table(
        "run_steps", metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=False, index=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("ref", sa.JSON()),
        sa.Column("detail", sa.JSON()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
    )
    run_evals = sa.Table(
        "run_evaluations", metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=False, index=True),
        sa.Column("dimension", sa.String(20), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
    )
    return [runs, run_steps, run_evals]


def _upgrade(bind) -> None:  # noqa: ANN001
    insp = sa.inspect(bind)
    existing = set(insp.get_table_names())
    metadata = sa.MetaData()
    for tbl in _tables(metadata):
        if tbl.name not in existing:
            tbl.create(bind)
    if "arslan_messages" in existing:
        cols = {c["name"] for c in insp.get_columns("arslan_messages")}
        if "run_id" not in cols:
            bind.execute(sa.text("ALTER TABLE arslan_messages ADD COLUMN run_id INTEGER"))


def _downgrade(bind) -> None:  # noqa: ANN001
    # Note: arslan_messages.run_id is intentionally NOT dropped here (older SQLite
    # lacks DROP COLUMN); downgrade reverts the new tables only.
    metadata = sa.MetaData()
    for tbl in reversed(_tables(metadata)):
        tbl.drop(bind, checkfirst=True)


def upgrade_sync(connection) -> None:  # noqa: ANN001
    _upgrade(connection)


def downgrade_sync(connection) -> None:  # noqa: ANN001
    _downgrade(connection)

"""persona_seeds FTS5 mirror

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def _upgrade(bind) -> None:  # noqa: ANN001
    insp = sa.inspect(bind)
    if "persona_seeds_fts" not in set(insp.get_table_names()):
        bind.exec_driver_sql("CREATE VIRTUAL TABLE persona_seeds_fts USING fts5(text)")


def _downgrade(bind) -> None:  # noqa: ANN001
    bind.exec_driver_sql("DROP TABLE IF EXISTS persona_seeds_fts")


def upgrade() -> None:
    _upgrade(op.get_bind())


def downgrade() -> None:
    _downgrade(op.get_bind())


def upgrade_sync(connection) -> None:  # noqa: ANN001
    _upgrade(connection)


def downgrade_sync(connection) -> None:  # noqa: ANN001
    _downgrade(connection)

"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-08
"""
from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _create_all(bind) -> None:  # noqa: ANN001
    """Create every table using the ORM metadata (single source of truth)."""
    from server.db.models import Base

    Base.metadata.create_all(bind)


def _drop_all(bind) -> None:  # noqa: ANN001
    from server.db.models import Base

    Base.metadata.drop_all(bind)


def upgrade() -> None:
    _create_all(op.get_bind())


def downgrade() -> None:
    _drop_all(op.get_bind())


# Test helper: apply/revert against a raw (sync) connection.
def upgrade_sync(connection) -> None:  # noqa: ANN001
    _create_all(connection)


def downgrade_sync(connection) -> None:  # noqa: ANN001
    _drop_all(connection)

"""0020: add user_facts.label (short LLM-extracted keyword phrase). Nullable.
SQLite 3.35+ supports ADD/DROP COLUMN directly; both guarded by inspect for
idempotency. Reversible: downgrade drops the column, preserving rows/ids."""
from __future__ import annotations

import sqlalchemy as sa

revision = "0020"
down_revision = "0019"


def _cols(bind) -> set[str]:  # noqa: ANN001
    insp = sa.inspect(bind)
    if "user_facts" not in set(insp.get_table_names()):
        return set()
    return {c["name"] for c in insp.get_columns("user_facts")}


def _upgrade(bind) -> None:  # noqa: ANN001
    if "user_facts" in set(sa.inspect(bind).get_table_names()) and "label" not in _cols(bind):
        bind.exec_driver_sql("ALTER TABLE user_facts ADD COLUMN label VARCHAR(40)")


def _downgrade(bind) -> None:  # noqa: ANN001
    if "label" in _cols(bind):
        bind.exec_driver_sql("ALTER TABLE user_facts DROP COLUMN label")


def upgrade_sync(connection) -> None:  # noqa: ANN001
    _upgrade(connection)


def downgrade_sync(connection) -> None:  # noqa: ANN001
    _downgrade(connection)

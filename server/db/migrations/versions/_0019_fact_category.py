"""user_facts.category — semantic category for preferences (nullable).

Forward: ALTER TABLE ADD COLUMN. Downgrade: SQLite 3.35+ supports ALTER TABLE
DROP COLUMN (Python 3.12 bundles 3.4x); we use it directly. Idempotent both ways
via column inspection so the main.py boot backfill can re-run safely."""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def _cols(bind) -> set:  # noqa: ANN001
    insp = sa.inspect(bind)
    if "user_facts" not in set(insp.get_table_names()):
        return set()
    return {c["name"] for c in insp.get_columns("user_facts")}


def _upgrade(bind) -> None:  # noqa: ANN001
    if "user_facts" in set(sa.inspect(bind).get_table_names()) and "category" not in _cols(bind):
        bind.exec_driver_sql("ALTER TABLE user_facts ADD COLUMN category VARCHAR(30)")


def _downgrade(bind) -> None:  # noqa: ANN001
    if "category" in _cols(bind):
        bind.exec_driver_sql("ALTER TABLE user_facts DROP COLUMN category")


def upgrade() -> None:
    _upgrade(op.get_bind())


def downgrade() -> None:
    _downgrade(op.get_bind())


def upgrade_sync(connection) -> None:  # noqa: ANN001
    _upgrade(connection)


def downgrade_sync(connection) -> None:  # noqa: ANN001
    _downgrade(connection)

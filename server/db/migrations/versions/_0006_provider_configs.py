"""provider_configs table + backfill legacy single key

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _table_def(metadata: sa.MetaData) -> sa.Table:
    return sa.Table(
        "provider_configs",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("base_url", sa.String(255), nullable=True),
        sa.Column("api_key", sa.Text(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def _get_setting(bind, key):  # noqa: ANN001
    if "settings" not in set(sa.inspect(bind).get_table_names()):
        return None
    row = bind.execute(sa.text("SELECT value FROM settings WHERE key=:k"), {"k": key}).first()
    return row[0] if row else None


def _set_setting(bind, key, value):  # noqa: ANN001
    if "settings" not in set(sa.inspect(bind).get_table_names()):
        return
    exists = bind.execute(sa.text("SELECT 1 FROM settings WHERE key=:k"), {"k": key}).first()
    if not exists:
        bind.execute(sa.text("INSERT INTO settings (key, value) VALUES (:k, :v)"), {"k": key, "v": value})


def _upgrade(bind) -> None:  # noqa: ANN001
    insp = sa.inspect(bind)
    if "provider_configs" not in set(insp.get_table_names()):
        metadata = sa.MetaData()
        tbl = _table_def(metadata)
        tbl.create(bind)
    count = bind.execute(sa.text("SELECT COUNT(*) FROM provider_configs")).scalar_one()
    enc_key = _get_setting(bind, "llm_api_key")
    if count == 0 and enc_key:
        provider = _get_setting(bind, "llm_provider") or "openai"
        model = _get_setting(bind, "llm_model") or ""
        base_url = _get_setting(bind, "llm_base_url") or ""
        bind.execute(
            sa.text(
                "INSERT INTO provider_configs "
                "(label, provider, model, base_url, api_key, is_primary, created_at) "
                "VALUES (:l, :p, :m, :b, :k, :pr, CURRENT_TIMESTAMP)"
            ),
            {"l": provider, "p": provider, "m": model, "b": base_url, "k": enc_key, "pr": True},
        )
    _set_setting(bind, "llm_strategy", "single")


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

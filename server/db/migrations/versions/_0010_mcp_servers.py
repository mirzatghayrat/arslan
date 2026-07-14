"""mcp_servers table + tools.external_name column."""
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"


def _upgrade(bind) -> None:
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "mcp_servers" not in tables:
        sa.Table(
            "mcp_servers", sa.MetaData(),
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("label", sa.String(80), nullable=False),
            sa.Column("transport", sa.String(20), nullable=False, server_default="stdio"),
            sa.Column("command", sa.String(255), nullable=False),
            sa.Column("args", sa.JSON(), nullable=False),
            sa.Column("env", sa.Text(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="registered"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        ).create(bind)
    if "tools" in tables:
        cols = {c["name"] for c in insp.get_columns("tools")}
        if "external_name" not in cols:
            bind.exec_driver_sql("ALTER TABLE tools ADD COLUMN external_name VARCHAR(120)")


def upgrade_sync(connection) -> None:
    _upgrade(connection)


def downgrade_sync(connection) -> None:
    pass

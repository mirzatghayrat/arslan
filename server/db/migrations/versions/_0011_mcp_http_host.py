"""tools.host_enabled + mcp_servers.url columns."""
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"


def _upgrade(bind) -> None:
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if "tools" in tables:
        cols = {c["name"] for c in insp.get_columns("tools")}
        if "host_enabled" not in cols:
            bind.exec_driver_sql("ALTER TABLE tools ADD COLUMN host_enabled BOOLEAN NOT NULL DEFAULT 0")
    if "mcp_servers" in tables:
        cols = {c["name"] for c in insp.get_columns("mcp_servers")}
        if "url" not in cols:
            bind.exec_driver_sql("ALTER TABLE mcp_servers ADD COLUMN url VARCHAR(500)")


def upgrade_sync(connection) -> None:
    _upgrade(connection)


def downgrade_sync(connection) -> None:
    pass

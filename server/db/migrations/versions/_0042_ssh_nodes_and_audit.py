"""0042: ssh_nodes + ssh_audit — enrolled machines, and a record of what was done to them.

P3c. Two tables, and the second one exists because a comfortable assumption did
not survive checking: the P3 spec said remote actions would be visible in the
trace, but `ssh_run` is an Arslan-level tool and the answer path produces no Run
row, so its tool trace lives in the in-memory turn journal and is dropped when
the turn ends. Nothing durable recorded it. Hence a real table.

`ssh_audit.node_id` is deliberately NOT a foreign key: revoking a machine must
not delete the history of what was run on it, and a FK with any ondelete rule
would either erase it or block the revocation.
"""
from __future__ import annotations


def _tables(connection) -> set[str]:
    return {r[0] for r in connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def upgrade_sync(connection) -> None:
    existing = _tables(connection)
    if "ssh_nodes" not in existing:
        connection.exec_driver_sql(
            "CREATE TABLE ssh_nodes ("
            " id INTEGER NOT NULL PRIMARY KEY,"
            " name VARCHAR(60) NOT NULL UNIQUE,"
            " host VARCHAR(45) NOT NULL,"
            " username VARCHAR(32) NOT NULL,"
            " host_keys TEXT NOT NULL,"
            " fingerprints TEXT,"
            " created_at DATETIME,"
            " last_used_at DATETIME)")
    if "ssh_audit" not in existing:
        connection.exec_driver_sql(
            "CREATE TABLE ssh_audit ("
            " id INTEGER NOT NULL PRIMARY KEY,"
            " created_at DATETIME,"
            " node_id INTEGER,"
            " node_name VARCHAR(60),"
            " host VARCHAR(45) NOT NULL,"
            " username VARCHAR(32) NOT NULL,"
            " command TEXT NOT NULL,"
            " exit_code INTEGER,"
            " ok BOOLEAN NOT NULL DEFAULT 0,"
            " error TEXT,"
            " conversation_id VARCHAR(50))")
        connection.exec_driver_sql(
            "CREATE INDEX ix_ssh_audit_created_at ON ssh_audit (created_at)")


def downgrade_sync(connection) -> None:
    """Dropping these would destroy the record of what ran where. Leaving them is
    harmless — older code never reads them."""
    return

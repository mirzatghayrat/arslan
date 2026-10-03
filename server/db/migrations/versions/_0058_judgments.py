"""0058: the judgment ledger (0.1.52 S2).

One row per small decision the judge model was asked about (should this card be
asked, is this worth remembering, ...), with the verdict, how sure it was, how long
it took, the mode it ran in (shadow decisions only record), and — filled in later —
what actually happened (the user's real choice on the card). Bounded by
judgment.prune (age and row caps). Idempotent; fresh databases get the same shape
from Base.metadata.create_all.
"""
from __future__ import annotations

_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS judgments (
        id INTEGER NOT NULL PRIMARY KEY,
        point VARCHAR(40) NOT NULL,
        mode VARCHAR(10) NOT NULL,
        state JSON NOT NULL,
        state_hash VARCHAR(64) NOT NULL,
        verdict BOOLEAN,
        probability FLOAT,
        latency_ms INTEGER,
        model VARCHAR(80),
        error VARCHAR(40),
        ref VARCHAR(80),
        conversation_id VARCHAR(50),
        outcome VARCHAR(20),
        outcome_at DATETIME,
        created_at DATETIME NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_judgments_point_created ON judgments (point, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_judgments_ref ON judgments (ref)",
)


def upgrade_sync(connection) -> None:
    for statement in _STATEMENTS:
        connection.exec_driver_sql(statement)


def downgrade_sync(connection) -> None:
    connection.exec_driver_sql("DROP TABLE IF EXISTS judgments")

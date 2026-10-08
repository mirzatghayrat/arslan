"""0064: capabilities that grow (0.1.57 §5.4).

Two tables — the dossier of each capability Arslan proposed or installed
(`capability_sources`) and what it found for later (`capability_finds`) — and two nullable
columns: `mcp_servers.sandbox` (the seatbelt profile an installed server starts under; NULL
for every existing server, which therefore starts exactly as before) and
`skill_packs.source_id`. No CHECK on an existing table changes, so no table is rebuilt.
Idempotent; fresh databases get all of it from Base.metadata.create_all.
"""
from __future__ import annotations


def _columns(connection, table: str) -> set[str]:
    return {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")}


def upgrade_sync(connection) -> None:
    if "sandbox" not in _columns(connection, "mcp_servers"):
        connection.exec_driver_sql("ALTER TABLE mcp_servers ADD COLUMN sandbox JSON")
    if "source_id" not in _columns(connection, "skill_packs"):
        connection.exec_driver_sql("ALTER TABLE skill_packs ADD COLUMN source_id VARCHAR(36)")
    connection.exec_driver_sql("""
    CREATE TABLE IF NOT EXISTS capability_sources (
        id VARCHAR(36) NOT NULL PRIMARY KEY,
        owner_id VARCHAR(100) NOT NULL DEFAULT 'local',
        kind VARCHAR(10) NOT NULL,
        name VARCHAR(120) NOT NULL,
        candidate_id VARCHAR(300) NOT NULL,
        source_url VARCHAR(500), repo VARCHAR(200), version VARCHAR(80), commit_sha VARCHAR(64),
        artifact_sha256 VARCHAR(64), lock_sha256 VARCHAR(64),
        license_spdx VARCHAR(40), license_path VARCHAR(300),
        stars INTEGER, pushed_days INTEGER, checked_at DATETIME,
        runtime VARCHAR(10), needs JSON NOT NULL, grants JSON NOT NULL,
        scan JSON, test JSON, files JSON,
        state VARCHAR(12) NOT NULL DEFAULT 'proposed', error TEXT,
        mcp_server_id INTEGER, skill_key VARCHAR(60),
        created_at DATETIME NOT NULL, installed_at DATETIME,
        CONSTRAINT ck_capability_source_kind CHECK (kind IN ('mcp','skill')),
        CONSTRAINT ck_capability_source_state CHECK (state IN ('proposed','installed','failed','removed'))
    )""")
    connection.exec_driver_sql("""
    CREATE TABLE IF NOT EXISTS capability_finds (
        id VARCHAR(36) NOT NULL PRIMARY KEY,
        owner_id VARCHAR(100) NOT NULL DEFAULT 'local',
        need VARCHAR(300) NOT NULL,
        why VARCHAR(16) NOT NULL,
        conversation_id VARCHAR(50), project_id VARCHAR(36), level_id VARCHAR(36),
        candidate JSON NOT NULL,
        state VARCHAR(10) NOT NULL DEFAULT 'open',
        created_at DATETIME NOT NULL,
        CONSTRAINT ck_capability_find_why CHECK (why IN ('declined','job','project_level')),
        CONSTRAINT ck_capability_find_state CHECK (state IN ('open','dismissed','installed'))
    )""")
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_capability_finds_created_at ON capability_finds (created_at)")


def downgrade_sync(connection) -> None:
    connection.exec_driver_sql("DROP TABLE IF EXISTS capability_finds")
    connection.exec_driver_sql("DROP TABLE IF EXISTS capability_sources")

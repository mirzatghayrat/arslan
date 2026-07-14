"""0031: Provider-P2 dynamic model catalog — model_catalog_cache table +
provider_configs health columns.

model_catalog_cache holds one row per provider config: the JSON array of models
fetched from the provider's list-models API, stamped with a fingerprint of
(provider, base_url, api_key) so editing the config invalidates the cache.
last_health / last_health_at on provider_configs are consumed by P4 (health probe).

Idempotency (this repo re-applies every migration on every boot): CREATE TABLE/INDEX
use IF NOT EXISTS and the ALTERs are guarded by PRAGMA table_info, so a second run
is a no-op. Fresh DBs get the final shape from Base.metadata.create_all (the
ModelCatalogCache / ProviderConfig ORM models), so the guards simply find
everything already present.

Revision ID: 0031
Revises: 0030
Create Date: 2026-07-12
"""
from __future__ import annotations

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None

_MODEL_CATALOG_CACHE_DDL = (
    "CREATE TABLE IF NOT EXISTS model_catalog_cache ("
    "id INTEGER PRIMARY KEY, "
    "provider_config_id INTEGER NOT NULL UNIQUE "
    "REFERENCES provider_configs(id) ON DELETE CASCADE, "
    "fingerprint VARCHAR(40) NOT NULL, "
    "fetched_at DATETIME NOT NULL, "
    "models TEXT NOT NULL)"
)

_PROVIDER_CONFIG_COLUMNS = [
    ("last_health", "VARCHAR(20)"),
    ("last_health_at", "DATETIME"),
]


def _upgrade(connection) -> None:  # noqa: ANN001
    connection.exec_driver_sql(_MODEL_CATALOG_CACHE_DDL)
    existing = {row[1] for row in
                connection.exec_driver_sql("PRAGMA table_info(provider_configs)")}
    for name, ddl in _PROVIDER_CONFIG_COLUMNS:
        if name not in existing:
            connection.exec_driver_sql(
                f"ALTER TABLE provider_configs ADD COLUMN {name} {ddl}")


def _downgrade(connection) -> None:  # noqa: ANN001
    connection.exec_driver_sql("DROP TABLE IF EXISTS model_catalog_cache")
    # SQLite pre-3.35 cannot DROP COLUMN; best-effort for newer versions.
    for name, _ in _PROVIDER_CONFIG_COLUMNS:
        try:
            connection.exec_driver_sql(
                f"ALTER TABLE provider_configs DROP COLUMN {name}")
        except Exception:  # noqa: BLE001 — downgrade is best-effort on old SQLite
            pass


def upgrade_sync(connection) -> None:  # noqa: ANN001
    _upgrade(connection)


def downgrade_sync(connection) -> None:  # noqa: ANN001
    _downgrade(connection)

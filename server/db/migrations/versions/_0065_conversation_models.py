"""0065: a model chosen for one conversation (0.1.58 §6).

One small table — conversation → (provider config, model id) — so a conversation can run on
any model its provider offers (all of OpenRouter's included) without touching the global
default. A deleted provider config deletes its choices (ON DELETE CASCADE); the conversation
then runs on the default again. No existing table changes. Idempotent; fresh databases get it
from Base.metadata.create_all.
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    connection.exec_driver_sql("""
    CREATE TABLE IF NOT EXISTS conversation_models (
        conversation_id VARCHAR(100) NOT NULL PRIMARY KEY,
        config_id INTEGER NOT NULL REFERENCES provider_configs (id) ON DELETE CASCADE,
        model VARCHAR(200) NOT NULL,
        updated_at DATETIME NOT NULL
    )""")


def downgrade_sync(connection) -> None:
    connection.exec_driver_sql("DROP TABLE IF EXISTS conversation_models")

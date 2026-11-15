"""0046: immutable recipe versions and durable execution checkpoints.

v0.1.64 C7c-5b deleted the two models (nothing reads or writes them), so the tables are defined here as the
models' create_all made them, byte for byte (same columns, keys, constraints and index), the 0052 way.
C7c-5c's migration drops them, so a new install creates them here and drops them later in the same boot.
"""


def _create(name: str, *lines: str) -> str:
    # create_all's layout: one tab-indented line per column or constraint, joined by ", \n".
    return f"CREATE TABLE IF NOT EXISTS {name} (\n\t" + ", \n\t".join(lines) + "\n)"


_TABLES = (
    _create("recipe_versions",
            "id INTEGER NOT NULL", '"key" VARCHAR(60) NOT NULL', "version INTEGER NOT NULL",
            "name VARCHAR(100) NOT NULL", "spec JSON NOT NULL", "created_at DATETIME", "PRIMARY KEY (id)",
            'UNIQUE ("key", version)'),
    'CREATE INDEX IF NOT EXISTS ix_recipe_versions_key ON recipe_versions ("key")',
    _create("recipe_executions",
            "id INTEGER NOT NULL", "request_key VARCHAR(80) NOT NULL", "recipe_id INTEGER NOT NULL",
            "input TEXT NOT NULL", "status VARCHAR(30) NOT NULL", "checkpoint JSON NOT NULL", "run_id INTEGER",
            "error TEXT", "created_at DATETIME", "updated_at DATETIME", "PRIMARY KEY (id)", "UNIQUE (request_key)",
            "FOREIGN KEY(recipe_id) REFERENCES recipe_versions (id)"),
)


def upgrade_sync(connection):
    for statement in _TABLES:
        connection.exec_driver_sql(statement)

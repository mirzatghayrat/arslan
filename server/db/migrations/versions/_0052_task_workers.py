"""0052: versioned methods and ephemeral, task-owned collaboration records.

v0.1.64 SUB6 deleted the helpers and the table's model, so the table is defined here, as the model's
create_all made it (same columns, keys, constraints and index). Nothing reads or writes it any more;
SUB7's migration drops it.

v0.1.64 SUB6b deleted the professional methods and their two models, so their tables are defined here the
same way (as the models' create_all made them). Nothing reads or writes them any more; 0096 drops them, so
a new install creates them here and drops them later in the same boot.
"""

_METHODS = (
    """CREATE TABLE IF NOT EXISTS professional_methods (
        "key" VARCHAR(40) NOT NULL,
        current_revision INTEGER NOT NULL,
        PRIMARY KEY ("key")
    )""",
    """CREATE TABLE IF NOT EXISTS professional_method_versions (
        "key" VARCHAR(40) NOT NULL,
        revision INTEGER NOT NULL,
        name VARCHAR(120) NOT NULL,
        instructions TEXT NOT NULL,
        created_at DATETIME NOT NULL,
        PRIMARY KEY ("key", revision),
        FOREIGN KEY("key") REFERENCES professional_methods ("key")
    )""",
)

_TASK_WORKERS = (
    """CREATE TABLE IF NOT EXISTS task_workers (
        id VARCHAR(36) NOT NULL,
        task_id VARCHAR(200) NOT NULL,
        attempt_id VARCHAR(36) NOT NULL,
        spec_revision INTEGER NOT NULL,
        method_key VARCHAR(40) NOT NULL,
        method_revision INTEGER NOT NULL,
        fingerprint VARCHAR(64) NOT NULL,
        brief JSON NOT NULL,
        status VARCHAR(20) NOT NULL,
        run_id INTEGER,
        result JSON,
        progress JSON NOT NULL,
        created_at DATETIME NOT NULL,
        ended_at DATETIME,
        PRIMARY KEY (id),
        CONSTRAINT uq_task_worker_request UNIQUE (task_id, spec_revision, fingerprint, attempt_id),
        CONSTRAINT ck_task_worker_status CHECK (status IN """
    """('queued','running','completed','partial','failed','cancelled','interrupted')),
        FOREIGN KEY(task_id) REFERENCES companion_tasks (id) ON DELETE CASCADE,
        FOREIGN KEY(attempt_id) REFERENCES task_attempts (id),
        FOREIGN KEY(run_id) REFERENCES runs (id)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_task_workers_task_id ON task_workers (task_id)",
)


def upgrade_sync(connection):
    for statement in (*_METHODS, *_TASK_WORKERS):
        connection.exec_driver_sql(statement)

"""0055: a background job's result message remembers its outcome (0.1.42).

The live `message` frame carries the job's checked outcome; without a column the
label ("Background work result · Done") vanished on the next reload. Adds one
nullable column; existing rows are not touched.
"""
import sqlalchemy as sa


def upgrade_sync(connection):
    columns = {row[1] for row in connection.execute(sa.text("PRAGMA table_info(arslan_messages)"))}
    if "job_outcome" not in columns:
        connection.execute(sa.text("ALTER TABLE arslan_messages ADD COLUMN job_outcome VARCHAR(20)"))

"""0043: last_health_detail, and a reset of the old health vocabulary.

The column stops meaning "did /models list anything" and starts meaning "can
this LLM answer a message". Those are different questions with different words,
so the rows carrying the old words are cleared rather than translated: there is
no honest mapping from "reachable_models" to "ok" — a public model-list endpoint
answers with no key at all, which is exactly why the old signal was replaced.
NULL reads as "never tested", the app tests on launch, and the row refills with
a verdict that means something.

last_health_detail carries the human-readable reason for a failure so it
survives a remount; a bare "failed" is only marginally better than a lie.

🔴 SHIPPED BROKEN in v0.1.33. Every statement here named ``provider_config``;
the table is ``provider_configs``. The guard on the first line therefore always
matched "table absent" and returned, so this migration did NOTHING while
apply_pending recorded it as applied — a silent no-op that looks identical to
success. Fixed here for any database that has not recorded 0043 yet; 0044
repairs the ones that already have. A fresh install never noticed, because
create_all builds the modern table straight from the model and no migration is
involved: only an UPGRADE could see it.
"""
from __future__ import annotations


def _columns(connection, table: str) -> set[str]:
    return {r[1] for r in connection.exec_driver_sql(f"PRAGMA table_info({table})")}


def upgrade_sync(connection) -> None:
    if "provider_configs" not in {r[0] for r in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'")}:
        return
    if "last_health_detail" not in _columns(connection, "provider_configs"):
        connection.exec_driver_sql(
            "ALTER TABLE provider_configs ADD COLUMN last_health_detail TEXT")
    # Old vocabulary → "never tested". Not a translation: the old words answered
    # a question this column no longer asks.
    connection.exec_driver_sql(
        "UPDATE provider_configs SET last_health = NULL, last_health_at = NULL "
        "WHERE last_health IN ('reachable_models','reachable_no_list','unreachable')")

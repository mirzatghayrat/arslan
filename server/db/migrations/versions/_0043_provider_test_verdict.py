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
"""
from __future__ import annotations


def _columns(connection, table: str) -> set[str]:
    return {r[1] for r in connection.exec_driver_sql(f"PRAGMA table_info({table})")}


def upgrade_sync(connection) -> None:
    if "provider_config" not in {r[0] for r in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'")}:
        return
    if "last_health_detail" not in _columns(connection, "provider_config"):
        connection.exec_driver_sql(
            "ALTER TABLE provider_config ADD COLUMN last_health_detail TEXT")
    # Old vocabulary → "never tested". Not a translation: the old words answered
    # a question this column no longer asks.
    connection.exec_driver_sql(
        "UPDATE provider_config SET last_health = NULL, last_health_at = NULL "
        "WHERE last_health IN ('reachable_models','reachable_no_list','unreachable')")

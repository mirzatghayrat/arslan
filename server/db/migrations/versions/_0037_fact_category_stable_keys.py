"""0037: user_facts.category — legacy Chinese display strings → stable keys.

Until S4.2-d, fact_classify.py stored the DISPLAY string ("身份背景", …) as the
category value, so the persisted data itself was Chinese and a non-Chinese UI
showed Chinese no matter what the language setting said. The category is now a
stable machine key (identity / communication / interest / task / spawn_wish /
other) that the frontend translates.

Mapping (user-approved fail-open decision):

  known Chinese value → its key   (exact 1:1)
  already a stable key → untouched (this repo re-applies migrations every boot)
  unknown non-blank    → 'other'   (fail-open: never invent a meaning, never lose
                                    the row from category-grouped views)
  NULL / ''            → untouched (means "not yet classified" — those rows belong
                                    to the label-IS-NULL backfill, not to us)

Downgrade restores the six Chinese strings; rows that upgrade fail-opened from
junk come back as 其他 (documented loss, asserted in test_migration_0037).
"""
from __future__ import annotations

LEGACY_TO_KEY = {
    "身份背景": "identity",
    "沟通偏好": "communication",
    "领域兴趣": "interest",
    "任务需求": "task",
    "想建的分身": "spawn_wish",
    "其他": "other",
}
_KEYS = tuple(LEGACY_TO_KEY.values())


def _has_table(connection) -> bool:
    return connection.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='user_facts'"
    ).first() is not None


def upgrade_sync(connection) -> None:
    if not _has_table(connection):
        return
    for legacy, key in LEGACY_TO_KEY.items():
        connection.exec_driver_sql(
            "UPDATE user_facts SET category = ? WHERE category = ?", (key, legacy))
    # Fail-open sweep for anything else non-blank that is not already a key.
    placeholders = ",".join("?" for _ in _KEYS)
    connection.exec_driver_sql(
        f"UPDATE user_facts SET category = 'other' "
        f"WHERE category IS NOT NULL AND category != '' "
        f"AND category NOT IN ({placeholders})",
        _KEYS)


def downgrade_sync(connection) -> None:
    if not _has_table(connection):
        return
    for legacy, key in LEGACY_TO_KEY.items():
        connection.exec_driver_sql(
            "UPDATE user_facts SET category = ? WHERE category = ?", (legacy, key))

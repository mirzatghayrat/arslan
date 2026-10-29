"""0077: skills promoted from Skill Forge get the "authored" mark, then `skill_candidates` goes (v0.1.64 CAP2b).

CAP2a removed the Skill Forge page, the curator and every candidate function; the create_skill card and
expert_conversion write the skill itself, marked "authored" (skill_forge.register). Before CAP2a a skill
Arslan wrote went live through a candidate, and the seeder told it from its own rows by that candidate's
promoted_at (D7, plan v0.1.63). That row now gets the same mark, so the seeder drops the candidate clause
and still never retires it.

Only rows that do not already say where they came from are marked: a promoted candidate's key can since
have gone to another skill (deleted, then imported or installed under that name), and that row keeps its
own mark, so an imported skill stays framed as outside text. The marks are written out here, not imported
from skill_forge, so this migration stays what it was when it ran.

The candidates themselves were drafts, not the user's skills; they stay in the upgrade backup the runner
takes before any migration (`prepare_upgrade_backup`). Its own PR after the code, so reverting CAP2a never
needs the table back (plan §6).

Idempotent: a database without the table (a second run) is left alone. 0017 still creates the table, empty,
on a new install; this then drops it.
"""
from __future__ import annotations


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
    if "skill_candidates" not in tables:
        return
    connection.exec_driver_sql(
        "UPDATE skill_packs SET category = 'authored'"
        " WHERE key IN (SELECT key FROM skill_candidates WHERE promoted_at IS NOT NULL)"
        " AND category NOT IN ('imported', 'authored', 'authored-outside') AND source_id IS NULL")
    connection.exec_driver_sql("DROP TABLE skill_candidates")


def downgrade_sync(connection) -> None:
    """Nothing to restore: no code reads the table, and its rows are in the upgrade backup."""
    return

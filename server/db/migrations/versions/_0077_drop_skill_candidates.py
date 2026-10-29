"""0077: skills promoted from Skill Forge get a mark of where their text came from, then `skill_candidates`
goes (v0.1.64 CAP2b).

CAP2a removed the Skill Forge page, the curator and every candidate function; the create_skill card and
expert_conversion write the skill itself, marked "authored" or "authored-outside" (skill_forge.register).
Before CAP2a a skill went live through a candidate, and the seeder told it from its own rows by that
candidate's promoted_at (D7, plan v0.1.63). That row now gets one of the same marks, so the seeder drops
the candidate clause and still never retires it.

Which mark, by the candidate's source (the user's decision on #496: split by source):
- "expert" (expert_conversion: a former expert's own prompt) -> "authored";
- anything else -> "authored-outside", framed like an imported skill. Before CAP2a the model's create_skill
  could write a candidate in any turn, a scheduled run or one that had read a page included, with no card,
  and Promote never showed the body. The Forge page's own form wrote the same source ("skill_creator"), so
  what the user typed there cannot be told apart and is marked the same.
A key whose promoted candidates include both gets "authored-outside".

Only rows that do not already say where they came from are marked: a promoted candidate's key can since
have gone to another skill (deleted, then imported, installed or saved on the card under that name), and
that row keeps its own mark. The marks are written out here, not imported from skill_forge, so this
migration stays what it was when it ran.

The candidates themselves were drafts. They are in the upgrade backup the runner takes before this
migration (`prepare_upgrade_backup`) until that backup is pruned: only the newest three are kept
(`upgrade_backup.py`). After that a candidate's source is gone, which is why the split is made here, not
later. Its own PR after the code, so reverting CAP2a never needs the table back (plan §6).

Idempotent: a database without the table (a second run) is left alone. 0017 still creates the table, empty,
on a new install; this then drops it.
"""
from __future__ import annotations

_UNMARKED = " AND category NOT IN ('imported', 'authored', 'authored-outside') AND source_id IS NULL"


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
    if "skill_candidates" not in tables:
        return
    # Outside first, so a key with both kinds of promoted candidate ends up outside.
    connection.exec_driver_sql(
        "UPDATE skill_packs SET category = 'authored-outside' WHERE key IN (SELECT key FROM skill_candidates"
        " WHERE promoted_at IS NOT NULL AND source IS NOT 'expert')" + _UNMARKED)
    connection.exec_driver_sql(
        "UPDATE skill_packs SET category = 'authored' WHERE key IN (SELECT key FROM skill_candidates"
        " WHERE promoted_at IS NOT NULL AND source = 'expert')" + _UNMARKED)
    connection.exec_driver_sql("DROP TABLE skill_candidates")


def downgrade_sync(connection) -> None:
    """Nothing to restore: no code reads the table, and its rows are in the upgrade backup while it is kept."""
    return

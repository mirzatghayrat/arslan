"""0080: skills the old Discover page made get an outside mark (v0.1.64, CAP's gh- follow-up).

Discover (discovery_service.create_skill, removed in CAP1a) had the model draft a skill from a GitHub repo's
README and saved it under "gh-<owner>-<repo>", with whatever category the draft named. The text is
third-party by origin, yet nothing marked it: read_skill handed it over like one of Arslan's own, and the
skill index carried its name and description in every request. Each "gh-" row not already marked outside
("imported" or "authored-outside") gets one of the marks read_skill, the skill index and the seeder (D7)
already read, by whether it has a source_id:
- none -> "authored-outside": the model's draft of a README. Read like an imported skill, but with no attached
  files served: read_skill serves references/ only for "imported", Discover never stored any, and a folder
  under such a key is a removed or failed import's leftover (#502 review 1). This includes a key 0077 marked
  "authored" (a former expert's promoted candidate under it): Discover's create_skill overwrote any row under
  its key, so its text may be Discover's, and unknown counts as outside. 0077 marks only rows without a
  source_id, so every row it marked is in this group.
- a source_id -> "imported": a skill a card installed (skill_import, then capability_flow) whose row Discover
  overwrote, its category too. This gives back the card's mark.
Each row ends framed and listed by key alone; it drops nothing. One thing opens again: a card's row, once more
"imported", has its own scanned files served by read_skill, framed, as before Discover overwrote it (#502
recheck). The draft's own category is lost; nothing reads it since CAP3a's one list.

Every non-seed "gh-" row came from Discover, apart from a skill imported or saved on the create_skill card
under such a name: those are already marked outside, or "authored" since 0.1.64 (CAP2a), which no upgrading
install has before this runs. No seed or retired key starts with "gh-" (tested). The marks are written out
here, not imported from skill_forge, so this migration stays what it was when it ran. It is listed after 0077;
either order ends the same, because 0077 marks only rows still unmarked (tested).

Idempotent: a second run finds every "gh-" row marked outside. A database without skill_packs is left alone.
"""
from __future__ import annotations

_UNMARKED_DISCOVER = "substr(key, 1, 3) = 'gh-' AND coalesce(category, '') NOT IN ('imported', 'authored-outside')"


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
    if "skill_packs" not in tables:
        return
    connection.exec_driver_sql(
        f"UPDATE skill_packs SET category = 'authored-outside' WHERE {_UNMARKED_DISCOVER} AND source_id IS NULL")
    connection.exec_driver_sql(
        f"UPDATE skill_packs SET category = 'imported' WHERE {_UNMARKED_DISCOVER} AND source_id IS NOT NULL")


def downgrade_sync(connection) -> None:
    """Nothing to restore: the earlier categories only made these rows read as Arslan's own, and they are in
    the upgrade backup the runner takes before this migration while it is kept."""
    return

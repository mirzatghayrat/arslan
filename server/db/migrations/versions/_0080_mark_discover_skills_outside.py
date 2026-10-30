"""0080: skills the old Discover page made get the outside mark (v0.1.64, CAP's gh- follow-up).

Discover (discovery_service.create_skill, removed in CAP1a) had the model draft a skill from a GitHub repo's
README and saved it under "gh-<owner>-<repo>", with whatever category the draft named. The text is
third-party by origin, yet nothing marked it: read_skill handed it over like one of Arslan's own, and the
skill index carried its name and description in every request. The mark it gets is the one read_skill,
the skill index and the seeder (D7) already read:
- an "authored" row -> "authored-outside". Discover's create_skill overwrote any row under its key, so a key
  0077 marked "authored" (a former expert's promoted candidate under it) may hold Discover's text. Which
  wrote last is unknown, and unknown counts as outside. That is why this runs after 0077.
- any other row not marked outside ("imported" or "authored-outside") -> "imported", framed like a skill
  pasted as a link. That includes a row with a source_id: an overwrite replaced its "imported" too.
It only makes reading stricter. The draft's own category is lost; nothing reads it since CAP3a's one list.

Every non-seed "gh-" row came from Discover, apart from a skill imported or saved on the create_skill card
under such a name: those are already marked outside, or "authored" since 0.1.64 (CAP2a), which no upgrading
install has before this runs. No seed key starts with "gh-" (tested). The marks are written out here, not
imported from skill_forge, so this migration stays what it was when it ran.

Idempotent: a second run finds every "gh-" row marked outside. A database without skill_packs is left alone.
"""
from __future__ import annotations

_DISCOVER = "substr(key, 1, 3) = 'gh-'"


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
    if "skill_packs" not in tables:
        return
    # "authored" first: the next statement would make it "imported".
    connection.exec_driver_sql(
        f"UPDATE skill_packs SET category = 'authored-outside' WHERE {_DISCOVER} AND category = 'authored'")
    connection.exec_driver_sql(
        f"UPDATE skill_packs SET category = 'imported' WHERE {_DISCOVER}"
        " AND coalesce(category, '') NOT IN ('imported', 'authored-outside')")


def downgrade_sync(connection) -> None:
    """Nothing to restore: the earlier categories only made these rows read as Arslan's own, and they are in
    the upgrade backup the runner takes before this migration while it is kept."""
    return

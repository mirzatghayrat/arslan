"""Which skills read as Arslan's own (v0.1.64 SKF1, docs/plans/0164/CAPX-followups.md): an allowlist, in one
place. read_skill (whether a skill is framed as outside content), the skill index (whether it is listed by key
alone) and the Capabilities list (whether it shows as built in) all ask `reads_as_own`.

Only two kinds of row read unframed:
- a seed row: a key in seed_catalog.SKILLS with none of D7's user marks (seeder._USERS_SKILL). The seeder
  upserts each of those keys at every boot, and no other writer takes an existing key;
- a skill Arslan wrote and the user kept: category "authored", with no capability source.
Everything else is framed: "imported", "authored-outside", a row with a source_id, and any category no writer
marks, an empty or unknown one included. Before SKF1 the readers framed only "imported" and "authored-outside",
so a row no writer marked read as Arslan's own; that is how the old Discover page's skills got through until
migration 0080 marked them. A future source can't.
"""
from __future__ import annotations

from server.registry.seed_catalog import SKILLS
from server.services.skill_forge import AUTHORED, WRITTEN

SEEDED = frozenset(key for key, *_ in SKILLS)
#: D7's user marks on the category (seeder._USERS_SKILL also counts a source_id).
_USER_CATEGORIES = ("imported", *WRITTEN)


def reads_as_own(pack) -> bool:
    """Whether a skill row reads as Arslan's own: a seed row, or one Arslan wrote. Anything else is outside."""
    if pack.source_id:
        return False
    if pack.category == AUTHORED:
        return True
    return pack.key in SEEDED and pack.category not in _USER_CATEGORIES

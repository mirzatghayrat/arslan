"""How skills are trusted, in one place (v0.1.64 SKF1, docs/plans/0164/CAPX-followups.md).

The user's decision D2(1), 2026-10-30: skills follow mainstream practice. Every skill the user has, from any
source, is trusted and read unframed, as Claude Code and Codex treat installed skills. read_skill frames no skill
and marks no turn for reading one, and the skill index lists every skill with its name and description; both ask
`reads_as_own`, which says yes for every skill.

The stated limit: this is the same trust model as MCP tool descriptions from approved servers (the user,
2026-10-29), which also reach the model unmarked. What protects the user is the gate before a skill comes in (the
install card, its pinned commit and scan, CAP4), not a frame at reading time. If that proves too loose, the place
to narrow it is `reads_as_own`, and only by the user's decision.

Where a skill came from stays as data, for deletion and display: D7's user marks (`USER_CATEGORIES`,
`has_users_mark`, from which seeder._USERS_SKILL is built) and `is_seed` (what the Capabilities list shows as
built in).
"""
from __future__ import annotations

from server.registry.seed_catalog import SKILLS
from server.services.skill_forge import WRITTEN

SEEDED = frozenset(key for key, *_ in SKILLS)
#: D7's user marks, in one place (#519 review): a category one of these, or a capability source. seeder._USERS_SKILL
#: is built from them; `has_users_mark` is the same rule on a row.
USER_CATEGORIES = ("imported", *WRITTEN)


def has_users_mark(pack) -> bool:
    """One of D7's user marks: the user brought this skill in, whatever its key. A source is any source_id that
    is not NULL, as D7 counts it."""
    return pack.source_id is not None or pack.category in USER_CATEGORIES


def is_seed(pack) -> bool:
    """A row the seeder planted: a key in seed_catalog.SKILLS with none of D7's user marks. The seeder upserts each
    of those keys at every boot, and no other writer takes an existing key."""
    return pack.key in SEEDED and not has_users_mark(pack)


def reads_as_own(pack) -> bool:
    """Whether a skill reads unframed, as Arslan's own: every skill does (D2(1); the limit is in the module's
    docstring)."""
    return True

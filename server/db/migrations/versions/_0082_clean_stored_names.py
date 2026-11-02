"""0082: names stored before UNI1 go through the name rule once (v0.1.64 UNI1a, #526 review).

UNI1a cleans a name wherever one comes in: Skill Forge's save card, a SKILL.md import, a card's install, a
connection added by hand, and (models.py's validators) any other write of a skill's name and description, an MCP
server's label or a capability source's name. Rows written before it keep what was typed or fetched: a bidi
override, a zero-width space, a label of only Mongolian variation selectors, a stack of combining marks. Until
now the Capabilities list cleaned those at read time; every other place that shows them (the MCP confirm card,
the connections page, a source's dossier) showed them as stored. This rewrites each such value once, so every
place shows what is stored.

The rule is frozen here, not imported: `_clean` is `untrusted.clean_name` as of v0.1.64, so a later change to
that function never changes what this migration does on a database that runs it later (a test holds the two
equal today). Only Python's own Unicode tables can move under it. A value that cleans to nothing gets what the
Capabilities list showed for it: a skill's key, "MCP <id>", or "capability".

Only rows whose value changes are written, so a second run touches nothing. The old values are in the upgrade
backup the runner takes before this migration, while it is kept. A missing table is left alone.

Names keep letters, marks on a base character (at most four), numbers, punctuation, symbols and single spaces.
So a ZWJ inside an emoji sequence goes: a family emoji becomes its members side by side. That is on purpose: in a
one-line name an invisible character could make two names look alike (tested).
"""
from __future__ import annotations

import unicodedata

#: Frozen from untrusted._NAME_INVISIBLE (v0.1.64): invisible, though not in a "C" category.
_INVISIBLE = frozenset({0x034F, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x180B, 0x180C, 0x180D, 0x180F, 0x2800, 0x3164,
                        0xFFA0, *range(0xFE00, 0xFE10), *range(0xE0100, 0xE01F0)})
_MARKS_MAX = 4
#: (table, its key, the column, the column's limit as models.py's validator applies it)
_FIELDS = (("skill_packs", "key", "name", 100), ("skill_packs", "key", "description", 2000),
           ("mcp_servers", "id", "label", 80), ("capability_sources", "id", "name", 120))


def _clean(text, limit: int) -> str:
    """untrusted.clean_name as of v0.1.64."""
    kept, marks = [], None
    for ch in str(text or ""):
        if ord(ch) in _INVISIBLE:
            continue
        category = unicodedata.category(ch)[0]
        if category == "M":
            if marks is not None and marks < _MARKS_MAX:
                kept.append(ch)
                marks += 1
        elif category in "LNPS":
            kept.append(ch)
            marks = 0
        elif category == "Z" or ch.isspace():
            kept.append(" ")
            marks = None
    return " ".join("".join(kept).split())[:limit].strip()


def _fallback(table: str, column: str, ident) -> str:
    if (table, column) == ("skill_packs", "name"):
        return str(ident)
    if table == "mcp_servers":
        return f"MCP {ident}"
    if table == "capability_sources":
        return "capability"
    return ""


def upgrade_sync(connection) -> None:
    tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
    for table, key, column, limit in _FIELDS:
        if table not in tables:
            continue
        for ident, value in connection.exec_driver_sql(f"SELECT {key}, {column} FROM {table}").fetchall():
            if value is None:
                continue
            cleaned = _clean(value, limit) or _fallback(table, column, ident)
            if cleaned != value:
                connection.exec_driver_sql(f"UPDATE {table} SET {column} = ? WHERE {key} = ?", (cleaned, ident))


def downgrade_sync(connection) -> None:
    """Nothing to restore: the earlier values are what UNI1 removes (hidden or reordering characters), and they
    are in the upgrade backup the runner takes before this migration while it is kept."""
    return

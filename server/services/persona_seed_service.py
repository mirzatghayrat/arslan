"""Persona seed library: import agency-agents personas; FTS5 search for the drafter."""
from __future__ import annotations

import logging
import re

from sqlalchemy import func, select, text as sa_text

from server.db import session as db_session
from server.db.models import PersonaSeed

logger = logging.getLogger(__name__)

# Word tokens: alphanumeric runs or CJK chars. Mirrors knowledge.py's safe-FTS helper.
_TOKEN = re.compile(r"[A-Za-z0-9]+|[一-鿿]")


def _fts_query(text: str) -> str:
    """Quoted/OR-joined FTS5 MATCH string (mirrors knowledge.py) so arbitrary input is safe."""
    toks = _TOKEN.findall(text or "")
    return " OR ".join(f'"{t}"' for t in toks)


async def search(query: str, k: int = 3) -> list[dict]:
    """Top-k persona seeds matching the query (by FTS). Returns dicts; [] on empty/no match."""
    q = _fts_query(query)
    if not q:
        return []
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(sa_text(
            "SELECT ps.slug, ps.name, ps.division, ps.raw, ps.deliverables, ps.workflow "
            "FROM persona_seeds_fts f JOIN persona_seeds ps ON ps.id = f.rowid "
            "WHERE f.text MATCH :q ORDER BY rank LIMIT :k"), {"q": q, "k": k})).mappings().all()
        return [dict(r) for r in rows]


async def count() -> int:
    """Number of persona seeds in the library."""
    async with db_session.AsyncSessionLocal() as db:
        return (await db.execute(select(func.count()).select_from(PersonaSeed))).scalar_one()

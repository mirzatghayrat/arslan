"""Persona seed library: FTS5 search and browsing over the persona seeds already stored."""
from __future__ import annotations

import re

from sqlalchemy import func, select, text as sa_text

from server.db import session as db_session
from server.db.models import PersonaSeed

# Word tokens: alphanumeric runs or CJK chars. Mirrors knowledge.py's safe-FTS helper.
_TOKEN = re.compile(r"[A-Za-z0-9]+|[一-鿿]+")


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


def _summary(seed: PersonaSeed) -> str:
    """A short one-line gist for browsing/chips (prefer mission, else identity)."""
    text = (seed.mission or seed.identity or "").strip().replace("\n", " ")
    return text[:160]


async def list_seeds(query: str | None = None, *, limit: int = 60, offset: int = 0) -> list[dict]:
    """Browse the seed library. With a query, FTS-rank; otherwise alphabetical by name.
    Returns {slug, name, division, summary} dicts for the panel."""
    async with db_session.AsyncSessionLocal() as db:
        q = _fts_query(query or "")
        if q:
            rows = (await db.execute(sa_text(
                "SELECT ps.slug, ps.name, ps.division, ps.mission, ps.identity "
                "FROM persona_seeds_fts f JOIN persona_seeds ps ON ps.id = f.rowid "
                "WHERE f.text MATCH :q ORDER BY rank LIMIT :limit OFFSET :offset"),
                {"q": q, "limit": limit, "offset": offset})).mappings().all()
            return [{"slug": r["slug"], "name": r["name"], "division": r["division"],
                     "summary": ((r["mission"] or r["identity"] or "").strip().replace("\n", " "))[:160]}
                    for r in rows]
        rows = (await db.execute(
            select(PersonaSeed).order_by(PersonaSeed.name).limit(limit).offset(offset)
        )).scalars().all()
        return [{"slug": s.slug, "name": s.name, "division": s.division, "summary": _summary(s)} for s in rows]


async def get_by_slugs(slugs: list[str]) -> list[dict]:
    """Resolve seed slugs → display dicts, preserving the given order. Unknown slugs are dropped."""
    wanted = [s for s in slugs if s]
    if not wanted:
        return []
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(PersonaSeed).where(PersonaSeed.slug.in_(wanted))
        )).scalars().all()
        by_slug = {s.slug: s for s in rows}
        return [{"slug": s, "name": by_slug[s].name, "division": by_slug[s].division,
                 "summary": _summary(by_slug[s])}
                for s in wanted if s in by_slug]

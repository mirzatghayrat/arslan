"""Persona seeds: resolve a spawn's composed seed slugs for its detail view.

The browse/search API (GET /seeds, list_seeds, count, search) went in C7 (v0.1.63): no
component called it. get_by_slugs stays for spawn detail (GET /spawns/{id} and the equipment
reply), which C7 step 3 keeps until v0.1.64.
"""
from __future__ import annotations

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import PersonaSeed


def _summary(seed: PersonaSeed) -> str:
    """A short one-line gist for browsing/chips (prefer mission, else identity)."""
    text = (seed.mission or seed.identity or "").strip().replace("\n", " ")
    return text[:160]


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

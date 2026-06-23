"""Retrieve task-relevant chunks from a spawn's knowledge base (FTS5) and format
them for injection into the spawn's prompt."""
from __future__ import annotations

import re

from sqlalchemy import text as sa_text

from server.db import session as db_session

# Word tokens: CJK chars or alphanumeric runs. Used to build a safe FTS5 query.
_TOKEN_RE = re.compile(r"[0-9A-Za-z]+|[一-鿿]")


def _safe_match_query(query: str) -> str:
    """Build an FTS5 MATCH string from query tokens (each quoted, OR-joined) so
    arbitrary user text never triggers FTS5 syntax errors. Empty → ''."""
    tokens = _TOKEN_RE.findall(query or "")
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"' for t in tokens)


async def retrieve(spawn_id: int, query: str, *, k: int = 5) -> list[str]:
    """Return up to k chunk texts for spawn_id best-matching query. Empty KB /
    no match / empty query → []."""
    match = _safe_match_query(query)
    if not match:
        return []
    async with db_session.AsyncSessionLocal() as db:
        rows = await db.execute(
            sa_text(
                "SELECT kc.text FROM knowledge_chunks_fts f "
                "JOIN knowledge_chunks kc ON kc.id = f.rowid "
                "WHERE f.text MATCH :q AND kc.spawn_id = :sid "
                "ORDER BY rank LIMIT :k"
            ),
            {"q": match, "sid": spawn_id, "k": k},
        )
        return [r[0] for r in rows.all()]


def knowledge_block(chunks: list[str]) -> str:
    """Format retrieved chunks as a system-prompt section, or '' if none."""
    if not chunks:
        return ""
    body = "\n- ".join(chunks)
    return ("\n\nYour knowledge base (use when relevant; do not fabricate beyond it):\n- "
            + body)

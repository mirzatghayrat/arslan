"""Search the conversation history (0.1.52 S3, task book A2 layer 2).

Returns the ORIGINAL words — a snippet around the match — with when it was said, which
conversation, and an in-app link (`#conversation=<id>`), never a summary (summaries lose
the detail people search for). Temporary and "don't use memory" conversations are never
searched. Uses the trigram FTS index (migration 0059); queries shorter than three
characters, or a database without the index, fall back to LIKE.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import text

from server.db import session as db_session

SNIPPET_CHARS = 240
MAX_LIMIT = 20


def _snippet(content: str, query: str) -> str:
    flat = " ".join((content or "").split())
    at = flat.lower().find(query.lower())
    if at < 0 or len(flat) <= SNIPPET_CHARS:
        return flat[:SNIPPET_CHARS]
    start = max(0, at - SNIPPET_CHARS // 3)
    piece = flat[start:start + SNIPPET_CHARS]
    return ("…" if start else "") + piece + ("…" if start + SNIPPET_CHARS < len(flat) else "")


def _fts_query(query: str) -> str:
    return '"' + query.replace('"', '""') + '"'          # one phrase: trigram substring match


async def search(query: str, *, since: datetime | None = None, until: datetime | None = None,
                 limit: int = 8, exclude_conversation: str | None = None) -> list[dict]:
    q = " ".join(str(query or "").split())[:200]
    if not q:
        return []
    limit = max(1, min(int(limit or 8), MAX_LIMIT))
    params: dict = {"limit": limit, "like": f"%{q}%", "since": since, "until": until,
                    "exclude": exclude_conversation or ""}
    where = ("m.role IN ('user', 'arslan') "
             "AND NOT EXISTS (SELECT 1 FROM conversation_contexts c WHERE c.id = m.conversation_id "
             "AND (c.temporary = 1 OR c.no_memory = 1)) "
             "AND (:since IS NULL OR m.timestamp >= :since) AND (:until IS NULL OR m.timestamp <= :until) "
             "AND m.conversation_id != :exclude")
    async with db_session.AsyncSessionLocal() as db:
        has_fts = (await db.execute(text(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='arslan_messages_fts'"))).first() is not None
        if has_fts and len(q) >= 3:
            params["match"] = _fts_query(q)
            sql = (f"SELECT m.id, m.conversation_id, m.role, m.content, m.timestamp FROM arslan_messages_fts f "
                   f"JOIN arslan_messages m ON m.id = f.rowid WHERE arslan_messages_fts MATCH :match AND {where} "
                   f"ORDER BY m.timestamp DESC LIMIT :limit")
        else:
            sql = (f"SELECT m.id, m.conversation_id, m.role, m.content, m.timestamp FROM arslan_messages m "
                   f"WHERE m.content LIKE :like AND {where} ORDER BY m.timestamp DESC LIMIT :limit")
        rows = (await db.execute(text(sql), params)).all()
        firsts: dict[str, str] = {}
        for cid in {r.conversation_id for r in rows}:
            first = (await db.execute(text(
                "SELECT content FROM arslan_messages WHERE conversation_id = :cid AND role = 'user' "
                "ORDER BY id LIMIT 1"), {"cid": cid})).scalar()
            firsts[cid] = " ".join((first or "").split())[:60]
    out = []
    for r in rows:
        ts = r.timestamp if isinstance(r.timestamp, datetime) else (
            datetime.fromisoformat(str(r.timestamp)) if r.timestamp else None)
        out.append({"conversation": firsts.get(r.conversation_id) or r.conversation_id,
                    "conversation_id": r.conversation_id, "message_id": r.id,
                    "who": "you" if r.role == "user" else "Arslan",
                    "when": ts.strftime("%Y-%m-%d %H:%M") if ts else None,
                    "snippet": _snippet(r.content, q),
                    "link": f"#conversation={r.conversation_id}"})
    return out

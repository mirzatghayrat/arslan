"""Search the conversation history (0.1.52 S3, task book A2 layer 2).

Returns the ORIGINAL words — a snippet around the match — with when it was said, which
conversation, and an in-app link (`#conversation=<id>`), never a summary (summaries lose
the detail people search for). Temporary and "don't use memory" conversations and
sub-sessions are never searched. Uses the trigram FTS index (migration 0059); queries shorter than three
characters, or a database without the index, fall back to LIKE.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import text

from server.db import session as db_session

SNIPPET_CHARS = 240
MAX_LIMIT = 20
#: The conversations no other conversation may read, over `conversation_contexts c`: temporary and "don't use memory" ones,
#: and sub-sessions and side chats (SUB2, SIDE-1: their settings live along their chain, not on this row, and no list
#: shows one; nothing of a side chat reaches its parent unless the user brings it back). `search` leaves them out, and so
#: does progress_report (INB7-f, #862 review).
HIDDEN_SQL = "c.temporary = 1 OR c.no_memory = 1 OR c.kind IN ('sub', 'side')"


def refusal(ctx) -> dict | None:
    """Why this turn may not use past conversations, or None: the memory block's permissions. Off in a temporary or "no
    memory" conversation, and off for a cloud model when the user turned memory off for conversations. The tools that read
    other conversations (conversation_search, progress_report) answer with this."""
    if ctx is not None and (ctx.no_memory or ctx.temporary):
        return {"ok": False, "external": False, "error": "memory is off for this conversation"}
    if ctx is not None and not ctx.model_is_local and not ctx.cloud_memory_effective:
        return {"ok": False, "external": False, "error": "using past conversations is turned off (Settings › Memory)"}
    return None


async def hidden(db, ids) -> set[str]:
    """Which of these conversations no other conversation may read (HIDDEN_SQL)."""
    from sqlalchemy import select
    from sqlalchemy.orm import aliased

    from server.db.companion_models import ConversationContext
    if not ids:
        return set()
    c = aliased(ConversationContext, name="c")
    return set((await db.execute(select(c.id).where(c.id.in_(list(ids)), text(HIDDEN_SQL)))).scalars())


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
             f"AND NOT EXISTS (SELECT 1 FROM conversation_contexts c WHERE c.id = m.conversation_id AND ({HIDDEN_SQL})) "
             "AND (:since IS NULL OR m.timestamp >= :since) AND (:until IS NULL OR m.timestamp <= :until) "
             "AND m.conversation_id != :exclude")
    async with db_session.AsyncSessionLocal() as db:
        has_fts = (await db.execute(text(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='arslan_messages_fts'"))).first() is not None
        if has_fts and len(q) >= 3:
            params["match"] = _fts_query(q)
            sql = (f"SELECT m.id, m.conversation_id, m.role, m.content, m.display_content, m.timestamp FROM arslan_messages_fts f "
                   f"JOIN arslan_messages m ON m.id = f.rowid WHERE arslan_messages_fts MATCH :match AND {where} "
                   f"ORDER BY m.timestamp DESC LIMIT :limit")
        else:
            sql = (f"SELECT m.id, m.conversation_id, m.role, m.content, m.display_content, m.timestamp FROM arslan_messages m "
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
                    # K2: the reply as shown, without the turn-tool summary in content.
                    "snippet": _snippet(r.display_content or r.content, q),
                    "link": f"#conversation={r.conversation_id}"})
    return out

"""Hand-written notes: CRUD + FTS sync + [[wiki-link]] parsing + backlinks. AI
helpers (suggest/generate) are added in NT-4/NT-5. FTS row = title + "\n" + content."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from sqlalchemy import select, text as sa_text

from server.db import session as db_session
from server.db.models import Note
from server.services.llm_factory import build_adapter

logger = logging.getLogger(__name__)

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")

_SUGGEST_SYS = ("你是知识库助手。只从给到的候选清单里选出与这篇笔记语义相关、该建 [[链接]] 的条目"
                "(不要选笔记自己),每条给一句理由;再给 3-5 个小写标签。严格输出 JSON,"
                "形如 {\"suggestions\":[{\"target\":\"...\",\"kind\":\"...\",\"reason\":\"...\"}],\"tags\":[\"...\"]}。"
                "target 必须来自候选清单原文,不要编造。")


def parse_links(content: str) -> list[str]:
    """Ordered, de-duplicated [[targets]] from note content."""
    out: list[str] = []
    for m in WIKILINK_RE.findall(content or ""):
        t = m.strip()
        if t and t not in out:
            out.append(t)
    return out


def _fts_text(title: str, content: str) -> str:
    return f"{title}\n{content}"


def _dump(n: Note) -> dict:
    return {"id": n.id, "title": n.title, "content": n.content, "tags": n.tags or [],
            "created_at": n.created_at.isoformat() if n.created_at else None,
            "updated_at": n.updated_at.isoformat() if n.updated_at else None}


async def create(title: str, content: str = "", tags: list[str] | None = None) -> Note:
    async with db_session.AsyncSessionLocal() as db:
        row = Note(title=title.strip() or "未命名笔记", content=content, tags=tags or [])
        db.add(row)
        await db.commit()
        await db.refresh(row)
        await db.execute(sa_text("INSERT INTO notes_fts (rowid, text) VALUES (:r, :t)"),
                         {"r": row.id, "t": _fts_text(row.title, row.content)})
        await db.commit()
        return row


async def list_notes() -> list[dict]:
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(select(Note).order_by(Note.updated_at.desc()))).scalars().all()
    return [_dump(n) for n in rows]


async def get(note_id: int) -> dict | None:
    async with db_session.AsyncSessionLocal() as db:
        n = await db.get(Note, note_id)
    return _dump(n) if n else None


async def update(note_id: int, *, title: str | None = None, content: str | None = None,
                 tags: list[str] | None = None) -> dict | None:
    async with db_session.AsyncSessionLocal() as db:
        n = await db.get(Note, note_id)
        if n is None:
            return None
        if title is not None:
            n.title = title.strip() or n.title
        if content is not None:
            n.content = content
        if tags is not None:
            n.tags = tags
        await db.commit()
        await db.refresh(n)
        await db.execute(sa_text("DELETE FROM notes_fts WHERE rowid = :r"), {"r": note_id})
        await db.execute(sa_text("INSERT INTO notes_fts (rowid, text) VALUES (:r, :t)"),
                         {"r": note_id, "t": _fts_text(n.title, n.content)})
        await db.commit()
        return _dump(n)


async def delete(note_id: int) -> bool:
    async with db_session.AsyncSessionLocal() as db:
        n = await db.get(Note, note_id)
        if n is None:
            return False
        await db.delete(n)
        await db.execute(sa_text("DELETE FROM notes_fts WHERE rowid = :r"), {"r": note_id})
        await db.commit()
        return True


async def backlinks(title: str) -> list[dict]:
    """Notes whose content [[links]] to this title (case-insensitive)."""
    target = (title or "").strip().lower()
    if not target:
        return []
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(select(Note))).scalars().all()
    return [{"id": n.id, "title": n.title} for n in rows
            if target in [t.lower() for t in parse_links(n.content)]]


def _get_adapter():
    return build_adapter(role="summarize")


async def suggest_links(note_id: int, candidate_labels: list[str]) -> dict:
    n = await get(note_id)
    if n is None:
        return {"suggestions": [], "tags": []}
    cand = "\n".join(f"- {c}" for c in candidate_labels if c and c != n["title"])
    user = f"笔记标题:{n['title']}\n笔记内容:\n{n['content']}\n\n候选条目:\n{cand}"
    try:
        adapter = _get_adapter()
        a = await adapter if hasattr(adapter, "__await__") else adapter
        resp = await a.chat(system=_SUGGEST_SYS, user=user)
        data = json.loads((resp.content or "{}").strip())
        allowed = {c for c in candidate_labels}
        sugg = [s for s in data.get("suggestions", [])
                if isinstance(s, dict) and s.get("target") in allowed]
        tags = [t for t in data.get("tags", []) if isinstance(t, str)][:5]
        return {"suggestions": sugg, "tags": tags}
    except Exception as exc:  # noqa: BLE001 — nothing beats a fabricated link
        logger.warning("suggest_links failed (non-fatal): %s", exc)
        return {"suggestions": [], "tags": []}


_GEN_SYS = ("你是知识架构师。就给定主题生成 {n} 篇互链的中文笔记,每篇 title + content(markdown,"
            "含标题/要点,至少 120 字,用 [[其它笔记标题]] 互相链接,每篇至少链 1 篇本批其它笔记)+ "
            "2-3 个小写标签。严格输出 JSON:{{\"notes\":[{{\"title\":\"...\",\"content\":\"...\",\"tags\":[\"...\"]}}]}}。")


async def generate_notes(topic: str, n: int = 4) -> list[dict]:
    if not (topic or "").strip():
        return []
    try:
        adapter = _get_adapter()
        a = await adapter if hasattr(adapter, "__await__") else adapter
        resp = await a.chat(system=_GEN_SYS.format(n=n), user=f"主题:{topic}")
        data = json.loads((resp.content or "{}").strip())
    except Exception as exc:  # noqa: BLE001 — nothing beats half-baked notes
        logger.warning("generate_notes failed (non-fatal): %s", exc)
        return []
    made: list[dict] = []
    for raw in data.get("notes", [])[:n]:
        if not isinstance(raw, dict) or not raw.get("title"):
            continue
        row = await create(raw["title"], raw.get("content", ""),
                           [t for t in (raw.get("tags") or []) if isinstance(t, str)])
        made.append(_dump(row))
    return made

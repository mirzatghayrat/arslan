"""0.1.55 §13: how memory was used, read from what already exists.

Usage comes from the per-turn context receipts (`receipt.used`, `kind: "memory"`),
which record ids and revisions only, never text. No new table: a receipt is the
fact "this entry was in this turn's context", so counting them IS the usage.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select

from server.db.models import (
    ContextReceiptRecord, KnowledgeChunk, MemoryEntry, MemoryRevision, MemorySource, Note,
)

# A week of receipts is a few hundred rows for a heavy user; this bounds a pathological one.
_MAX_RECEIPTS = 20_000


def _iso(value):
    return value.isoformat() + "Z" if value else None


async def usage(db, *, owner_id: str = "local", days: int = 7) -> tuple[dict[str, dict], dict]:
    """Per entry: turns that carried it and when it was last carried; plus totals.

    A turn counts once per entry even if the receipt names the entry twice
    (core + relevant), so "used 3 times" means three turns, not three lines."""
    since = datetime.utcnow() - timedelta(days=days)
    rows = (await db.execute(
        select(ContextReceiptRecord.conversation_id, ContextReceiptRecord.receipt, ContextReceiptRecord.created_at)
        .where(ContextReceiptRecord.owner_id == owner_id, ContextReceiptRecord.created_at >= since)
        .order_by(ContextReceiptRecord.created_at.desc()).limit(_MAX_RECEIPTS))).all()
    per_entry: dict[str, dict] = {}
    turns = 0
    conversations: set[str] = set()
    for conversation_id, receipt, created_at in rows:
        used = receipt.get("used") if isinstance(receipt, dict) else None
        ids = {item.get("id") for item in used or () if isinstance(item, dict) and item.get("kind") == "memory"}
        ids.discard(None)
        if not ids:
            continue
        turns += 1
        conversations.add(conversation_id)
        for entry_id in ids:
            seen = per_entry.setdefault(entry_id, {"uses": 0, "last_used_at": None})
            seen["uses"] += 1
            if seen["last_used_at"] is None:  # rows are newest first
                seen["last_used_at"] = _iso(created_at)
    return per_entry, {"retrievals": turns, "conversations": len(conversations)}


async def core_budgets(db, *, owner_id: str = "local") -> dict:
    """The two always-in-view sets, measured the way the prompt builder fills them."""
    from server.services.personal_context import CORE_ABOUT_YOU_CHARS, CORE_NOTES_CHARS, _core
    rows = (await db.execute(select(MemoryEntry, MemoryRevision).join(
        MemoryRevision, MemoryRevision.id == MemoryEntry.current_revision_id,
    ).where(MemoryEntry.owner_id == owner_id, MemoryEntry.status == "active"))).all()
    about_you, notes = _core([tuple(row) for row in rows])
    marked = {"about_you": 0, "notes": 0}
    for _entry, revision in rows:
        member = (revision.structured_value or {}).get("core")
        if member in marked:
            marked[member] += 1

    def measure(chosen, cap, member):
        used = sum(len(" ".join((revision.content or "").split())) for _e, revision in chosen)
        return {"used": used, "cap": cap, "entries": len(chosen), "left_out": marked[member] - len(chosen)}
    return {"about_you": measure(about_you, CORE_ABOUT_YOU_CHARS, "about_you"),
            "notes": measure(notes, CORE_NOTES_CHARS, "notes")}


async def stats(db, *, owner_id: str = "local", days: int = 7) -> dict:
    from server.services import settings_service
    since = datetime.utcnow() - timedelta(days=days)
    _per_entry, totals = await usage(db, owner_id=owner_id, days=days)
    new_entries = await db.scalar(select(func.count()).select_from(MemoryEntry).where(
        MemoryEntry.owner_id == owner_id, MemoryEntry.status == "active", MemoryEntry.created_at >= since)) or 0
    # An edit is a later revision the user wrote (creation is "created", status flips are "status_*").
    user_edits = await db.scalar(select(func.count(func.distinct(MemoryRevision.id))).select_from(MemoryRevision).join(
        MemorySource, MemorySource.revision_id == MemoryRevision.id,
    ).join(MemoryEntry, MemoryEntry.id == MemoryRevision.entry_id).where(
        MemoryEntry.owner_id == owner_id, MemoryRevision.change_reason == "user_confirmed",
        MemoryRevision.previous_version.is_not(None), MemorySource.author == "user",
        MemoryRevision.created_at >= since)) or 0
    materials = await db.scalar(select(func.count()).select_from(
        select(KnowledgeChunk.collection_id, KnowledgeChunk.source)
        .where(KnowledgeChunk.collection_id.is_not(None)).distinct().subquery())) or 0
    latest_material = await db.scalar(select(KnowledgeChunk.source).where(
        KnowledgeChunk.collection_id.is_not(None)).order_by(KnowledgeChunk.created_at.desc()).limit(1))
    notes = await db.scalar(select(func.count()).select_from(Note)) or 0
    latest_note = await db.scalar(select(Note.title).order_by(Note.updated_at.desc()).limit(1))
    return {
        "days": days, **totals, "new_entries": new_entries, "user_edits": user_edits,
        "core": await core_budgets(db, owner_id=owner_id),
        # "Remember me and use it in conversations": when on, cloud models see normal
        # memory too (never local-only or sensitive entries without the per-chat switch).
        "remember_in_conversations": await settings_service.memory_in_conversations(db),
        "materials": {"count": materials, "latest": latest_material},
        "notes": {"count": notes, "latest": latest_note},
    }

"""Scope 1 (working memory + compaction) and scope 3 (long-term facts)."""
from __future__ import annotations

import os

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import ArslanMessage, ArslanSummary, UserFact
from server.services.llm_factory import build_adapter

_DEFAULT_CHAR_BUDGET = 12000  # ~3k tokens at 4 chars/token


def estimate_tokens(text: str) -> int:
    """Cheap heuristic: ~4 characters per token (no tokenizer dependency)."""
    return len(text) // 4


def _char_budget() -> int:
    return int(os.environ.get("ARSLAN_WORKING_CHAR_BUDGET", str(_DEFAULT_CHAR_BUDGET)))


async def add_message(
    conversation_id: str,
    role: str,
    content: str,
    *,
    display_content: str | None = None,
    spawn_id: int | None = None,
) -> int:
    """Append an arslan_messages row; return its id."""
    async with db_session.AsyncSessionLocal() as db:
        row = ArslanMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            display_content=display_content,
            spawn_id=spawn_id,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def _latest_summary(db, conversation_id: str) -> ArslanSummary | None:  # noqa: ANN001
    rows = await db.execute(
        select(ArslanSummary)
        .where(ArslanSummary.conversation_id == conversation_id)
        .order_by(ArslanSummary.id.desc())
    )
    return rows.scalars().first()


async def assemble_working_context(conversation_id: str) -> dict:
    """Return {summary, history} for the router/answer prompt.

    `history` is the CONTEXT copy (arslan_messages.content) of turns AFTER the latest
    compaction point, newest last. `summary` is the rolling compaction summary ("" if none).
    """
    async with db_session.AsyncSessionLocal() as db:
        summ = await _latest_summary(db, conversation_id)
        cutoff = summ.up_to_message_id if summ else 0
        rows = await db.execute(
            select(ArslanMessage)
            .where(ArslanMessage.conversation_id == conversation_id)
            .where(ArslanMessage.id > cutoff)
            .order_by(ArslanMessage.id)
        )
        msgs = rows.scalars().all()
    history = [
        {"role": "user" if m.role == "user" else "assistant", "content": m.content}
        for m in msgs
    ]
    return {"summary": summ.summary if summ else "", "history": history}


async def maybe_compact(conversation_id: str) -> None:
    """If the post-cutoff working text exceeds the char budget, fold older messages
    into a rolling summary. On any failure, leave the thread un-compacted (never drop)."""
    try:
        async with db_session.AsyncSessionLocal() as db:
            summ = await _latest_summary(db, conversation_id)
            cutoff = summ.up_to_message_id if summ else 0
            rows = await db.execute(
                select(ArslanMessage)
                .where(ArslanMessage.conversation_id == conversation_id)
                .where(ArslanMessage.id > cutoff)
                .order_by(ArslanMessage.id)
            )
            msgs = rows.scalars().all()

        total_chars = sum(len(m.content) for m in msgs)
        if total_chars <= _char_budget() or len(msgs) < 2:
            return

        # Fold all but the most recent message into the summary.
        to_fold = msgs[:-1]
        new_cutoff = to_fold[-1].id
        prior = summ.summary if summ else ""
        body = "\n".join(f"{m.role}: {m.content}" for m in to_fold)
        adapter = _get_adapter()
        new_summary = await _summarize(adapter, f"{prior}\n{body}".strip())

        async with db_session.AsyncSessionLocal() as db:
            db.add(
                ArslanSummary(
                    conversation_id=conversation_id,
                    summary=new_summary,
                    up_to_message_id=new_cutoff,
                )
            )
            await db.commit()
    except Exception:  # noqa: BLE001 - degrade gracefully, keep full thread
        return


def _get_adapter():
    """Indirection so tests can stub adapter construction."""
    return build_adapter()


async def _summarize(adapter, text: str) -> str:  # noqa: ANN001
    """One compaction LLM call. `adapter` may be an awaitable (build_adapter())."""
    a = await adapter if hasattr(adapter, "__await__") else adapter
    resp = await a.chat(
        system="Summarize the conversation so far into a compact running summary. "
        "Preserve durable facts, decisions, and open threads. Be terse.",
        user=text,
    )
    return (resp.content or "").strip()


# ---- Scope 3: long-term facts ----

async def save_facts(facts: list[dict]) -> list[UserFact]:
    """Persist auto-extracted facts; return the created rows."""
    created: list[UserFact] = []
    if not facts:
        return created
    async with db_session.AsyncSessionLocal() as db:
        for f in facts:
            content = (f.get("content") or "").strip()
            if not content:
                continue
            row = UserFact(
                content=content,
                source=f.get("source", "auto"),
                sensitive=bool(f.get("sensitive", False)),
            )
            db.add(row)
            created.append(row)
        await db.commit()
        for row in created:
            await db.refresh(row)
    return created


async def list_facts() -> list[UserFact]:
    async with db_session.AsyncSessionLocal() as db:
        rows = await db.execute(select(UserFact).order_by(UserFact.id))
        return list(rows.scalars().all())


async def facts_text() -> str:
    """Render facts as a bullet block for injection into prompts ('' if none)."""
    facts = await list_facts()
    if not facts:
        return ""
    return "Known facts about the user:\n" + "\n".join(f"- {f.content}" for f in facts)

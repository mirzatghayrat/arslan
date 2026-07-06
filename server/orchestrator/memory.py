"""Scope 1 (working memory + compaction) and scope 3 (long-term facts)."""
from __future__ import annotations

import logging
import os

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import ArslanMessage, ArslanSummary, UserFact
from server.services.llm_factory import build_adapter

logger = logging.getLogger(__name__)

_DEFAULT_TOKEN_BUDGET = 3000  # ~working context tokens for Arslan; env-tunable


def estimate_tokens(text: str) -> int:
    """Estimate tokens. CJK chars are ~1 token each; other text ~4 chars/token.

    The product targets Chinese users, where a naive 4-chars/token estimate
    undercounts tokens by ~2x and lets the thread run far past the intended budget.
    """
    cjk = sum(
        1
        for ch in text
        if "一" <= ch <= "鿿"   # CJK Unified Ideographs
        or "぀" <= ch <= "ヿ"   # Hiragana + Katakana
        or "가" <= ch <= "힯"   # Hangul syllables
    )
    other = len(text) - cjk
    return cjk + other // 4


def _token_budget() -> int:
    return int(os.environ.get("ARSLAN_WORKING_TOKEN_BUDGET", str(_DEFAULT_TOKEN_BUDGET)))


def _summary_token_cap() -> int:
    """The rolling summary itself must stay bounded, else context grows unbounded
    (it is injected into every prompt). Cap it at the working budget."""
    return _token_budget()


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
    history = []
    for m in msgs:
        if m.role == "user":
            history.append({"role": "user", "content": m.content})
        elif m.role == "spawn_summary":
            # A specialist spawn's relayed output. Frame it in the third person so the answer
            # model treats it as a teammate's message and never adopts the spawn's identity
            # (otherwise Arslan continues a spawn's first-person voice, e.g. "我是 Mermer").
            history.append(
                {"role": "assistant", "content": f"(relayed output from a specialist spawn) {m.content}"}
            )
        else:  # arslan's own turns pass through verbatim
            history.append({"role": "assistant", "content": m.content})
    return {"summary": summ.summary if summ else "", "history": history}


async def maybe_compact(conversation_id: str) -> None:
    """If the post-cutoff working text exceeds the char budget, fold older messages
    into a rolling summary. On any failure, leave the thread un-compacted (never drop)."""
    try:
        # NOTE: read-then-write is not serialized; safe for v1's single sequential user.
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

        total_tokens = sum(estimate_tokens(m.content) for m in msgs)
        if total_tokens <= _token_budget() or len(msgs) < 2:
            return

        # Fold all but the most recent message into the summary.
        to_fold = msgs[:-1]
        new_cutoff = to_fold[-1].id
        prior = summ.summary if summ else ""
        body = "\n".join(f"{m.role}: {m.content}" for m in to_fold)
        adapter = _get_adapter()
        new_summary = await _summarize(adapter, f"{prior}\n{body}".strip())

        # Bound the rolling summary itself (C1): if it exceeds the cap, compress it
        # once more, then hard-truncate as a guaranteed floor so context can't grow.
        if estimate_tokens(new_summary) > _summary_token_cap():
            new_summary = await _summarize(adapter, new_summary)
            cap_chars = _summary_token_cap() * 4
            if len(new_summary) > cap_chars:
                new_summary = new_summary[:cap_chars]

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
        logger.warning("compaction failed for %s; keeping full thread", conversation_id, exc_info=True)
        return


def _get_adapter():
    """Indirection so tests can stub adapter construction."""
    return build_adapter(role="summarize")


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
    """Persist auto-extracted facts; return the created rows.

    Write-time dedup (exact-normalized) skips facts that already exist, within
    the batch and against the existing store. Fail-open: any failure computing
    the existing-norm set is swallowed and treated as empty (i.e. dedup is
    skipped, not the write) — a user's fact must always get saved.
    """
    created: list[UserFact] = []
    if not facts:
        return created

    from server.services.fact_dedup import norm

    seen = await existing_norms_safe()

    async with db_session.AsyncSessionLocal() as db:
        for f in facts:
            content = (f.get("content") or "").strip()
            if not content:
                continue
            try:
                key = norm(content)
                if key in seen:
                    continue
            except Exception:  # noqa: BLE001 - fail-open: never skip a legit write on error
                key = None
            row = UserFact(
                content=content,
                source=f.get("source", "auto"),
                sensitive=bool(f.get("sensitive", False)),
            )
            db.add(row)
            created.append(row)
            if key is not None:
                seen.add(key)
        await db.commit()
        for row in created:
            await db.refresh(row)
    return created


async def existing_norms_safe() -> set[str]:
    """Fail-open wrapper: returns existing_norms(), or empty set on any failure."""
    try:
        from server.services.fact_dedup import existing_norms

        return await existing_norms()
    except Exception:  # noqa: BLE001 - dedup must never block writes
        logger.warning("existing_norms failed; treating as empty (fail-open)", exc_info=True)
        return set()


async def list_facts() -> list[UserFact]:
    async with db_session.AsyncSessionLocal() as db:
        rows = await db.execute(select(UserFact).order_by(UserFact.id))
        return list(rows.scalars().all())


async def add_manual_fact(content: str, sensitive: bool = False) -> UserFact:
    """Add a user-authored fact (source='manual').

    Write-time dedup (exact-normalized): if a fact with the same normalized
    content already exists, return that existing row instead of inserting a
    duplicate. Fail-open: any exception in the dedup check is swallowed and
    falls through to a normal insert — a user's fact must always get saved.
    """
    text = content.strip()
    if not text:
        raise ValueError("Fact content cannot be empty")

    try:
        from server.services.fact_dedup import norm

        target = norm(text)
        if target in await existing_norms_safe():
            async with db_session.AsyncSessionLocal() as db:
                rows = await db.execute(select(UserFact).order_by(UserFact.id))
                for row in rows.scalars().all():
                    if norm(row.content) == target:
                        return row
    except Exception:  # noqa: BLE001 - fail-open: dedup must never block the write
        logger.warning("add_manual_fact: dedup check failed; proceeding with insert", exc_info=True)

    async with db_session.AsyncSessionLocal() as db:
        row = UserFact(content=text, source="manual", sensitive=bool(sensitive))
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row


async def update_fact(fact_id: int, content: str | None = None, sensitive: bool | None = None) -> UserFact | None:
    """Edit a fact's content/sensitivity. Returns None if not found."""
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(UserFact, fact_id)
        if row is None:
            return None
        if content is not None:
            row.content = content.strip()
        if sensitive is not None:
            row.sensitive = bool(sensitive)
        await db.commit()
        await db.refresh(row)
        return row


async def delete_fact(fact_id: int) -> bool:
    """Delete a fact. Returns True if a row was removed."""
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(UserFact, fact_id)
        if row is None:
            return False
        await db.delete(row)
        await db.commit()
        return True


async def facts_text() -> str:
    """Render facts as a bullet block for injection into prompts ('' if none)."""
    facts = await list_facts()
    if not facts:
        return ""
    return "Known facts about the user:\n" + "\n".join(f"- {f.content}" for f in facts)


async def user_turn_count(conversation_id: str) -> int:
    """Number of user turns so far — the 'turn clock' for temporary grants."""
    from sqlalchemy import func, select

    from server.db.models import ArslanMessage

    async with db_session.AsyncSessionLocal() as db:
        n = (await db.execute(
            select(func.count()).select_from(ArslanMessage).where(
                ArslanMessage.conversation_id == conversation_id,
                ArslanMessage.role == "user",
            )
        )).scalar_one()
    return int(n)

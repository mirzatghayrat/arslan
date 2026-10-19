"""Scope 1 (working memory + compaction) and scope 3 (long-term facts)."""
from __future__ import annotations

import logging
import os
from types import SimpleNamespace

from sqlalchemy import select

from arslan.context_budget import clip as clip_context, estimate_tokens

from server.db import session as db_session
from server.db.models import ArslanMessage, ArslanSummary
from server.services.llm_factory import build_adapter
from server.services.memory_history import eligible_messages

logger = logging.getLogger(__name__)

_DEFAULT_TOKEN_BUDGET = 3000  # ~working context tokens for Arslan; env-tunable


_FACTS_TOKEN_BUDGET = 600  # facts 块 token 预算(estimate_tokens 计)


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
    job_outcome: str | None = None,
    source: str | None = None,
) -> int:
    """Append an arslan_messages row; return its id."""
    async with db_session.AsyncSessionLocal() as db:
        row = ArslanMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            display_content=display_content,
            spawn_id=spawn_id,
            job_outcome=job_outcome,
            source=source,
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
            eligible_messages(conversation_id)
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
    # Compaction is model-backed and may fail. Prompt admission is deterministic
    # regardless: keep a bounded summary and the newest turns without deleting
    # ANY source messages. This is an estimate, not an exact vendor-token bound.
    budget = max(1, _token_budget())
    original_summary = summ.summary if summ else ""
    summary = clip_context(original_summary, max(1, budget // 2))
    remaining = budget - estimate_tokens(summary)
    bounded = []
    used_ids = []
    for source, message in reversed(list(zip(msgs, history))):
        content = clip_context(message["content"], remaining)
        if content:
            bounded.append({**message, "content": content})
            used_ids.append(source.id)
            remaining -= estimate_tokens(content)
        if remaining <= 0 or content != message["content"]:
            break
    bounded.reverse()
    truncated = summary != original_summary or bounded != history
    from server.services import task_service
    runtime = task_service.current()
    if runtime is not None:
        runtime.register_history(conversation_id, used_ids,
                                 [(summ.id, summ.updated_at)] if summ and summary else [])
    return {"summary": summary, "history": bounded, "truncated": truncated,
            "budget_mode": "estimated_text_tokens"}


async def maybe_compact(conversation_id: str) -> None:
    """If the post-cutoff working text exceeds the char budget, fold older messages
    into a rolling summary. On any failure, leave the thread un-compacted (never drop)."""
    try:
        from sqlalchemy import insert, literal
        from server.services import memory_snapshot_guard
        # NOTE: read-then-write is not serialized; safe for v1's single sequential user.
        async with db_session.AsyncSessionLocal() as db:
            snapshot_token = await memory_snapshot_guard.capture(db)
            summ = await _latest_summary(db, conversation_id)
            cutoff = summ.up_to_message_id if summ else 0
            rows = await db.execute(
                eligible_messages(conversation_id)
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
        # Sync-or-awaitable, the same shape router.py uses. This seam has always
        # accepted a plain object from a test stub; making it await-only would have been
        # the code demanding that six existing tests change to suit it.
        adapter = _get_adapter()
        adapter = await adapter if hasattr(adapter, "__await__") else adapter
        # S3-M3 usage ledger: compaction runs at orchestration level (after the turn,
        # never inside a dispatch's collecting region) — ledger its 1-2 summarize calls
        # under scope="memory".
        from server.services import usage_ledger

        async with usage_ledger.scope("memory", conversation_id):
            if not await memory_snapshot_guard.is_current(snapshot_token):
                return
            new_summary = await _summarize(adapter, f"{prior}\n{body}".strip())

            # Bound the rolling summary itself (C1): if it exceeds the cap, compress it
            # once more, then hard-truncate as a guaranteed floor so context can't grow.
            if estimate_tokens(new_summary) > _summary_token_cap():
                if not await memory_snapshot_guard.is_current(snapshot_token):
                    return
                new_summary = await _summarize(adapter, new_summary)
                new_summary = clip_context(new_summary, _summary_token_cap())

        async with db_session.AsyncSessionLocal() as db:
            await db.execute(insert(ArslanSummary).from_select(
                ["conversation_id", "summary", "up_to_message_id"],
                select(literal(conversation_id), literal(new_summary), literal(new_cutoff))
                .where(memory_snapshot_guard.unchanged(snapshot_token))))
            await db.commit()
    except Exception:  # noqa: BLE001 - degrade gracefully, keep full thread
        logger.warning("compaction failed for %s; keeping full thread", conversation_id, exc_info=True)
        return


async def _get_adapter():
    """The adapter for this task, honouring its per-task slot if one is set.

    🔴 The slot is consulted FIRST and only overrides when the user set one — an unset
    slot returns None from build_slot_adapter, and this falls through to exactly the
    call that happened before. A hook that rerouted unconditionally would move this
    task, and its cost, onto another model with no symptom but the bill.
    """
    from server.services.llm_factory import build_slot_adapter

    slotted = await build_slot_adapter("compaction_config_id")
    if slotted is not None:
        return slotted
    return await build_adapter(role="summarize")


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
# Memory v2 only (C2a): every launch activates it (storage_boot.initialize), so the v1 paths over
# the user_facts table could not run and are gone. The facts are memory entries; the functions below
# keep the old fact-shaped interface through memory_compat.

async def save_facts(facts: list[dict], *, provenance: dict) -> list[SimpleNamespace]:
    """Save auto-extracted facts as memory entries in the bound task context's scope; return their
    fact views. Near-duplicates of something already remembered are skipped (memory_compat).

    `provenance` is mandatory (a programmer guard: every caller declares where its facts come from),
    though v2 records the source from the bound task context. Callers: arslan.py's router extraction
    ({"source_kind": "router", "conversation_id": <cid>}) and distill_service.distill_meta_upflow
    ({"source_kind": "upflow", "spawn_id": <id>}).
    """
    if not provenance:
        raise ValueError("save_facts: provenance is mandatory (programmer guard)")
    from server.services import memory_compat
    return await memory_compat.save_facts(facts)


async def list_facts(*, include_superseded: bool = False,
                     include_stale: bool = False) -> list[SimpleNamespace]:
    """Fact views of the entries behind the facts API: active only by default; include_stale adds
    paused entries, include_superseded every entry not deleted (the Settings/Memory admin view)."""
    from server.services import memory_compat
    return await memory_compat.list_facts(include_superseded=include_superseded, include_stale=include_stale)


async def add_manual_fact(content: str, sensitive: bool = False) -> SimpleNamespace:
    """Add a user-authored fact as a global memory entry; return its fact view."""
    from server.services import memory_compat
    return await memory_compat.add_manual_fact(content, sensitive)


async def update_fact(fact_id: int, content: str | None = None, sensitive: bool | None = None,
                      *, expected_version: int | None = None) -> SimpleNamespace | None:
    """Edit a fact's content/sensitivity as a new revision. None if not found."""
    from server.services import memory_compat
    return await memory_compat.update_fact(fact_id, content, sensitive, expected_version=expected_version)


async def delete_fact(fact_id: int, *, expected_version: int | None = None) -> bool:
    """Delete a fact. Returns True if one was removed."""
    from server.services import memory_compat
    return await memory_compat.delete_fact(fact_id, expected_version=expected_version)


async def facts_text(*, include_sensitive: bool = False,
                     limit_tokens: int = _FACTS_TOKEN_BUDGET) -> str:
    """The memory the bound task context may see, rendered for a prompt ('' if none, or no context).

    include_sensitive=False is FAIL-CLOSED: sensitive entries reach a prompt only where the host
    call site declares the privilege (router / host answer / spawn_drafter) AND the context allows
    them. Spawn dispatch, sandbox drafts and replay ambient keep the safe default, so a forgotten
    flag gives less, never a private fact in a spawn prompt.
    """
    from dataclasses import replace
    from server.services.personal_context import assemble, current
    context = current()
    if context is None:
        return ""
    result = await assemble(context=replace(context, allow_sensitive=context.allow_sensitive and include_sensitive),
                            limit_tokens=limit_tokens)
    return result.text if result else ""


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

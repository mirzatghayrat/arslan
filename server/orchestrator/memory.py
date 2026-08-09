"""Scope 1 (working memory + compaction) and scope 3 (long-term facts)."""
from __future__ import annotations

import logging
import os
from datetime import datetime

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


_FACTS_MAX_COUNT = 40      # 注入事实条数硬上限
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

async def save_facts(facts: list[dict], *, provenance: dict) -> list[UserFact]:
    """Persist auto-extracted facts; return the created rows.

    `provenance` is MANDATORY (programmer guard, not the dedup's fail-open
    discipline — see below): every write must declare where it came from
    ({"source_kind": ..., ...}). Callers: arslan.py's router-extraction path
    ({"source_kind": "router", "conversation_id": <cid>}) and
    distill_service.distill_meta_upflow ({"source_kind": "upflow", "spawn_id": <id>}).

    Write-time dedup is two-phase: exact-normalized duplicates merge (bump the
    existing fact's confidence, don't append); fuzzy near-dups route through
    `fact_dedup.fuzzy_kind` (P1 rule-initiated supersede, direction lock):
    "extension" (new extends old) auto-supersedes via the memory_temporal
    executor (in-transaction, full guards — never a bare pointer write);
    "shrink"/"other" coexist and get a MemoryProposal soft-mark for human
    adjudication; below-threshold pairs (fuzzy_kind returns None) never reach
    this branch at all — pure coexist, zero proposal (P0 semantics preserved).
    All scanners are active-only (superseded_by IS NULL) — a new write must
    never collide with a dead row. Fail-open: any failure in the dedup checks
    is swallowed and treated as no-dup — a user's fact must always get saved.
    This fail-open discipline is SEPARATE from the provenance guard above: a
    missing/empty provenance is a programmer error and always raises, dedup
    failures never do.

    NOTE (#13, multi-sibling): find_near_dup returns the FIRST active similar
    row in scan order — P1 semantics is "at most one near-dup pair handled per
    write". A write that fuzzy-matches a non-extension sibling is safe-biased
    toward coexist+proposal (deterministic), not a full-table optimal match.
    """
    if not provenance:
        raise ValueError("save_facts: provenance is mandatory (programmer guard)")
    created: list[UserFact] = []
    if not facts:
        return created

    from server.db.models import MemoryProposal
    from server.services import fact_dedup, memory_temporal
    from server.services.fact_dedup import exact_norm_dup, find_near_dup

    async with db_session.AsyncSessionLocal() as db:
        for f in facts:
            content = (f.get("content") or "").strip()
            if not content:
                continue
            # P0-b 两阶段:精确归一相等 → merge-bump(真重复);模糊命中 → 三路
            # (P1: extension 自动取代/shrink+other 提案)。两阶段皆 fail-open+活跃-only。
            exact = await exact_norm_dup(db, content)
            if exact is not None:
                exact.confidence = min(1.0, (exact.confidence or 0.6) + 0.1)
                continue
            fuzzy = await find_near_dup(db, content)
            row = UserFact(
                content=content,
                source=f.get("source", "auto"),
                sensitive=bool(f.get("sensitive", False)),
                confidence=0.9 if f.get("source") == "manual" else 0.6,
                provenance=dict(provenance),
                valid_from=datetime.utcnow(),
            )
            db.add(row)
            created.append(row)
            if fuzzy is not None:
                # Fail-open envelope (pre-merge hardening): the row insert above
                # stays OUTSIDE this try — the fact itself is never hostage. A
                # raise anywhere in the supersede/proposal step below would
                # otherwise propagate and roll back the WHOLE batch (all facts
                # in the call lost), violating "a user's fact must always get
                # saved". Why-safe note: under v1 this sub-block cannot raise —
                # the fuzzy hit comes from an active-only scan (so the executor's
                # already_superseded guard can't fire), the flush precedes the
                # pointer write, and provenance is non-empty (guarded at entry);
                # the except is defense-in-depth for future batch/concurrency
                # changes, not a live path.
                try:
                    # HARD requirement: row.id is None until flushed — without
                    # this, the auto-supersede below silently no-ops (new_id=None).
                    await db.flush()
                    kind = fact_dedup.fuzzy_kind(content, fuzzy.content)
                    if kind == "extension":
                        # new extends old -> auto-supersede (direction lock),
                        # through the EXECUTOR's full guards -- never a bare
                        # pointer write.
                        await memory_temporal.execute_supersede(
                            "user_facts", row.id, fuzzy.id, provenance=provenance, db=db)
                    elif kind in ("shrink", "other"):
                        db.add(MemoryProposal(
                            table_name="user_facts", new_id=row.id, old_id=fuzzy.id,
                            reason=f"{kind}: near-dup coexist", provenance=provenance))
                        logger.info(
                            "save_facts: near-dup coexist -> proposal (%s): %d ~ %d",
                            kind, row.id, fuzzy.id)
                    # kind is None here only if fuzzy_kind's exact-norm-equal
                    # guard fires, which exact_norm_dup (active-only) should
                    # already have caught above -- defensive, not expected.
                except Exception:  # noqa: BLE001 — fail-open: fact > pointer/proposal
                    logger.warning(
                        "save_facts: supersede/proposal step failed; falling back "
                        "to pure coexist (fact already staged): %r",
                        content, exc_info=True)
        await db.commit()
        for row in created:
            await db.refresh(row)
    try:
        from server.services import fact_classify
        ids = [r.id for r in created]
        if ids:
            fact_classify.schedule(fact_classify.classify_ids(ids))
    except Exception:  # noqa: BLE001 — scheduling never blocks the write
        pass
    return created


async def existing_norms_safe() -> set[str]:
    """Fail-open wrapper: returns existing_norms(), or empty set on any failure."""
    try:
        from server.services.fact_dedup import existing_norms

        return await existing_norms()
    except Exception:  # noqa: BLE001 - dedup must never block writes
        logger.warning("existing_norms failed; treating as empty (fail-open)", exc_info=True)
        return set()


async def list_facts(*, include_superseded: bool = False,
                     include_stale: bool = False) -> list[UserFact]:
    """Active-only by default (superseded_by IS NULL, and not marked stale) — the P0
    single throat: every injection site renders facts via facts_text() -> list_facts(),
    so this default makes all of them active-only for free. include_superseded=True /
    include_stale=True are for the Settings/Memory admin view (audit trail).

    `provenance["stale"]` is set by the remember tool's `mark_stale` action
    (registry/memory_executors._mark_stale_tier1), which is advertised to the model in
    the tool schema. It is filtered HERE rather than at each caller for the same reason
    superseded_by is: this function is the only door, so a new injection site cannot
    forget. Marking is a toggle — marking again clears the flag and the fact comes
    back — so the row is left alone; nothing about the mark is destructive.
    """
    async with db_session.AsyncSessionLocal() as db:
        stmt = select(UserFact).order_by(UserFact.id)
        if not include_superseded:
            stmt = stmt.where(UserFact.superseded_by.is_(None))
        rows = await db.execute(stmt)
        facts = list(rows.scalars().all())
    if not include_stale:
        # Filtered in Python, not SQL: `provenance` is a JSON column, and a
        # json_extract() predicate would tie the single throat to SQLite's JSON1
        # extension for a set small enough that the scan is free.
        facts = [f for f in facts if not (f.provenance or {}).get("stale")]
    return facts


async def add_manual_fact(content: str, sensitive: bool = False) -> UserFact:
    """Add a user-authored fact (source='manual').

    Write-time dedup (exact-normalized, active-only — superseded rows never
    collide with a new write): if an ACTIVE fact with the same normalized
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
                rows = await db.execute(
                    select(UserFact).where(UserFact.superseded_by.is_(None)).order_by(UserFact.id)
                )
                for row in rows.scalars().all():
                    if norm(row.content) == target:
                        return row
    except Exception:  # noqa: BLE001 - fail-open: dedup must never block the write
        logger.warning("add_manual_fact: dedup check failed; proceeding with insert", exc_info=True)

    async with db_session.AsyncSessionLocal() as db:
        row = UserFact(
            content=text,
            source="manual",
            sensitive=bool(sensitive),
            confidence=0.9,  # debt#5 fix: manual facts were previously unset (NULL)
            provenance={"source_kind": "manual", "via": "api"},
            valid_from=datetime.utcnow(),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        try:
            from server.services import fact_classify
            fact_classify.schedule(fact_classify.classify_ids([row.id]))
        except Exception:  # noqa: BLE001 — scheduling never blocks the write
            pass
        return row


async def update_fact(fact_id: int, content: str | None = None, sensitive: bool | None = None) -> UserFact | None:
    """Edit a fact's content/sensitivity. Returns None if not found.

    An edit merges `edited_by_user_at` into the row's provenance dict (rather than
    replacing it) — an auto-extracted fact a human later hand-edits becomes
    distinguishable from a still-pristine auto fact, without losing its original
    source_kind/spawn_id/conversation_id.
    """
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(UserFact, fact_id)
        if row is None:
            return None
        if content is not None:
            row.content = content.strip()
        if sensitive is not None:
            row.sensitive = bool(sensitive)
        if content is not None or sensitive is not None:
            prov = dict(row.provenance or {})
            prov["edited_by_user_at"] = datetime.utcnow().isoformat()
            row.provenance = prov
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


async def facts_text(*, include_sensitive: bool = False,
                     limit_tokens: int = _FACTS_TOKEN_BUDGET) -> str:
    """Render facts as a bullet block for injection into prompts ('' if none).

    P0-a:确定性上限——confidence 优先、recency 破平、id 终平,再按
    _FACTS_MAX_COUNT 与 token 预算截断(estimate_tokens,CJK-aware)。
    默认 include_sensitive=False 是 FAIL-CLOSED:敏感事实只在 host 调用点
    显式声明特权(router / host answer / spawn_drafter)时进入 prompt;
    spawn dispatch / sandbox 草稿 / replay ambient 走安全默认,零改动即正确。
    忘传 flag 的泄漏方向永远是"少给",不是"私密进 spawn prompt"。
    """
    facts = await list_facts()
    if not include_sensitive:
        # NULL⇒sensitive:隐私过滤 fail-closed——只有显式 False 放行
        # (raw insert 可产生 NULL sensitive;truthiness 会把 NULL 当非敏感放漏)。
        facts = [f for f in facts if f.sensitive is False]
    if not facts:
        return ""
    total = len(facts)

    def _ordinal(f) -> float:  # noqa: ANN001 — NULL-safe recency(raw insert 可为 NULL)
        return f.created_at.timestamp() if f.created_at is not None else 0.0

    ranked = sorted(facts, key=lambda f: (-(f.confidence or 0.6), -_ordinal(f), -f.id))
    chosen = []
    spent = 0
    for f in ranked[:_FACTS_MAX_COUNT]:
        line_tokens = estimate_tokens(f"- {f.content}")
        if chosen and spent + line_tokens > limit_tokens:
            break
        chosen.append(f)
        spent += line_tokens
    if len(chosen) < total:
        # 诚实:截断留痕,不静默
        logger.debug("facts_text: capped %d/%d facts (count/token budget)", len(chosen), total)
    chosen.sort(key=lambda f: f.id)  # 渲染回 id 升序:注入文本稳定,利缓存
    return "Known facts about the user:\n" + "\n".join(f"- {f.content}" for f in chosen)


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

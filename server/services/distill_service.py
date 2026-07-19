"""Session-end distillation: consolidate a spawn's session signals into ≤8 behavioral
preferences stored in Spawn.memory_facts. Best-effort, background, never raises.

Verdict source: deliverable 👍/👎 verdicts are persisted as DB `Feedback` rows keyed by the
REAL `conversation_id` (see `record_deliverable_verdict` in server/orchestrator/arslan.py),
so they ARE cleanly queryable per (conversation_id, spawn_id). We fold them into the distill
signals alongside conversation material (user messages + the spawn's deliverables from
ArslanMessage). The REST `/feedback` endpoint still writes a degenerate `spawn-{id}` key; those
rows are intentionally excluded here since they aren't tied to a specific conversation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import ArslanMessage, DistilledSession, Feedback, Spawn
from server.services.replay_safety import should_not_curate
from server.orchestrator.json_protocol import parse_json_object
from server.services.llm_factory import build_adapter
from server.services.prompts.distill import DISTILL_SYSTEM
from server.services import recap_service

_META_UPFLOW_SYSTEM = (
    "你是 Arslan 的记忆整理器。只提炼 AT MOST 一条对【所有分身 / Arslan 本身】都有用的元知识——"
    "要么是通用的用户偏好(如「用户偏口语、忌硬广」),要么是领域归属"
    "(如「小红书类内容交给某分身」)。不要提炼只对该分身领域内部有用的细节。"
    "如果没有值得上浮的,返回空字符串。只输出一行纯文本(那条元知识或空),不要解释、不要 JSON、不要引号。"
)

logger = logging.getLogger(__name__)

_MAX_FACTS = 8

#: distilled_sessions.reason written by the curation sweep when it permanently
#: abandons a pair (see server/services/curation_loop.py).
_GAVE_UP_REASON = "curation_gave_up"


async def distill_facts(existing: list[str], signals: str) -> list[str] | None:
    """LLM-consolidate existing prefs + this session's signals → ≤8 prefs. Returns None
    on any failure (LLM error / unparseable / bad shape) so the caller can skip the write
    AND the idempotency marker — a transient failure must not permanently consume the session."""
    user = f"现有偏好:\n{existing}\n\n本次会话信号:\n{signals[:8000]}"
    try:
        adapter = await build_adapter(role="judgment")
        resp = await adapter.chat(system=DISTILL_SYSTEM, user=user)
        parsed = parse_json_object(resp.content or "") or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("distill_facts failed (will retry next session): %s", exc)
        return None
    facts = parsed.get("facts")
    if not isinstance(facts, list):
        # Was a bare `return None` with NO logging at all — a malformed LLM response
        # left literally zero evidence anywhere ("silent warning" understated it).
        logger.warning("distill_facts: LLM returned no usable 'facts' list (got %s)",
                       type(facts).__name__)
        return None
    return [str(f).strip() for f in facts if str(f).strip()][:_MAX_FACTS]


async def distill_meta_upflow(spawn, new_facts: list[str],
                             conversation_id: str | None = None) -> str | None:
    """After per-spawn distillation, bubble ONE cross-spawn META fact up to Arslan's
    user profile. Meta = a user preference OR a domain-ownership hint
    ('X 内容找 <spawn>'). Domain depth stays in the spawn; only meta rises.

    Routes through memory.save_facts(source='upflow', provenance={"source_kind":
    "upflow", "spawn_id": ...}) — the SAME two-phase active-only dedup + mandatory
    provenance + temporal discipline every other fact write gets (brain-P1 Task 3,
    BLOCKER #1: this function used to construct UserFact directly and bypass
    save_facts entirely, so its facts landed with provenance=NULL forever and its
    own ad-hoc containment dedup scanned superseded rows as if they were live).
    Because save_facts owns its own session/commit, this is no longer atomic with
    the caller's spawn.memory_facts + DistilledSession write (a deliberate,
    already-flagged semantic upgrade — see the P1 plan's Task 3 deviation note).

    Returns the fact content actually written, or None: the LLM said nothing
    worth upflowing, OR save_facts's exact-norm dedup merge-bumped an existing
    active row instead of inserting a new one. Best-effort: any exception → None.
    """
    if not new_facts:
        return None
    try:
        from server.orchestrator import memory
        # Active-only existing profile for the prompt ONLY (blind-free generation:
        # the upflow LLM must know what's already known so it doesn't re-propose it).
        # This is STRICTLY BETTER than the old code, which fed the LLM ALL rows
        # including superseded ones (a latent staleness bug). It is NOT a dedup scan:
        # save_facts's active-only two-phase owns dedup — do not re-add one here.
        existing = await memory.list_facts()  # default: active-only
        prompt = (
            f"分身「{spawn.name}」(领域:{spawn.domain_category})刚学到的偏好:\n"
            + "\n".join(f"- {f}" for f in new_facts)
            + "\n\n已有的用户画像(别重复):\n"
            + ("\n".join(f"- {e.content}" for e in existing) if existing else "(空)")
        )
        adapter = await build_adapter(role="judgment")
        resp = await adapter.chat(system=_META_UPFLOW_SYSTEM, user=prompt)
        fact = (resp.content or "").strip().strip('"').strip("「」").strip()
        if not fact:
            return None
        prov = {"source_kind": "upflow", "spawn_id": getattr(spawn, "id", None)}
        if conversation_id:
            # Only when there IS one: an upflowed profile fact used to be permanently
            # untraceable to the conversation that produced it. A None-valued key would
            # just be noise on the direct-call path, so omit it there.
            prov["conversation_id"] = conversation_id
        created = await memory.save_facts(
            [{"content": fact, "source": "upflow"}], provenance=prov,
        )
        return created[0].content if created else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("distill_meta_upflow(spawn=%s) failed: %s", getattr(spawn, "id", "?"), exc)
        return None


@dataclass(frozen=True)
class DistillOutcome:
    """What actually happened to ONE spawn's distillation.

    Replaces a bare ``False`` that meant four different things (already-distilled /
    spawn gone / nothing to distill / LLM failure), which made it impossible for any
    surface to honestly say "distillation FAILED" rather than "nothing happened".
    """

    ok: bool
    reason: str | None = None   # already_distilled|no_spawn|nothing_to_distill|llm_failed|exception
    spawn_id: int | None = None

    #: reasons that mean "we tried and it broke" (vs. a benign skip)
    FAILURE_REASONS = ("llm_failed", "exception")

    @property
    def failed(self) -> bool:
        return not self.ok and self.reason in self.FAILURE_REASONS


@dataclass(frozen=True)
class DistillReport:
    """Per-conversation roll-up: the honest count plus every spawn's outcome."""

    distilled: int
    outcomes: list[DistillOutcome]


async def distill_session(conversation_id: str) -> int:
    """Distill every spawn that produced a deliverable in this conversation. Idempotent
    per (conversation, spawn). Never raises. Returns the number of spawns ACTUALLY
    distilled this call (idle/already-distilled/failed spawns are skipped and NOT counted)
    — so callers (e.g. the manual REST trigger) can report an honest count.

    Signature deliberately unchanged (`-> int`): the REST endpoint, the frontend toast
    (``App.tsx`` reads ``res.distilled_spawns > 0``) and several tests depend on it.
    Callers that need per-spawn detail use :func:`distill_session_detailed`.
    """
    return (await distill_session_detailed(conversation_id)).distilled


async def distill_session_detailed(
    conversation_id: str, *, propose_only: bool = False
) -> DistillReport:
    """distill_session + per-spawn outcomes. Never raises.

    A failed spawn logs a ``distill_failed`` growth event so the failure is VISIBLE on
    the recap timeline instead of dying in a server log. Each spawn is attempted inside
    its own try: before this, one spawn raising aborted the whole loop and left every
    remaining spawn markerless (hence permanently re-attempted) forever.
    """
    if should_not_curate(conversation_id):
        # Synthetic eval/replay traffic is never material to learn from. Until now this
        # was only an accident (replay never persists ArslanMessage rows, so the query
        # below came back empty) — an accident any new caller could break.
        return DistillReport(distilled=0, outcomes=[])
    try:
        async with db_session.AsyncSessionLocal() as db:
            spawn_ids = (await db.execute(
                select(ArslanMessage.spawn_id).where(
                    ArslanMessage.conversation_id == conversation_id,
                    ArslanMessage.role == "spawn_summary",
                    ArslanMessage.spawn_id.isnot(None),
                ).distinct()
            )).scalars().all()
    except Exception as exc:  # noqa: BLE001 — candidate query failure is not a spawn failure
        logger.warning("distill_session(%s) candidate query failed: %s", conversation_id, exc)
        return DistillReport(distilled=0, outcomes=[])

    n = 0
    outcomes: list[DistillOutcome] = []
    for spawn_id in spawn_ids:
        sid = int(spawn_id)
        try:
            outcome = await _distill_one(conversation_id, sid, propose_only=propose_only)
        except Exception as exc:  # noqa: BLE001 — one bad spawn must not abort the rest
            logger.warning("distill_one(%s, %s) raised: %s", conversation_id, sid, exc)
            outcome = DistillOutcome(ok=False, reason="exception", spawn_id=sid)
        outcomes.append(outcome)
        if outcome.ok:
            n += 1
        elif outcome.failed:
            await recap_service.log_event(
                conversation_id, "distill_failed",
                {"spawn_id": sid, "reason": outcome.reason},
                f"蒸馏失败({outcome.reason})· 分身 {sid}")
    return DistillReport(distilled=n, outcomes=outcomes)


async def _distill_one(
    conversation_id: str, spawn_id: int, *, propose_only: bool = False,
    usage_scope: str = "distill",
) -> DistillOutcome:
    """Distill one spawn's material for this conversation.

    Returns a discriminated :class:`DistillOutcome` — ``ok=True`` iff facts were actually
    written (and the idempotency marker persisted); otherwise ``reason`` says which of
    already-distilled / spawn-gone / nothing-to-distill / LLM-failure happened.

    The whole body runs inside ``usage_ledger.scope`` so BOTH LLM calls (the distill
    itself and the meta-upflow) are accounted — distill_service used to be on the
    NOT_COVERED list and burned tokens invisibly. That context manager is fail-open by
    construction: an accounting failure is logged and swallowed, never surfaced here.
    """
    from server.services import usage_ledger

    async with usage_ledger.scope(usage_scope, conversation_id):
        return await _distill_one_inner(
            conversation_id, spawn_id, propose_only=propose_only)


async def _distill_one_inner(
    conversation_id: str, spawn_id: int, *, propose_only: bool = False
) -> DistillOutcome:
    async with db_session.AsyncSessionLocal() as db:
        already = (await db.execute(select(DistilledSession).where(
            DistilledSession.conversation_id == conversation_id,
            DistilledSession.spawn_id == spawn_id))).scalar_one_or_none()
        # A `curation_gave_up` marker means the BACKGROUND sweep abandoned this pair.
        # It is terminal for the sweep (that is what keeps a dead conversation from
        # costing money forever) but it must NOT silence the user: an interactive
        # caller ignores it and, on success, upserts the row back to a normal marker.
        gave_up = already is not None and already.reason == _GAVE_UP_REASON
        if already is not None and not (gave_up and not propose_only):
            return DistillOutcome(ok=False, reason="already_distilled", spawn_id=spawn_id)
        spawn = await db.get(Spawn, spawn_id)
        if spawn is None:
            return DistillOutcome(ok=False, reason="no_spawn", spawn_id=spawn_id)
        deliverables = (await db.execute(select(ArslanMessage.display_content).where(
            ArslanMessage.conversation_id == conversation_id,
            ArslanMessage.role == "spawn_summary",
            ArslanMessage.spawn_id == spawn_id))).scalars().all()
        user_msgs = (await db.execute(select(ArslanMessage.content).where(
            ArslanMessage.conversation_id == conversation_id,
            ArslanMessage.role == "user"))).scalars().all()
        verdicts = (await db.execute(select(Feedback.user_action).where(
            Feedback.session_id == conversation_id,
            Feedback.spawn_id == spawn_id))).scalars().all()
        existing = list(spawn.memory_facts or [])

    # Conversation material + per-conversation 👍/👎 verdict counts (now cleanly queryable).
    ups = sum(1 for v in verdicts if v == "thumbs_up")
    downs = sum(1 for v in verdicts if v == "thumbs_down")
    feedback_line = f"\n\n用户反馈:👍×{ups} 👎×{downs}" if (ups or downs) else ""
    signals = "用户消息:\n" + "\n".join(u for u in user_msgs if u) + \
              "\n\n分身产出:\n" + "\n".join(d for d in deliverables if d) + \
              feedback_line
    if not deliverables and not user_msgs:
        return DistillOutcome(ok=False, reason="nothing_to_distill", spawn_id=spawn_id)

    new_facts = await distill_facts(existing, signals)
    if new_facts is None:
        # write nothing + no marker, so it retries next session
        return DistillOutcome(ok=False, reason="llm_failed", spawn_id=spawn_id)

    async with db_session.AsyncSessionLocal() as db:
        spawn = await db.get(Spawn, spawn_id)
        if spawn is not None:
            spawn.memory_facts = new_facts
            # Best-effort metaknowledge upflow: bubble ONE cross-spawn meta-fact up to
            # Arslan's user profile. A failure here must not break the per-spawn distill.
            # NOTE: save_facts (which this now routes through) owns its own session/
            # commit, independent of this block's — see distill_meta_upflow's docstring.
            await distill_meta_upflow(spawn, new_facts, conversation_id)
        # UPSERT within uq_distilled_conv_spawn: a successful interactive distill
        # replaces a background give-up marker with a normal one.
        existing = (await db.execute(select(DistilledSession).where(
            DistilledSession.conversation_id == conversation_id,
            DistilledSession.spawn_id == spawn_id))).scalar_one_or_none()
        if existing is not None:
            existing.reason = None
        else:
            db.add(DistilledSession(conversation_id=conversation_id, spawn_id=spawn_id))
        await db.commit()
    return DistillOutcome(ok=True, spawn_id=spawn_id)


async def distill_from_signals(
    spawn_id: int, signals: str, *, conversation_id: str | None = None
) -> DistillOutcome:
    """Distill an EPHEMERAL session (sandbox / direct chat) whose transcript lives only
    in memory. Unlike distill_session, takes signals directly (no DB query) and writes no
    DistilledSession marker (each confirm is its own one-shot session). Never raises.

    Returns a :class:`DistillOutcome` — previously `-> None`, which made it impossible
    even in principle for a caller to know whether anything was learned. `complete_chat`
    needs exactly that answer before it archives the source messages.

    ``conversation_id`` is used only to attribute the failure event. The two callers
    that have no real conversation (sandbox merge, direct chat) fall back to the repo's
    existing ``spawn-{id}`` convention — a synthetic key, not a real conversation.
    """
    if should_not_curate(conversation_id):
        return DistillOutcome(ok=False, reason="nothing_to_distill", spawn_id=spawn_id)
    outcome: DistillOutcome
    try:
        async with db_session.AsyncSessionLocal() as db:
            spawn = await db.get(Spawn, spawn_id)
            if spawn is None:
                return DistillOutcome(ok=False, reason="no_spawn", spawn_id=spawn_id)
            existing = list(spawn.memory_facts or [])
        new_facts = await distill_facts(existing, signals)
        if new_facts is None:
            outcome = DistillOutcome(ok=False, reason="llm_failed", spawn_id=spawn_id)
        else:
            async with db_session.AsyncSessionLocal() as db:
                spawn = await db.get(Spawn, spawn_id)
                if spawn is None:
                    outcome = DistillOutcome(ok=False, reason="no_spawn", spawn_id=spawn_id)
                else:
                    spawn.memory_facts = new_facts
                    await db.commit()
                    outcome = DistillOutcome(ok=True, spawn_id=spawn_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("distill_from_signals(spawn=%s) failed: %s", spawn_id, exc)
        outcome = DistillOutcome(ok=False, reason="exception", spawn_id=spawn_id)

    if outcome.failed:
        await recap_service.log_event(
            conversation_id or f"spawn-{spawn_id}", "distill_failed",
            {"spawn_id": spawn_id, "reason": outcome.reason},
            f"蒸馏失败({outcome.reason})· 分身 {spawn_id}")
    return outcome

"""Session-end distillation for an expert: the session's signals become memory PROPOSALS in that expert's
scope (unified memory store). Best-effort, background, never raises.

0.1.63 C2a-2 removed the v1 path, which replaced Spawn.memory_facts outright, bubbled one fact up into the
user profile and filed v1 MemoryProposal rows; no boot reached it once v2 was always active. The expert
code that still calls this goes with C7 / C8.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import ArslanMessage
from server.services.replay_safety import should_not_curate
from server.orchestrator.json_protocol import parse_json_object
from server.services.llm_factory import build_adapter
from server.services.prompts.distill import DISTILL_SYSTEM
from server.services import recap_service

logger = logging.getLogger(__name__)

_MAX_FACTS = 8


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


@dataclass(frozen=True)
class DistillOutcome:
    """What actually happened to ONE spawn's distillation.

    Replaces a bare ``False`` that meant four different things (already-distilled /
    spawn gone / nothing to distill / LLM failure), which made it impossible for any
    surface to honestly say "distillation FAILED" rather than "nothing happened".
    """

    ok: bool
    # already_distilled|no_spawn|nothing_to_distill|llm_failed|write_failed|exception
    reason: str | None = None
    spawn_id: int | None = None
    proposed: int = 0

    #: reasons that mean "we tried and it broke" (vs. a benign skip)
    #: "we tried and it broke" — each of these must produce a visible event.
    #: write_failed included: a proposal that could not be filed is material LOST, not
    #: a benign skip.
    FAILURE_REASONS = ("llm_failed", "exception", "write_failed")

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
    conversation_id: str, *, propose_only: bool = False,
    usage_scope: str = "distill",
) -> DistillReport:
    """distill_session + per-spawn outcomes. Never raises.

    ``usage_scope`` names the ledger bucket. Its only non-default caller was the
    curation sweep (``curation_distill``), deleted in C8-3 (v0.1.63), so every caller
    now passes the defaults for both ``usage_scope`` and ``propose_only``.
    DELETE-BY: C8-4, which removes both parameters.

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
            outcome = await _distill_one(conversation_id, sid, propose_only=propose_only,
                                         usage_scope=usage_scope)
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
    # 0.1.63 C2a-2: v2 only (every boot activates it). `propose_only` meant "file a v1 proposal instead of
    # writing"; v2 distillation only ever proposes, so it changes nothing here.
    return await _distill_v2(spawn_id, conversation_id=conversation_id)


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
    from server.services import usage_ledger

    # Ledgered like the session path: three of the five distill trigger paths
    # (dual-track, sandbox merge, direct chat) come through here, so wrapping only
    # _distill_one would have made "distill_service is accounted" a false claim.
    async with usage_ledger.scope("distill", conversation_id or f"spawn-{spawn_id}"):
        return await _distill_from_signals_inner(spawn_id, signals, conversation_id)


async def _distill_from_signals_inner(
    spawn_id: int, signals: str, conversation_id: str | None
) -> DistillOutcome:
    return await _distill_v2(spawn_id, signals=signals, conversation_id=conversation_id)


async def _distill_v2(spawn_id: int, *, signals: str | None = None,
                      conversation_id: str | None = None) -> DistillOutcome:
    """Distillation produces individual proposals, never replaces an expert array."""
    from dataclasses import replace
    from arslan.companion.memory import MemoryError, MemoryScope, MemoryWrite
    from server.services.memory_repository import repository
    from server.services.personal_context import current
    ctx = current()
    if ctx is None or ctx.no_learning or ctx.temporary:
        return DistillOutcome(ok=False, reason="learning_disabled", spawn_id=spawn_id)
    # The judgment provider can differ from the answer provider. Do not infer
    # that it is local from the main task's model_is_local flag.
    if not ctx.cloud_memory_allowed:
        return DistillOutcome(ok=False, reason="cloud_memory_permission_required", spawn_id=spawn_id)
    if ctx.expert_id != str(spawn_id):
        return DistillOutcome(ok=False, reason="memory_scope_denied", spawn_id=spawn_id)
    if signals is None:
        if not conversation_id or conversation_id != ctx.conversation_id:
            return DistillOutcome(ok=False, reason="memory_scope_denied", spawn_id=spawn_id)
        async with db_session.AsyncSessionLocal() as db:
            messages = (await db.execute(select(ArslanMessage).where(
                ArslanMessage.conversation_id == conversation_id,
                (ArslanMessage.role == "user") | ((ArslanMessage.role == "spawn_summary") &
                                                (ArslanMessage.spawn_id == spawn_id)),
            ).order_by(ArslanMessage.id))).scalars().all()
        signals = "\n".join(f"{message.role}: {message.content}" for message in messages)
    if not signals.strip():
        return DistillOutcome(ok=False, reason="nothing_to_distill", spawn_id=spawn_id)
    facts = await distill_facts([], signals)
    if facts is None:
        return DistillOutcome(ok=False, reason="llm_failed", spawn_id=spawn_id)
    proposed = 0
    actor = replace(ctx.actor("extractor"), expert_id=str(spawn_id))
    for fact in facts:
        try:
            async with repository() as repo:
                result = await repo.create(MemoryWrite(content=fact,
                    scope=MemoryScope(kind="expert", id=str(spawn_id))), actor)
                proposed += int(result["status"] == "proposed" and not result.get("deduplicated"))
        except MemoryError as exc:
            if exc.code not in {"credentials_not_memory", "memory_source_deleted", "memory_previously_deleted"}:
                return DistillOutcome(ok=False, reason="write_failed", spawn_id=spawn_id, proposed=proposed)
    # Do not report "learned" or archive a source merely because a proposal exists.
    return DistillOutcome(ok=False, reason="confirmation_required" if proposed else "nothing_to_distill",
                          spawn_id=spawn_id, proposed=proposed)

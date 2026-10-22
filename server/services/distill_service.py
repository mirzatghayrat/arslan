"""Distillation for an expert: a direct chat's signals become memory PROPOSALS in that expert's scope
(unified memory store). Best-effort, never raises.

0.1.63 C2a-2 removed the v1 path, which replaced Spawn.memory_facts outright, bubbled one fact up into the
user profile and filed v1 MemoryProposal rows; no boot reached it once v2 was always active. C8-4 removed
the session-end entry (distill_session and its per-conversation roll-up), which the `session_ended` frame
started. What is left serves the spawns `complete-chat` route only.
DELETE-BY: v0.1.64, with that route (expert REST), together with prompts/distill.py.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from server.services.replay_safety import should_not_curate
from server.orchestrator.json_protocol import parse_json_object
from server.services.llm_factory import build_adapter
from server.services.prompts.distill import DISTILL_SYSTEM

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


async def distill_from_signals(
    spawn_id: int, signals: str, *, conversation_id: str | None = None
) -> DistillOutcome:
    """Distill an EPHEMERAL session (sandbox / direct chat) whose transcript lives only
    in memory: takes signals directly (no DB query) and writes no DistilledSession marker
    (each confirm is its own one-shot session). Never raises.

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

    # Ledgered: an LLM call made here must show up in the usage summary.
    async with usage_ledger.scope("distill", conversation_id or f"spawn-{spawn_id}"):
        return await _distill_from_signals_inner(spawn_id, signals, conversation_id)


async def _distill_from_signals_inner(
    spawn_id: int, signals: str, conversation_id: str | None
) -> DistillOutcome:
    return await _distill_v2(spawn_id, signals=signals, conversation_id=conversation_id)


async def _distill_v2(spawn_id: int, *, signals: str,
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

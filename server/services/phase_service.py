"""Staged-orchestration phase state per conversation (one pending proposal at a time)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import delete, select

from server.db import session as db_session
from server.db.models import SpawnPhase

logger = logging.getLogger(__name__)


# Sentinel spawn_id for pre-spawn phases (clarifying, gathering): no spawn exists yet.
# The spawn_phases.spawn_id column is NOT NULL and carries no FK to spawns, so a 0
# sentinel is safe (no migration).
_CLARIFYING_SPAWN_ID = 0


async def _upsert_phase(conversation_id: str, *, spawn_id: int, phase: str, direction: str) -> None:
    """Clear any existing pending row for the conversation, then insert one
    (one pending phase per conversation)."""
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(
            delete(SpawnPhase).where(SpawnPhase.conversation_id == conversation_id)
        )
        db.add(
            SpawnPhase(
                conversation_id=conversation_id,
                spawn_id=spawn_id,
                phase=phase,
                direction=direction,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        await db.commit()


async def set_proposing(conversation_id: str, spawn_id: int, direction: str) -> None:
    """Upsert: clear any existing pending proposal for the conversation, then insert."""
    await _upsert_phase(conversation_id, spawn_id=spawn_id, phase="proposing", direction=direction)


async def set_clarifying(conversation_id: str) -> None:
    """Pin a 'clarifying' create phase for the conversation. While active, the
    turn model suppresses routing to existing spawns so the follow-up keeps
    clarifying.

    Retained only for the legacy "clarifying" phase value: the staffing spine
    no longer invokes this — it uses `set_gathering` (slot-based) instead. The
    turn model still recognizes the "clarifying" phase for backward compatibility.
    """
    await _upsert_phase(conversation_id, spawn_id=_CLARIFYING_SPAWN_ID, phase="clarifying", direction="")


async def clear_clarifying(conversation_id: str) -> None:
    """Clear a clarifying phase (alias of clear for call-site readability)."""
    await clear(conversation_id)


async def get_pending(conversation_id: str) -> dict | None:
    """Return the pending proposal for the conversation, or None if none exists."""
    async with db_session.AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(SpawnPhase).where(SpawnPhase.conversation_id == conversation_id)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return {"spawn_id": row.spawn_id, "phase": row.phase, "direction": row.direction}


async def clear(conversation_id: str, spawn_id: int | None = None) -> None:
    """Remove the pending proposal for the conversation."""
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(
            delete(SpawnPhase).where(SpawnPhase.conversation_id == conversation_id)
        )
        await db.commit()


async def set_inviting(
    conversation_id: str, spawn_id: int, *, task_brief: str, user_message: str,
    needs_proposal: bool = False, announced: bool = False, answered: bool = False,
) -> None:
    """Persist a pending roster invite for the conversation.

    The router wanted to route to `spawn_id`, but that spawn is NOT yet in the
    roster — so instead of auto-joining we proposed an invite card and parked the
    task here. On Accept the WS handler reads this back (via `get_pending_invite`),
    joins the spawn, and dispatches the stored task — in the SAME mode a roster-member
    route would have used (propose-mode when `needs_proposal`, else execute). The
    `needs_proposal` flag captured at route time is carried so the accept handler
    re-makes the exact same propose-vs-execute decision. Uses the sentinel spawn_id=0
    row (same as clarifying/gathering) and stows the real payload in `direction`
    as JSON, so no new column is needed.

    `answered` (delegation route-to-member, cell 6): TRUE marks a RECRUITING invite —
    Arslan already fully answered the task doer-first, so Accept must ONLY enroll the
    spawn into this session's roster (the user can then @ it directly) and must NOT
    re-dispatch the already-answered task. The key is written ONLY when True so pre-existing parks (staffing / cell 2,
    which carry an UNanswered task that Accept must still dispatch) keep their exact
    payload shape — the accept side reads `pending.get("answered")`, falsy for those.
    """
    payload = {
        "spawn_id": spawn_id, "task_brief": task_brief, "user_message": user_message,
        "needs_proposal": bool(needs_proposal), "announced": bool(announced),
    }
    if answered:
        payload["answered"] = True
    await _upsert_phase(
        conversation_id,
        spawn_id=_CLARIFYING_SPAWN_ID,
        phase="inviting",
        direction=json.dumps(payload, ensure_ascii=False),
    )


async def set_choosing(
    conversation_id: str, *, candidates: list[dict], task_brief: str,
    user_message: str, needs_proposal: bool = False,
) -> None:
    """Persist a pending member-picker choice (delegation route-to-member, cell 5).

    The inferred route was AMBIGUOUS across ≥2 roster members (picker band), so instead
    of silently dispatching the router's guess we emit an `ask_user_choice` card and park
    the candidate members + the task here. The user's pick (the chosen member's name, sent
    back as a normal message by the clarify_options card) is matched against `candidates`
    on the next turn and dispatched to that member with the parked `task_brief`. Uses the
    sentinel spawn_id=0 row + JSON `direction`, same as the other pre-spawn phases.

    `candidates` is a list of {spawn_id, name} (extra keys are ignored/kept).
    """
    payload = {
        "candidates": [{"spawn_id": c.get("spawn_id"), "name": c.get("name")}
                       for c in candidates],
        "task_brief": task_brief, "user_message": user_message,
        "needs_proposal": bool(needs_proposal),
    }
    await _upsert_phase(
        conversation_id,
        spawn_id=_CLARIFYING_SPAWN_ID,
        phase="choosing",
        direction=json.dumps(payload, ensure_ascii=False),
    )


async def get_pending_choice(conversation_id: str) -> dict | None:
    """Return the pending member-picker payload `{candidates, task_brief, user_message,
    needs_proposal}`, or None if there is no active `choosing` phase / corrupt JSON."""
    pending = await get_pending(conversation_id)
    if not pending or pending.get("phase") != "choosing":
        return None
    try:
        return json.loads(pending.get("direction") or "{}")
    except Exception:  # noqa: BLE001
        logger.warning("choice: corrupted choice JSON for %s", conversation_id)
        return None


async def get_pending_invite(conversation_id: str) -> dict | None:
    """Return the pending invite payload `{spawn_id, task_brief, user_message,
    needs_proposal}`, or None if there is no active `inviting` phase / corrupt JSON."""
    pending = await get_pending(conversation_id)
    if not pending or pending.get("phase") != "inviting":
        return None
    try:
        return json.loads(pending.get("direction") or "{}")
    except Exception:  # noqa: BLE001
        logger.warning("invite: corrupted invite JSON for %s", conversation_id)
        return None


async def set_gathering(conversation_id: str, slots: dict) -> None:
    """Persist accumulating gather slots as JSON in the direction column.

    Uses the sentinel spawn_id=0 (same as set_clarifying) — no new column needed.
    """
    await _upsert_phase(
        conversation_id,
        spawn_id=_CLARIFYING_SPAWN_ID,
        phase="gathering",
        direction=json.dumps(slots, ensure_ascii=False),
    )


async def get_gathered_slots(conversation_id: str) -> dict:
    """Return the accumulated slots for a gathering phase, or {} if none / wrong phase."""
    pending = await get_pending(conversation_id)
    if not pending or pending.get("phase") != "gathering":
        return {}
    try:
        return json.loads(pending.get("direction") or "{}")
    except Exception:  # noqa: BLE001
        logger.warning("gather: corrupted slot JSON for %s", conversation_id)
        return {}

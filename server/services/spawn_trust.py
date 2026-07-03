"""Deterministic spawn trust/maturity signal (spec: boundary/harness round).

Pure aggregation over the Feedback table — a spawn graduates green -> trusted once
it has a real track record. No ML, no LLM. Consumed by the routing gate (only route
to trusted spawns) and by suggestion-chip wording (green = 'let X practice').
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.models import Feedback

# Graduation thresholds (v1; central + easy to tune).
MIN_TASKS = 3          # distinct conversations the spawn has worked in
MIN_ACCEPT_RATE = 0.6  # thumbs_up / (thumbs_up + thumbs_down)


async def trust(session: AsyncSession, spawn_id: int) -> dict:
    """Return {"band": "green"|"trusted", "tasks": int, "accept_rate": float}.

    tasks = distinct session_id the spawn has feedback in.
    accept_rate = up / (up + down); 0.0 when no up/down verdicts yet.
    trusted iff tasks >= MIN_TASKS AND accept_rate >= MIN_ACCEPT_RATE.
    """
    tasks = (await session.execute(
        select(func.count(func.distinct(Feedback.session_id)))
        .where(Feedback.spawn_id == spawn_id)
    )).scalar() or 0
    up = (await session.execute(
        select(func.count()).where(Feedback.spawn_id == spawn_id,
                                   Feedback.user_action == "thumbs_up")
    )).scalar() or 0
    down = (await session.execute(
        select(func.count()).where(Feedback.spawn_id == spawn_id,
                                   Feedback.user_action == "thumbs_down")
    )).scalar() or 0
    accept_rate = (up / (up + down)) if (up + down) else 0.0
    band = "trusted" if (tasks >= MIN_TASKS and accept_rate >= MIN_ACCEPT_RATE) else "green"
    return {"band": band, "tasks": int(tasks), "accept_rate": round(accept_rate, 3)}

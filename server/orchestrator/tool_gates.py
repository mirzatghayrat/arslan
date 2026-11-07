"""What a gate tells the model when a card can't be shown or says no (LOOP1 c2)."""
from __future__ import annotations


def _declined(refused: str, subject: str) -> str:
    """What a "no" from a card tells the model (0.1.61): the decision's own text when there is
    one (the user's note, or "nobody answered — NOT a refusal"), never "declined" for a card
    that simply ran out (seen 2026-10-04 on a phone task)."""
    from server.services import approvals, permissions
    decision = permissions.LAST_DECISION.get()
    if decision is not None and not decision.allowed and decision.model_text:
        return decision.model_text
    if approvals.LAST_OUTCOME.get() == "expired":
        return (f"Nobody answered the card for {subject} in 30 minutes. This is NOT a refusal. "
                "Don't retry it in this turn. Finish what you can and tell the user what is waiting.")
    return refused


async def _unattended(error: str, req, conversation_id: str | None) -> str:
    """S1 (U14 c): a step refused for want of a card callback. With nobody to ask (a scheduled run) the
    refusal is listed in the Inbox and the model is told what decide() tells it; a turn with someone to
    ask (none today lacks the callback) keeps `error` and writes no row."""
    from server.services import background_jobs, permissions
    if permissions.current_asker() is not None:
        return error
    return await permissions.refuse_unattended(
        req, permissions.Context(conversation_id, job_id=background_jobs._inside_job.get()))

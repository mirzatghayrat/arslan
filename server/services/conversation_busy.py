"""Whether anything runs in a conversation (#490 review), for the endpoints that change what a conversation is or
how it remembers: turning a quick question into a chat (server/api/phone.py) and the window's context switches
(server/api/companion.py).

A chat turn holds the conversation's turn lock from before it loads its context and stores its message, and it
registers its run only later, so the lock is what covers that window; a background job or a task may run on after
a turn ends. turn_undo keeps its own check: it asks about one turn's runs and tasks, not the conversation's.
"""
from __future__ import annotations

from sqlalchemy import select

from server.db.task_models import CompanionTask


async def busy(db, conversation_id: str, *, holding_lock: bool = False) -> bool:
    from server.services import background_jobs, run_registry
    from server.ws import arslan as ws_arslan
    lock = ws_arslan._turn_locks.get(conversation_id)
    if (not holding_lock and lock is not None and lock.locked()) or run_registry.active_for(conversation_id):
        return True
    if any(job.phase != "finished" for job in background_jobs.jobs_for(conversation_id)):
        return True
    return bool(await db.scalar(select(CompanionTask.id).where(
        CompanionTask.conversation_id == conversation_id, CompanionTask.phase.in_(("running", "verifying"))).limit(1)))

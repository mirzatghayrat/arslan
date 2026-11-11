"""Background jobs (0.1.42): what is running now, and a stop button.

Jobs live in memory beside the tasks that record them; this surface only
reads that list and cancels by id. Starting a job is Arslan's call, made in
the conversation, so there is deliberately no POST to create one.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth import require_auth
from server.db.session import get_session
from server.services import background_jobs, sub_sessions

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/background-jobs")
async def list_jobs(conversation_id: str | None = None, db: AsyncSession = Depends(get_session)):
    jobs = [job for job in background_jobs._jobs.values()
            if conversation_id is None or job.conversation_id == conversation_id]
    if conversation_id is None:         # SUB2: the sidebar's list. A sub-session is opened from its parent.
        subs = await sub_sessions.sub_ids(db, [job.conversation_id for job in jobs])
        jobs = [job for job in jobs if job.conversation_id not in subs]
    return {"active": background_jobs.active_count(), "jobs": [job.frame() for job in jobs]}


@router.post("/background-jobs/{job_id}/stop")
async def stop_job(job_id: str, db: AsyncSession = Depends(get_session)):
    """SUB5: a sub-session's job stops the sub-sessions under it too (`sub_sessions.stop_job`). The island's one entry
    for a commander's sub-sessions names them all (`sub_sessions.STOP_ALL`): they all stop, at any depth
    (`sub_sessions.stop_commander`), 409 when none is at work."""
    if job_id.startswith(sub_sessions.STOP_ALL):
        if not await sub_sessions.stop_commander(db, job_id.removeprefix(sub_sessions.STOP_ALL)):
            raise HTTPException(409, detail={"code": "job_not_running"})
        return {"ok": True}
    job = background_jobs._jobs.get(job_id)
    if job is None:
        raise HTTPException(404, detail={"code": "job_not_found"})
    if not background_jobs.stop(job.conversation_id, job_id):
        raise HTTPException(409, detail={"code": "job_not_running"})
    await sub_sessions.stop_job(db, job)
    return {"ok": True}

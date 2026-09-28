"""Background jobs (0.1.42): what is running now, and a stop button.

Jobs live in memory beside the tasks that record them; this surface only
reads that list and cancels by id. Starting a job is Arslan's call, made in
the conversation, so there is deliberately no POST to create one.
"""
from fastapi import APIRouter, Depends, HTTPException

from server.auth import require_auth
from server.services import background_jobs

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/background-jobs")
async def list_jobs(conversation_id: str | None = None):
    jobs = [job for job in background_jobs._jobs.values()
            if conversation_id is None or job.conversation_id == conversation_id]
    return {"active": background_jobs.active_count(), "jobs": [job.frame() for job in jobs]}


@router.post("/background-jobs/{job_id}/stop")
async def stop_job(job_id: str):
    job = background_jobs._jobs.get(job_id)
    if job is None:
        raise HTTPException(404, detail={"code": "job_not_found"})
    if not background_jobs.stop(job.conversation_id, job_id):
        raise HTTPException(409, detail={"code": "job_not_running"})
    return {"ok": True}

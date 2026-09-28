"""Host-only recovery reads, bound to the current trusted Task identity."""
from server.services import task_service
from server.services.task_repository import TaskError


class TaskProgressExecutor:
    key = "task_progress"

    async def execute(self, args: dict) -> dict:
        if not isinstance(args, dict) or set(args) - {"run_id"}:
            return {"ok": False, "error_code": "invalid_task_progress_arguments"}
        run_id = args.get("run_id")
        if run_id is not None and (not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1):
            return {"ok": False, "error_code": "invalid_task_progress_arguments"}
        try:
            return await task_service.progress_for_current(run_id)
        except TaskError as exc:
            return {"ok": False, "error_code": exc.code}


class DelegateWorkExecutor:
    key = "delegate_work"

    async def execute(self, args: dict) -> dict:
        from pydantic import ValidationError
        from server.orchestrator.arslan import _arslan_tools
        from server.services import task_workers
        try:
            return await task_workers.delegate(task_workers.Batch.model_validate(args), _arslan_tools)
        except ValidationError:
            return {"ok": False, "error_code": "invalid_worker_arguments"}
        except TaskError as exc:
            return {"ok": False, "error_code": exc.code}


def _conversation_id() -> str | None:
    from server.services import personal_context
    ctx = personal_context.current()
    return ctx.conversation_id if ctx is not None else None


class StartBackgroundWorkExecutor:
    """0.1.42: hand a piece of work to a background job; the turn ends at once."""
    key = "start_background_work"

    async def execute(self, args: dict) -> dict:
        from server.services import background_jobs
        conversation_id = _conversation_id()
        if conversation_id is None or background_jobs.inside_job():
            return {"ok": False, "error_code": "background_unavailable"}
        goal, criteria = (args or {}).get("goal"), (args or {}).get("criteria") or []
        if not isinstance(goal, str) or not goal.strip() or not isinstance(criteria, list):
            return {"ok": False, "error_code": "invalid_background_arguments"}
        waiting = background_jobs.active_count() >= background_jobs.MAX_CONCURRENT
        job = await background_jobs.start(conversation_id, goal,
                                          [c for c in criteria if isinstance(c, dict)])
        return {"ok": True, "external": False, "job_id": job.job_id, "queued": waiting,
                "criteria": [c["description"] for c in job.acceptance if c["id"] != "answer-delivered"],
                "note": "The job runs after this turn. Reply in one sentence; do not do the work here."}


class BackgroundStatusExecutor:
    key = "background_status"

    async def execute(self, args: dict) -> dict:
        from server.services import background_jobs
        conversation_id = _conversation_id()
        if conversation_id is None:
            return {"ok": False, "error_code": "background_unavailable"}
        return {"ok": True, "external": False, "jobs": [
            {k: v for k, v in job.frame().items() if k not in {"type", "conversation_id"}}
            for job in background_jobs.jobs_for(conversation_id)]}


class StopBackgroundWorkExecutor:
    key = "stop_background_work"

    async def execute(self, args: dict) -> dict:
        from server.services import background_jobs
        conversation_id, job_id = _conversation_id(), (args or {}).get("job_id")
        if conversation_id is None or not isinstance(job_id, str):
            return {"ok": False, "error_code": "invalid_background_arguments"}
        return {"ok": background_jobs.stop(conversation_id, job_id), "external": False}

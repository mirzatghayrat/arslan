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

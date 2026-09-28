"""Background work: the conversation stays free while a job runs (0.1.42).

The host starts a job with `start_background_work` and ends its turn in one
sentence. The job runs in a CLEAN context (no inherited turn, budget or memory
binding) as a durable task with driver `background` and acceptance criteria
drafted by the host, through the same native tool loop, validation and repair
as a turn. Its progress is a card, not a stream: nothing it produces is typed
into the chat while the user keeps talking. When it ends, its result is posted
to the conversation as one message, the desktop shell is told (notification /
menu bar) and a short spoken line is offered to voice mode.

Outcomes the user sees are exactly four: done, partial, blocked, stopped.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import time
import uuid
from dataclasses import dataclass, field, replace

from server.services import desktop_status, run_registry

logger = logging.getLogger(__name__)

MAX_CONCURRENT = 3
MAX_CRITERIA = 5
_inside_job: contextvars.ContextVar[str | None] = contextvars.ContextVar("background_job", default=None)
_slots: asyncio.Semaphore | None = None


def inside_job() -> bool:
    return _inside_job.get() is not None


@dataclass
class Job:
    job_id: str
    conversation_id: str
    goal: str
    acceptance: list[dict]
    phase: str = "queued"             # queued | running | finished
    step: str | None = None
    outcome: str | None = None        # done | partial | blocked | stopped
    detail: str | None = None
    results: dict = field(default_factory=dict)   # check_id -> status
    started_at: float = field(default_factory=time.time)
    task: asyncio.Task | None = field(default=None, repr=False)

    def frame(self) -> dict:
        return {"type": "job_update", "job_id": self.job_id, "conversation_id": self.conversation_id,
                "goal": self.goal, "phase": self.phase, "step": self.step, "outcome": self.outcome,
                "detail": self.detail,
                "criteria": [{"id": c["id"], "description": c["description"],
                              "status": self.results.get(c["id"], "pending")}
                             for c in self.acceptance if c["id"] != "answer-delivered"]}


_jobs: dict[str, Job] = {}


def criteria_to_acceptance(criteria: list[dict]) -> list[dict]:
    """Host-drafted criteria → AcceptanceCheck dicts.

    Checkable kinds become deterministic rules; anything else is a non-critical
    model check. `answer-delivered` is always first, so every job has at least
    one non-model check and an empty result can never pass.
    """
    from server.services.task_service import ANSWER_DELIVERED
    checks = [dict(ANSWER_DELIVERED)]
    for index, item in enumerate(criteria[:MAX_CRITERIA], start=1):
        description = " ".join(str(item.get("description") or "").split())[:300]
        if not description:
            continue
        kind, target = item.get("kind"), item.get("target")
        check = {"id": f"criterion-{index}", "description": description, "evaluator": "model"}
        if kind == "file_saved" and isinstance(target, str) and target.strip():
            check.update(evaluator="deterministic", rule={"kind": "artifact", "target": target.strip()[:240]})
        elif kind == "sources_read":
            minimum = item.get("minimum")
            check.update(evaluator="deterministic", rule={"kind": "research_sources",
                         "minimum": minimum if isinstance(minimum, int) and 1 <= minimum <= 20 else 1})
        elif kind == "mentions" and isinstance(target, str) and target.strip():
            check.update(evaluator="deterministic", rule={"kind": "text", "contains": [target.strip()[:200]]})
        checks.append(check)
    return checks


def outcome_of(phase: str, results: dict, reason: str | None) -> str:
    """The one word the user sees. Only a task the validator marked succeeded is done."""
    if phase == "succeeded":
        return "done"
    if phase == "cancelled":
        return "stopped"
    user_checks = {k: v for k, v in results.items() if k != "answer-delivered"}
    if any(v == "passed" for v in user_checks.values()) and results.get("answer-delivered") == "passed":
        return "partial"
    return "blocked"


def jobs_for(conversation_id: str) -> list[Job]:
    return [job for job in _jobs.values() if job.conversation_id == conversation_id]


def active_count() -> int:
    return sum(job.phase != "finished" for job in _jobs.values())


async def start(conversation_id: str, goal: str, criteria: list[dict]) -> Job:
    goal = " ".join(goal.split())[:4000]
    if not goal:
        raise ValueError("background_goal_required")
    job = Job(job_id=f"job-{uuid.uuid4()}", conversation_id=conversation_id, goal=goal,
              acceptance=criteria_to_acceptance(criteria))
    _jobs[job.job_id] = job
    # A clean context: the job must not inherit the starting turn's task,
    # budget, memory lease or save authority.
    job.task = asyncio.get_running_loop().create_task(_run(job), context=contextvars.Context())
    _emit(job)
    return job


def stop(conversation_id: str, job_id: str) -> bool:
    job = _jobs.get(job_id)
    if job is None or job.conversation_id != conversation_id or job.phase == "finished" or job.task is None:
        return False
    job.task.cancel()
    return True


def _emit(job: Job) -> None:
    run_registry.make_emit(job.conversation_id)(job.frame())


def _job_sink(job: Job, downstream):
    def sink(event: dict) -> None:
        kind = event.get("type")
        if kind in {"stream_start", "stream_chunk", "stream_end", "task_state"}:
            # Never typed into the chat while the user talks, and never mistaken
            # for the conversation's own turn state: the job_update card says it.
            return
        if kind in {"tool_call", "tool_result"} and event.get("tool"):
            if job.step != event["tool"]:
                job.step = event["tool"]
                _emit(job)
        downstream(event)
    return sink


async def _run(job: Job) -> None:
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(MAX_CONCURRENT)
    token = _inside_job.set(job.job_id)
    final_text, phase, reason = "", "failed", "task_execution_failed"
    try:
        async with _slots:
            job.phase = "running"
            _emit(job)
            final_text, phase, reason = await _execute(job)
    except asyncio.CancelledError:
        phase, reason = "cancelled", None
    except Exception as exc:  # noqa: BLE001 — a job failure is reported, never raised into the loop
        logger.warning("background job %s failed: %s %s", job.job_id, type(exc).__name__,
                       getattr(exc, "code", ""))
    finally:
        _inside_job.reset(token)
        job.phase = "finished"
        job.outcome = outcome_of(phase, job.results, reason)
        job.detail = reason
        _emit(job)
        await _report(job, final_text)


async def _execute(job: Job) -> tuple[str, str, str | None]:
    from server.orchestrator import arslan
    from server.services import approvals, host_run, personal_context, task_context, task_service
    from server.services.task_repository import repository
    ctx = await task_context.load(job.conversation_id, user_message=job.goal)
    ctx = replace(ctx, task_id=job.job_id, run_id=f"job-{job.job_id}", explicit_save_digest=None,
                  explicit_save_ref=None, allow_global_save=False)
    confirmations = approvals.JobConfirmations(job.conversation_id)
    downstream = run_registry.make_emit(job.conversation_id)

    async def function(conversation_id, instruction, emit):
        async def body(sink):
            return await arslan.background_body(conversation_id, instruction, _job_sink(job, sink), confirmations)
        return await host_run.execute(conversation_id, instruction, emit, body, announce=False)

    with personal_context.bind(ctx), desktop_status.working(job.conversation_id):
        try:
            output = await task_service.run_turn(function, job.conversation_id, job.goal,
                                                 _job_sink(job, downstream), _driver={"kind": "background"},
                                                 _acceptance=job.acceptance)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — the task row records the failure; read it below
            logger.exception("background job %s execution raised %s %s", job.job_id, type(exc).__name__,
                             getattr(exc, "code", ""))
            output = None
    async with repository() as repo:
        row = await repo.get(job.job_id)
        for result in row.results or ():
            job.results[result.get("check_id")] = result.get("status")
        text = output if isinstance(output, str) else (output or {}).get("final") if isinstance(output, dict) else ""
        return text or "", row.phase, row.pause_reason


async def _report(job: Job, text: str) -> None:
    """Post the result, tell the shell, offer voice mode one line. Best-effort."""
    from server.orchestrator import memory
    from server.ws import protocol
    try:
        body = text.strip()
        if body:   # a stopped or empty job is shown by its card alone, never by a filler message
            message_id = await memory.add_message(job.conversation_id, "arslan", body)
            run_registry.make_emit(job.conversation_id)(protocol.message(message_id, body, "arslan") | {
                "job_id": job.job_id, "outcome": job.outcome})
    except Exception as exc:  # noqa: BLE001
        logger.warning("background job %s result not posted: %s", job.job_id, type(exc).__name__)
    desktop_status.push("turn_finished", conversation_id=job.conversation_id,
                        outcome={"done": "ok", "stopped": "cancelled"}.get(job.outcome, "needs_review"))
    run_registry.make_emit(job.conversation_id)({"type": "job_spoken", "job_id": job.job_id,
                                                 "outcome": job.outcome, "goal": job.goal[:200]})


def _reset_for_tests() -> None:
    global _slots
    for job in _jobs.values():
        if job.task is not None and not job.task.done():
            job.task.cancel()
    _jobs.clear()
    _slots = None

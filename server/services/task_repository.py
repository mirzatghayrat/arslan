"""Transactional Task/Run state, not a replay engine.

Every live mutation is fenced by its attempt ID and a row version. A checkpoint
contains references and counters, never tool arguments, prompts or credentials.
Unknown external effects are reconciled before another attempt may start.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError

from arslan.companion.content_policy import contains_credential, contains_credential_data
from arslan.companion.contracts import (
    CheckResult, Contract, Identifier, ResourceRef, TaskSpec, TaskState,
)
from arslan.execution_budget import Budget
from server.db import session as db_session
from server.db.models import (
    CompanionTask, Project, Run, TaskAction, TaskAttempt, TaskCheckpoint, TaskEvent, TaskRevision, TaskWorker,
)


class TaskError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class Progress(Contract):
    completed_steps: tuple[Identifier, ...] = Field(default=(), max_length=1000)
    evidence: tuple[ResourceRef, ...] = Field(default=(), max_length=1000)
    artifacts: tuple[ResourceRef, ...] = Field(default=(), max_length=1000)
    pending_actions: tuple[Identifier, ...] = Field(default=(), max_length=1000)
    continuation_ref: ResourceRef | None = None
    loop_fingerprints: tuple[Identifier, ...] = Field(default=(), max_length=256)
    validation_repairs: tuple[Identifier, ...] = Field(default=(), max_length=2)


def identity() -> str:
    return str(uuid4())


@asynccontextmanager
async def repository():
    async with db_session.AsyncSessionLocal() as db:
        try:
            yield TaskRepository(db)
            await db.commit()
        except (OperationalError, IntegrityError) as exc:
            await db.rollback()
            if isinstance(exc, IntegrityError) or any(word in str(exc.orig).lower() for word in ("locked", "busy")):
                raise TaskError("task_version_conflict") from exc
            raise
        except BaseException:
            await db.rollback()
            raise


class TaskRepository:
    def __init__(self, db):
        self.db = db

    async def get(self, task_id: str, *, owner_id="local") -> CompanionTask:
        row = await self.db.get(CompanionTask, task_id)
        if row is None or row.owner_id != owner_id:
            raise TaskError("task_not_found")
        return row

    async def spec(self, row: CompanionTask) -> TaskSpec:
        revision = await self.db.get(TaskRevision, (row.id, row.spec_revision))
        if revision is None:
            raise TaskError("task_revision_missing")
        return TaskSpec.model_validate(revision.spec)

    async def present(self, row: CompanionTask) -> dict:
        spec = await self.spec(row)
        state = TaskState(
            task_id=row.id, spec_revision=row.spec_revision, run_id=row.attempt_id,
            sequence=row.sequence, phase=row.phase, checkpoint_ref=row.checkpoint_id,
            results=tuple(CheckResult.model_validate(item) for item in row.results),
            updated_at=row.updated_at.replace(tzinfo=timezone.utc),
        ).validated_for(spec)
        return {"version": row.version, "conversation_id": row.conversation_id,
                "spec": spec.model_dump(mode="json"), "state": state.model_dump(mode="json"),
                "budget": row.budget, "pause_reason": row.pause_reason,
                "cancel_requested": row.cancel_requested}

    async def create(self, spec: TaskSpec, conversation_id: str, *, owner_id="local",
                     budget_snapshot: dict | None = None, privacy: dict | None = None) -> dict:
        if spec.scope.owner_id != owner_id:
            raise TaskError("task_scope_denied")
        if spec.memory_mode == "temporary":
            raise TaskError("temporary_task_not_persisted")
        if not conversation_id.strip() or len(conversation_id) > 100:
            raise TaskError("invalid_conversation_id")
        if contains_credential(spec.model_dump_json()):
            raise TaskError("credentials_not_task_data")
        if spec.scope.project_id:
            project = await self.db.get(Project, spec.scope.project_id)
            if project is None or project.owner_id != owner_id or project.status != "active":
                raise TaskError("project_not_available")
        if await self.db.get(CompanionTask, spec.id):
            raise TaskError("task_already_exists")
        budget = (Budget.from_snapshot(budget_snapshot, limits=spec.budget.to_native())
                  if budget_snapshot is not None else Budget(spec.budget.to_native()))
        row = CompanionTask(
            id=spec.id, owner_id=owner_id, conversation_id=conversation_id,
            project_id=spec.scope.project_id, spec_revision=spec.revision,
            project_version=project.version if spec.scope.project_id else None,
            attempt_id=identity(), budget=budget.snapshot(),
            privacy=privacy or {"no_learning": True, "cloud_memory_allowed": False, "allow_sensitive": False},
            results=[], phase="queued", sequence=0, version=1,
        )
        self.db.add(row)
        await self.db.flush()
        self.db.add(TaskRevision(task_id=spec.id, revision=spec.revision, spec=spec.model_dump(mode="json")))
        await self.db.flush()
        return await self.present(row)

    async def _advance(self, row: CompanionTask, kind: str, *, changes=None, payload=None):
        old_version, sequence = row.version, row.sequence + 1
        values = {**(changes or {}), "version": old_version + 1, "sequence": sequence,
                  "updated_at": datetime.utcnow()}
        result = await self.db.execute(update(CompanionTask).where(
            CompanionTask.id == row.id, CompanionTask.version == old_version,
        ).values(**values).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            raise TaskError("task_version_conflict")
        await self.db.refresh(row)
        self.db.add(TaskEvent(task_id=row.id, sequence=sequence, attempt_id=row.attempt_id,
                              kind=kind, payload={"phase": row.phase, "spec_revision": row.spec_revision,
                                                 **(payload or {})}))
        await self.db.flush()
        return row

    async def _active(self, task_id: str, attempt_id: str, *, owner_id="local", check_scope=True):
        row = await self.get(task_id, owner_id=owner_id)
        if row.cancel_requested or row.phase == "cancelled":
            raise TaskError("task_cancelled")
        if row.attempt_id != attempt_id or row.phase not in {"running", "verifying"}:
            raise TaskError("task_attempt_stale")
        if check_scope and row.project_id:
            project = await self.db.get(Project, row.project_id)
            if (project is None or project.owner_id != owner_id or project.status != "active"
                    or project.version != row.project_version):
                raise TaskError("task_project_changed")
        return row

    async def start(self, task_id: str, expected_version: int, *, explicit_resume=False, owner_id="local") -> dict:
        row = await self.get(task_id, owner_id=owner_id)
        if row.version != expected_version:
            raise TaskError("task_version_conflict")
        if row.phase in {"running", "verifying", "succeeded"}:
            raise TaskError("task_cannot_start")
        if (row.phase != "queued" or row.cancel_requested) and not explicit_resume:
            raise TaskError("task_explicit_resume_required")
        if row.project_id:
            project = await self.db.get(Project, row.project_id)
            if project is None or project.owner_id != owner_id or project.status != "active":
                raise TaskError("project_not_available")
            if project.version != row.project_version:
                raise TaskError("task_project_changed")
        uncertain = await self.db.scalar(select(TaskAction.id).where(
            TaskAction.task_id == row.id, TaskAction.effect != "read",
            TaskAction.status.in_(("prepared", "in_flight", "uncertain"))).limit(1))
        if uncertain:
            raise TaskError("task_reconciliation_required")
        spec = await self.spec(row)
        budget = Budget.from_snapshot(row.budget, limits=spec.budget.to_native())
        budget.check()
        if (budget.model_requests >= budget.limits.model_requests or budget.tokens >= budget.limits.tokens
                or budget.tool_calls >= budget.limits.tool_calls):
            raise TaskError("task_budget_exhausted")
        number = (await self.db.scalar(select(func.max(TaskAttempt.number)).where(
            TaskAttempt.task_id == row.id)) or 0) + 1
        attempt_id = identity()
        await self._advance(row, "attempt_started", changes={
            "attempt_id": attempt_id, "phase": "running", "cancel_requested": False,
            "pause_reason": None, "budget": budget.snapshot(),
        }, payload={"attempt_number": number})
        self.db.add(TaskAttempt(id=attempt_id, task_id=row.id, number=number, spec_revision=row.spec_revision))
        await self.db.flush()
        return await self.present(row)

    async def revise(self, task_id: str, expected_version: int, spec: TaskSpec, *, owner_id="local") -> dict:
        """Explicit user revision; never called by an executor or background job."""
        row = await self.get(task_id, owner_id=owner_id)
        if row.version != expected_version:
            raise TaskError("task_version_conflict")
        if row.phase in {"running", "verifying"}:
            raise TaskError("task_still_running")
        if spec.id != row.id or spec.revision != row.spec_revision + 1 or spec.scope.owner_id != owner_id:
            raise TaskError("task_revision_mismatch")
        if spec.memory_mode == "temporary" or contains_credential(spec.model_dump_json()):
            raise TaskError("task_revision_not_persistable")
        project = await self.db.get(Project, spec.scope.project_id) if spec.scope.project_id else None
        if spec.scope.project_id and (project is None or project.owner_id != owner_id or project.status != "active"):
            raise TaskError("project_not_available")
        budget = Budget.from_snapshot(row.budget)
        budget.limits = spec.budget.to_native()  # Explicit user-supplied ceiling; usage and identity stay intact.
        if budget.stop_reason:
            used = budget.snapshot()["used"][budget.stop_reason]
            if used < getattr(budget.limits, budget.stop_reason):
                budget.stop_reason = None
        self.db.add(TaskRevision(task_id=row.id, revision=spec.revision, spec=spec.model_dump(mode="json")))
        await self._advance(row, "goal_revised", changes={
            "spec_revision": spec.revision, "project_id": spec.scope.project_id,
            "project_version": project.version if project else None, "results": [],
            "budget": budget.snapshot(), "phase": "waiting_user", "pause_reason": "goal_changed",
        })
        return await self.present(row)

    async def link_run(self, task_id: str, attempt_id: str, run_id: int):
        row = await self._active(task_id, attempt_id)
        run = await self.db.get(Run, run_id)
        if run is None or run.conversation_id != row.conversation_id:
            raise TaskError("task_run_scope_denied")
        attempt = await self.db.get(TaskAttempt, attempt_id)
        if run_id not in attempt.run_ids:
            attempt.run_ids = [*attempt.run_ids, run_id]
            await self._advance(row, "run_linked", payload={"run_id": run_id})

    async def checkpoint(self, task_id: str, attempt_id: str, budget: dict, progress: Progress,
                         *, reason="checkpoint", retain_stopped=False) -> dict:
        if retain_stopped:
            row = await self.get(task_id)
            if row.attempt_id != attempt_id:
                raise TaskError("task_attempt_stale")
        else:
            row = await self._active(task_id, attempt_id)
        attempt = await self.db.get(TaskAttempt, attempt_id)
        if attempt is None or attempt.spec_revision != row.spec_revision:
            raise TaskError("task_attempt_stale")
        prior = Budget.from_snapshot(row.budget)
        current = Budget.from_snapshot(budget, limits=(await self.spec(row)).budget.to_native())
        if current.id != prior.id:
            raise TaskError("task_budget_identity_mismatch")
        for name in ("model_requests", "tool_calls", "tokens", "artifact_bytes"):
            if getattr(current, name) < getattr(prior, name):
                raise TaskError("task_budget_cannot_reset")
        # Wall snapshots are rounded to milliseconds. Preserve the larger known
        # elapsed value instead of rejecting a harmless rounding difference.
        snapshot = current.snapshot()
        snapshot["used"]["wall_seconds"] = max(row.budget["used"]["wall_seconds"], snapshot["used"]["wall_seconds"])
        checkpoint_id = identity()
        await self._advance(row, reason, changes={"checkpoint_id": checkpoint_id, "budget": snapshot},
                            payload={"checkpoint_id": checkpoint_id})
        self.db.add(TaskCheckpoint(id=checkpoint_id, task_id=row.id, attempt_id=attempt_id,
                                  spec_revision=row.spec_revision, sequence=row.sequence,
                                  data={"progress": progress.model_dump(mode="json"), "budget": snapshot}))
        await self.db.flush()
        return await self.present(row)

    async def latest_checkpoint(self, task_id: str, *, owner_id="local") -> dict | None:
        row = await self.get(task_id, owner_id=owner_id)
        checkpoint = await self.db.get(TaskCheckpoint, row.checkpoint_id) if row.checkpoint_id else None
        return {**checkpoint.data, "spec_revision": checkpoint.spec_revision} if checkpoint else None

    async def finish(self, task_id: str, attempt_id: str, *, phase: str,
                     results: tuple[CheckResult, ...] = (), reason: str | None = None) -> dict:
        if phase not in {"waiting_user", "verifying", "succeeded", "failed"}:
            raise TaskError("task_invalid_transition")
        row = await self._active(task_id, attempt_id, check_scope=phase not in {"waiting_user", "failed"})
        spec = await self.spec(row)
        if phase == "succeeded" and await self.db.scalar(select(TaskAction.id).where(
                TaskAction.task_id == row.id, TaskAction.effect != "read",
                TaskAction.status.in_(("prepared", "in_flight", "uncertain"))).limit(1)):
            raise TaskError("task_reconciliation_required")
        TaskState(task_id=row.id, spec_revision=row.spec_revision, run_id=attempt_id,
                  sequence=row.sequence + 1, phase=phase, results=results,
                  updated_at=datetime.now(timezone.utc)).validated_for(spec)
        await self._advance(row, "state_changed", changes={
            "phase": phase, "results": [result.model_dump(mode="json") for result in results],
            "pause_reason": reason,
        })
        if phase != "verifying":
            attempt = await self.db.get(TaskAttempt, attempt_id)
            attempt.status, attempt.ended_at = phase, datetime.utcnow()
        return await self.present(row)

    async def cancel(self, task_id: str, *, expected_version: int | None = None, owner_id="local") -> dict:
        row = await self.get(task_id, owner_id=owner_id)
        if row.phase == "cancelled":
            return await self.present(row)  # Repeated cancel must remain harmless.
        if expected_version is not None and row.version != expected_version:
            raise TaskError("task_version_conflict")
        if row.phase == "succeeded":
            raise TaskError("task_already_finished")
        await self._advance(row, "cancel_requested", changes={
            "phase": "cancelled", "cancel_requested": True, "pause_reason": "user_cancelled"})
        attempt = await self.db.get(TaskAttempt, row.attempt_id)
        if attempt:
            attempt.status, attempt.ended_at = "cancelled", datetime.utcnow()
        await self._mark_uncertain(row.id)
        await self.db.execute(update(TaskWorker).where(TaskWorker.task_id == row.id,
            TaskWorker.status.in_(("queued", "running"))).values(status="cancelled", ended_at=datetime.utcnow()))
        return await self.present(row)

    async def accept_review(self, task_id: str, expected_version: int, *, owner_id="local") -> dict:
        row = await self.get(task_id, owner_id=owner_id)
        if row.version != expected_version:
            raise TaskError("task_version_conflict")
        if row.phase != "waiting_user" or row.pause_reason != "acceptance_review_required":
            raise TaskError("task_not_awaiting_acceptance")
        spec = await self.spec(row)
        previous = {result.check_id: result for result in map(CheckResult.model_validate, row.results)}
        if not any(check.evaluator == "human" for check in spec.acceptance) or any(
            check.evaluator != "human" and (check.id not in previous or not (
                previous[check.id].status == "passed" or (previous[check.id].status == "not_applicable"
                    and not check.critical and check.rule is not None and check.rule.when == "artifacts_present")))
            for check in spec.acceptance):
            raise TaskError("task_deterministic_checks_required")
        from server.services import artifact_store, task_validation
        report = await task_validation.latest_report(self, row)
        for artifact in (report or {}).get("artifacts", []):
            if artifact["status"] == "not_applicable" and artifact.get("superseded_by"):
                continue
            if artifact["status"] == "failed":
                raise TaskError("task_validation_failed")
            try:
                metadata, _ = artifact_store.read_owned(artifact["run_id"], artifact["filename"])
                if metadata["sha256"] != artifact.get("sha256"):
                    raise ValueError("changed")
            except (KeyError, OSError, ValueError, TypeError) as exc:
                raise TaskError("task_artifact_changed") from exc
        if await self.db.scalar(select(TaskAction.id).where(
                TaskAction.task_id == row.id, TaskAction.effect != "read",
                TaskAction.status.in_(("prepared", "in_flight", "uncertain"))).limit(1)):
            raise TaskError("task_reconciliation_required")
        review_id = f"human-review:{identity()}"
        proof = ResourceRef(id=review_id, kind="document", revision=1,
                            locator=f"/api/v1/tasks/{row.id}/events?after={row.sequence}")
        results = tuple(CheckResult(check_id=check.id, evaluator="human", status="passed", evidence=(proof,))
                        if check.evaluator == "human" else previous[check.id] for check in spec.acceptance)
        TaskState(task_id=row.id, spec_revision=row.spec_revision, run_id=row.attempt_id,
                  sequence=row.sequence + 1, phase="succeeded", results=results,
                  updated_at=datetime.now(timezone.utc)).validated_for(spec)
        await self._advance(row, "human_acceptance", changes={
            "phase": "succeeded", "pause_reason": None,
            "results": [result.model_dump(mode="json") for result in results],
        }, payload={"review_id": review_id, "reviewer": owner_id})
        attempt = await self.db.get(TaskAttempt, row.attempt_id)
        if attempt:
            attempt.status = "succeeded"
        return await self.present(row)

    async def events(self, task_id: str, after: int = 0, limit: int = 100, *, owner_id="local") -> dict:
        row = await self.get(task_id, owner_id=owner_id)
        if after < 0 or after > row.sequence or not 1 <= limit <= 500:
            raise TaskError("invalid_event_cursor")
        rows = (await self.db.execute(select(TaskEvent).where(
            TaskEvent.task_id == row.id, TaskEvent.sequence > after,
        ).order_by(TaskEvent.sequence).limit(limit))).scalars().all()
        cursor = rows[-1].sequence if rows else after
        return {"events": [{"sequence": item.sequence, "attempt_id": item.attempt_id, "kind": item.kind,
                            "payload": item.payload, "created_at": item.created_at.isoformat() + "Z"} for item in rows],
                "cursor": cursor, "has_more": cursor < row.sequence}

    async def prepare_action(self, task_id: str, attempt_id: str, *, tool_key: str,
                             arguments: dict, effect: str) -> dict:
        row = await self._active(task_id, attempt_id)
        if effect not in {"read", "local_write", "external_write", "destructive"}:
            raise TaskError("task_invalid_effect")
        if not tool_key or len(tool_key) > 200:
            raise TaskError("task_invalid_tool")
        # No argument is written to the journal. The hash only identifies an
        # exact intent, never authorizes it. Reads may safely repeat.
        encoded = json.dumps({"tool": tool_key, "arguments": arguments}, sort_keys=True,
                             ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if len(encoded) > 262144 or contains_credential_data(arguments) or contains_credential(encoded):
            raise TaskError("task_action_arguments_not_journalable")
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        if effect == "read":
            digest = hashlib.sha256((digest + identity()).encode()).hexdigest()
        previous = await self.db.scalar(select(TaskAction).where(
            TaskAction.task_id == row.id, TaskAction.spec_revision == row.spec_revision,
            TaskAction.intent_hash == digest))
        if previous and previous.status != "not_applied":
            code = "task_action_already_completed" if previous.status == "succeeded" else "task_reconciliation_required"
            raise TaskError(code)
        if previous:
            action = previous
            action.attempt_id, action.status = attempt_id, "prepared"
            action.version += 1
            action.updated_at = datetime.utcnow()
        else:
            action = TaskAction(id=identity(), task_id=row.id, attempt_id=attempt_id,
                                spec_revision=row.spec_revision, tool_key=tool_key,
                                intent_hash=digest, effect=effect, status="prepared")
            self.db.add(action)
        await self._advance(row, "action_prepared", payload={"action_id": action.id, "effect": effect})
        return {"id": action.id, "version": action.version, "status": action.status}

    async def action_started(self, task_id: str, attempt_id: str, action_id: str, *, grant_id: str | None = None):
        row = await self._active(task_id, attempt_id)
        action = await self.db.get(TaskAction, action_id)
        if action is None or action.task_id != row.id or action.attempt_id != attempt_id or action.status != "prepared":
            raise TaskError("task_action_stale")
        if action.tool_key.startswith("asc.") or grant_id is not None:
            from server.services.action_permissions import ActionPermissions
            if grant_id is None:
                raise TaskError("action_grant_required")
            await ActionPermissions(self.db).consume(grant_id, owner_id=row.owner_id, task_id=task_id,
                                                      attempt_id=attempt_id, action_id=action_id)
        action.status, action.version, action.updated_at = "in_flight", action.version + 1, datetime.utcnow()
        await self._advance(row, "action_started", payload={"action_id": action.id})

    async def action_finished(self, task_id: str, attempt_id: str, action_id: str, *,
                              status: str, evidence: tuple[ResourceRef, ...] = (), error_code: str | None = None):
        row = await self._active(task_id, attempt_id)
        action = await self.db.get(TaskAction, action_id)
        if action is None or action.task_id != row.id or action.attempt_id != attempt_id or action.status != "in_flight":
            raise TaskError("task_action_stale")
        if status not in {"succeeded", "failed", "denied", "uncertain"}:
            raise TaskError("task_action_invalid_status")
        # A tool's error return cannot prove that an external write did not
        # happen. Failed writes remain uncertain until a separate read-back.
        if status == "failed" and action.effect != "read":
            status = "uncertain"
        action.status, action.version, action.updated_at = status, action.version + 1, datetime.utcnow()
        action.evidence = [item.model_dump(mode="json") for item in evidence]
        action.error_code = error_code
        await self._advance(row, "action_finished", payload={"action_id": action.id, "status": status})

    async def reconcile_action(self, task_id: str, action_id: str, *, expected_version: int,
                               applied: bool, evidence: tuple[ResourceRef, ...], owner_id="local"):
        """Trusted verified read-back/manual-review path, not a model tool."""
        row = await self.get(task_id, owner_id=owner_id)
        if row.phase in {"running", "verifying"}:
            raise TaskError("task_still_running")
        action = await self.db.get(TaskAction, action_id)
        if action is None or action.task_id != row.id or action.status != "uncertain" or action.version != expected_version:
            raise TaskError("task_action_stale")
        if not evidence:
            raise TaskError("task_reconciliation_evidence_required")
        action.status = "succeeded" if applied else "not_applied"
        action.evidence = [item.model_dump(mode="json") for item in evidence]
        action.version, action.updated_at = action.version + 1, datetime.utcnow()
        await self._advance(row, "action_reconciled", payload={"action_id": action.id, "status": action.status})

    async def _mark_uncertain(self, task_id: str):
        await self.db.execute(update(TaskAction).where(
            TaskAction.task_id == task_id, TaskAction.status.in_(("prepared", "in_flight")),
        ).values(status="uncertain", version=TaskAction.version + 1, updated_at=datetime.utcnow()))

    async def recover_interrupted(self) -> int:
        """Exclusive boot pass. Never launches, retries or grants anything."""
        rows = (await self.db.execute(select(CompanionTask).where(
            CompanionTask.phase.in_(("running", "verifying"))))).scalars().all()
        for row in rows:
            await self._mark_uncertain(row.id)
            await self._advance(row, "process_interrupted", changes={
                "phase": "waiting_user", "pause_reason": "process_interrupted"})
            attempt = await self.db.get(TaskAttempt, row.attempt_id)
            if attempt:
                attempt.status, attempt.ended_at = "interrupted", datetime.utcnow()
        await self.db.execute(update(TaskWorker).where(TaskWorker.status.in_(("queued", "running")))
                              .values(status="interrupted", ended_at=datetime.utcnow()))
        return len(rows)

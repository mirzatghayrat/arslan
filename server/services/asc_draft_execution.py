"""Host-only single-field draft execution, still without a production transport.

Each field needs its own freshly prepared action and one-use approval. This
deliberately cannot replay an entire partially completed plan. The future broker
must independently enforce target, credential, redirect and network boundaries.
No route or model tool exposes this service while that security gate is closed.
"""
from __future__ import annotations

import asyncio
import json
from typing import Protocol

from arslan.companion.contracts import ResourceRef
from server.connectors.app_store_connect.client import ASCError, ReadClient
from server.connectors.app_store_connect.contracts import AppTarget
from server.connectors.app_store_connect.preparation import DraftPlan, plan_draft, reconcile_fields, require_fresh
from server.db.models import Project, Run, TaskAction, TaskAttempt
from server.services.artifact_store import store_bytes
from server.services.action_permissions import ActionPermissions
from server.services.task_repository import TaskError, action_digest, encoded_action, repository


class DraftTransport(Protocol):
    async def patch(self, path: str, body: dict) -> int:
        """Return HTTP status only; never expose remote bodies or auth headers."""
        ...


async def _bound_action(repo, *, owner_id: str, task_id: str, attempt_id: str,
                        action_id: str, target: AppTarget, run_id: int, arguments: dict):
    task = await repo._active(task_id, attempt_id, owner_id=owner_id)
    attempt = await repo.db.get(TaskAttempt, attempt_id)
    run = await repo.db.get(Run, run_id)
    if (type(run_id) is not int or run_id <= 0 or run is None or attempt is None
            or run_id not in attempt.run_ids or run.conversation_id != task.conversation_id):
        raise TaskError("task_run_scope_denied")
    project = await repo.db.get(Project, task.project_id)
    binding = project.app_binding if project is not None else None
    if not binding or any(binding.get(key) != value for key, value in target.model_dump().items()):
        raise ASCError("asc_app_binding_mismatch")
    action = await repo.db.get(TaskAction, action_id)
    if (action is None or action.task_id != task_id or action.attempt_id != attempt_id
            or action.tool_key != "asc.draft.update" or action.effect != "external_write"
            or action.status != "prepared"):
        raise TaskError("task_action_stale")
    if action_digest(action.tool_key, arguments, action.effect, action.id) != action.intent_hash:
        raise TaskError("task_action_intent_mismatch")


async def execute_field_draft(*, owner_id: str, task_id: str, attempt_id: str,
                              action_id: str, grant_id: str, plan: DraftPlan, run_id: int,
                              reader: ReadClient, writer: DraftTransport) -> dict:
    # Revalidation also rejects unchecked model_copy/model_construct values.
    plan = DraftPlan.model_validate(plan.model_dump(mode="json"))
    if len(plan.changes) != 1:
        raise ASCError("asc_single_field_approval_required")
    change = plan.changes[0]
    if change.after is None:
        raise ASCError("asc_null_write_not_supported")
    arguments = plan.model_dump(mode="json")
    async with repository() as repo:
        await _bound_action(repo, owner_id=owner_id, task_id=task_id, attempt_id=attempt_id,
                            action_id=action_id, target=plan.target, run_id=run_id, arguments=arguments)
        await ActionPermissions(repo.db).validate(grant_id, owner_id=owner_id, task_id=task_id,
                                                 attempt_id=attempt_id, action_id=action_id)
    async with asyncio.timeout(60):
        before = await reader.snapshot(plan.target)
    require_fresh(plan, before)
    canonical = plan_draft(before, {change.locale: {change.field: change.after}})
    if canonical != plan:
        raise ASCError("asc_draft_stale_reapproval_required")
    # Recheck local target/cancellation after network preflight. Admission hashes
    # precisely this plan, not an arbitrary caller-provided request body.
    async with repository() as repo:
        await _bound_action(repo, owner_id=owner_id, task_id=task_id, attempt_id=attempt_id,
                            action_id=action_id, target=plan.target, run_id=run_id, arguments=arguments)
        await repo.action_started(task_id, attempt_id, action_id, grant_id=grant_id, arguments=arguments)
    outcome = {"status": "unknown", "automatic_retry": False,
               "evidence_kind": reader.evidence_kind, "request_accepted": False,
               "atomic_remote_compare_and_swap": False}
    evidence = ()
    cancelled = False
    try:
        async with asyncio.timeout(60):
            try:
                async with asyncio.timeout(15):
                    status = await writer.patch(f"/v1/appStoreVersionLocalizations/{change.localization_id}",
                        {"data": {"type": "appStoreVersionLocalizations", "id": change.localization_id,
                                  "attributes": {change.field: change.after}}})
                outcome["request_accepted"] = type(status) is int and status == 200
            except (OSError, TimeoutError):
                pass  # Sent may mean applied. A separate readback decides state.
            latest = await reader.snapshot(plan.target)
            outcome.update(reconcile_fields(plan, latest)[0])
            item = next((item for item in latest.localizations if item.id == change.localization_id), None)
            report = {"kind": "asc_field_readback", "target": plan.target.model_dump(mode="json"),
                      "action_id": action_id, "plan_hash": plan.diff_hash(), "result": dict(outcome),
                      "fetched_at": latest.fetched_at.isoformat(), "expected": change.after,
                      "observed_present": bool(item and change.field in item.fields),
                      "observed": item.fields.get(change.field) if item else None}
            # A remote string is not permission to persist credentials as an artifact.
            encoded_action("asc.field.readback", report)
            artifact = store_bytes(run_id, "asc-field-readback.json",
                                   json.dumps(report, ensure_ascii=False, allow_nan=False).encode())
            outcome["artifact"] = artifact
            evidence = (ResourceRef(id=artifact["id"], kind="artifact", revision=1,
                                    sha256=artifact["sha256"], locator=artifact["url"]),)
    except asyncio.CancelledError:
        cancelled = True
    except Exception:
        # No raw broker errors/remote payloads reach the task or its journal.
        outcome["status"] = "unknown"
    try:
        async with repository() as repo:
            await repo.action_finished(task_id, attempt_id, action_id,
                status="succeeded" if outcome["status"] == "verified" else "uncertain",
                evidence=evidence,
                error_code=None if outcome["status"] == "verified" else "asc_readback_required")
    except TaskError:
        # Task cancellation/stop already quarantines in-flight writes. It must
        # not be overridden by a late completion or suppress cancellation.
        if not cancelled:
            raise
    if cancelled:
        raise asyncio.CancelledError
    return outcome

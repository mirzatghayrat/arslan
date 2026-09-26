"""Host-only approval storage. No model tool/API can mint these approvals.

This is not a credential broker. Real authenticated connectors remain disabled
until the independent OS-boundary review. A UUID/boolean supplied by an agent is
not user confirmation; the eventual trusted confirmation UI must call issue().
All methods participate in the caller's SQLite transaction; admission and grant
consumption must commit together with TaskRepository.action_started().
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, update
from arslan.companion.action_policy import ACCOUNT_ACTION_EFFECTS

from server.db.models import ActionGrantRecord, CompanionConnection, Project, TaskAction
from server.services.task_repository import TaskError, TaskRepository

# Draft and read capabilities are deliberately separate. Submission/publication,
# agreements, tax, banking and privacy assertions are not available here.
APPROVABLE_ACTIONS = frozenset(ACCOUNT_ACTION_EFFECTS)


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def target_hash(binding: dict | None) -> str:
    if not isinstance(binding, dict) or not binding:
        raise TaskError("grant_target_missing")
    return hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def opaque_uuid(value: str) -> str:
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as exc:
        raise TaskError("grant_invalid_reference") from exc
    return value


class ActionPermissions:
    def __init__(self, db):
        self.db = db

    async def register(self, *, owner_id: str, provider: str, credential_ref: str) -> dict:
        if provider != "app_store_connect" or not owner_id or len(owner_id) > 100:
            raise TaskError("connection_provider_unavailable")
        row = CompanionConnection(id=str(uuid4()), owner_id=owner_id, provider=provider,
                                  credential_ref=opaque_uuid(credential_ref), status="disconnected", version=1)
        self.db.add(row)
        await self.db.flush()
        return self.present(row)

    @staticmethod
    def present(row) -> dict:
        # Even the opaque broker reference stays out of UI/agent-facing payloads.
        return {"id": row.id, "provider": row.provider, "status": row.status, "version": row.version}

    async def disconnect(self, connection_id: str, *, owner_id: str, expected_version: int):
        result = await self.db.execute(update(CompanionConnection).where(
            CompanionConnection.id == connection_id, CompanionConnection.owner_id == owner_id,
            CompanionConnection.version == expected_version,
        ).values(status="disconnected", version=expected_version + 1))
        if result.rowcount != 1:
            raise TaskError("connection_stale")

    async def _binding(self, *, owner_id: str, task_id: str, attempt_id: str,
                       action_id: str, connection_id: str):
        task = await TaskRepository(self.db)._active(task_id, attempt_id, owner_id=owner_id)
        action = await self.db.scalar(select(TaskAction).where(TaskAction.id == action_id)
                                     .execution_options(populate_existing=True))
        connection = await self.db.scalar(select(CompanionConnection).where(
            CompanionConnection.id == connection_id).execution_options(populate_existing=True))
        project = await self.db.scalar(select(Project).where(Project.id == task.project_id)
                                      .execution_options(populate_existing=True))
        if (connection is None or connection.owner_id != owner_id or connection.status != "connected"
                or connection.provider != "app_store_connect"):
            raise TaskError("grant_connection_unavailable")
        if (project is None or project.owner_id != owner_id or project.status != "active"
                or project.version != task.project_version):
            raise TaskError("grant_project_stale")
        from pydantic import ValidationError
        from server.connectors.app_store_connect.contracts import AppTarget
        binding = project.app_binding or {}
        if binding.get("connection_id") != connection.id:
            raise TaskError("grant_connection_binding_mismatch")
        try:
            AppTarget.model_validate({key: binding.get(key) for key in ("app_id", "version_id", "platform", "bundle_id")})
        except ValidationError as exc:
            raise TaskError("grant_target_missing") from exc
        if (action is None or action.task_id != task.id or action.attempt_id != attempt_id
                or action.spec_revision != task.spec_revision or action.status != "prepared"
                or action.tool_key not in APPROVABLE_ACTIONS
                or action.effect != ACCOUNT_ACTION_EFFECTS.get(action.tool_key)):
            raise TaskError("grant_action_unavailable")
        return {"owner_id": owner_id, "connection_id": connection.id, "connection_version": connection.version,
                "task_id": task.id, "attempt_id": attempt_id, "spec_revision": task.spec_revision,
                "project_id": project.id, "project_version": project.version,
                "target_hash": target_hash(project.app_binding), "action_id": action.id,
                "action_version": action.version, "action": action.tool_key, "diff_hash": action.intent_hash}

    async def issue(self, *, owner_id: str, task_id: str, attempt_id: str, action_id: str,
                    connection_id: str, confirmation_ref: str, approved_diff_hash: str,
                    approved_target_hash: str, lifetime_seconds: int = 300) -> str:
        """Called only after trusted UI confirmation of the displayed exact diff.

        Hashes must come from the confirmed UI snapshot, not be regenerated from
        whatever happens to be current when the confirmation arrives.
        """
        if type(lifetime_seconds) is not int or not 1 <= lifetime_seconds <= 900:
            raise TaskError("grant_invalid_lifetime")
        binding = await self._binding(owner_id=owner_id, task_id=task_id, attempt_id=attempt_id,
                                      action_id=action_id, connection_id=connection_id)
        if binding["diff_hash"] != approved_diff_hash or binding["target_hash"] != approved_target_hash:
            raise TaskError("grant_confirmation_stale")
        now = utc_now()
        grant = ActionGrantRecord(id=str(uuid4()), **binding, confirmation_ref=opaque_uuid(confirmation_ref),
                                  issued_at=now, expires_at=now + timedelta(seconds=lifetime_seconds))
        self.db.add(grant)
        await self.db.flush()
        return grant.id

    async def revoke(self, grant_id: str, *, owner_id: str):
        result = await self.db.execute(update(ActionGrantRecord).where(
            ActionGrantRecord.id == grant_id, ActionGrantRecord.owner_id == owner_id,
            ActionGrantRecord.revoked_at.is_(None), ActionGrantRecord.consumed_at.is_(None),
        ).values(revoked_at=utc_now()))
        if result.rowcount != 1:
            raise TaskError("grant_unavailable")

    async def validate(self, grant_id: str, *, owner_id: str, task_id: str, attempt_id: str, action_id: str):
        """Read-only preflight; never substitutes for atomic consume at admission."""
        grant = await self.db.scalar(select(ActionGrantRecord).where(ActionGrantRecord.id == grant_id)
                                    .execution_options(populate_existing=True))
        if grant is None or grant.owner_id != owner_id:
            raise TaskError("grant_unavailable")
        binding = await self._binding(owner_id=owner_id, task_id=task_id, attempt_id=attempt_id,
                                      action_id=action_id, connection_id=grant.connection_id)
        if any(getattr(grant, key) != value for key, value in binding.items()):
            raise TaskError("grant_binding_stale")
        now = utc_now()
        if (grant.revoked_at is not None or grant.consumed_at is not None
                or grant.issued_at > now or grant.expires_at <= now):
            raise TaskError("grant_unavailable")

    async def consume(self, grant_id: str, *, owner_id: str, task_id: str, attempt_id: str, action_id: str):
        await self.validate(grant_id, owner_id=owner_id, task_id=task_id, attempt_id=attempt_id, action_id=action_id)
        now = utc_now()
        result = await self.db.execute(update(ActionGrantRecord).where(
            ActionGrantRecord.id == grant_id, ActionGrantRecord.revoked_at.is_(None),
            ActionGrantRecord.consumed_at.is_(None), ActionGrantRecord.issued_at <= now,
            ActionGrantRecord.expires_at > now,
        ).values(consumed_at=now))
        if result.rowcount != 1:
            raise TaskError("grant_unavailable")

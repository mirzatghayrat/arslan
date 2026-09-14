"""Synthetic authorization records only; no broker or remote account access."""
import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from arslan.companion.contracts import TaskSpec
from server.db.models import ActionGrantRecord, CompanionConnection, CompanionTask, Project, TaskAction
from server.services.action_permissions import ActionPermissions, target_hash, utc_now
from server.services.task_repository import TaskError, repository


async def setup_action(execution_db, tool="asc.draft.update"):
    async with execution_db() as db:
        db.add(Project(id="project", owner_id="local", name="Example", version=1,
                       app_binding={"app_id": "123", "version_id": "v1"}))
        await db.commit()
    async with repository() as repo:
        value = await repo.create(TaskSpec.model_validate({
            "id": "task", "scope": {"kind": "task", "owner_id": "local", "task_id": "task",
                                      "project_id": "project"},
            "instruction": "Prepare a draft", "locale": "en", "acceptance": [
                {"id": "readback", "description": "Exact field readback", "evaluator": "deterministic"}],
        }), "conversation")
        value = await repo.start("task", value["version"])
        attempt = value["state"]["run_id"]
        action = await repo.prepare_action("task", attempt, tool_key=tool,
                                           arguments={"before": "old", "after": "new"}, effect="external_write")
        permissions = ActionPermissions(repo.db)
        connection = await permissions.register(owner_id="local", provider="app_store_connect",
                                                credential_ref=str(uuid4()))
        assert "credential_ref" not in connection and connection["status"] == "disconnected"
        # Synthetic broker attestation. Production has no activation path yet.
        row = await repo.db.get(CompanionConnection, connection["id"])
        row.status = "connected"
        project = await repo.db.get(Project, "project")
        project.app_binding = {"app_id": "123", "version_id": "v1", "platform": "IOS",
                               "bundle_id": "com.example.app", "connection_id": connection["id"]}
        await repo.db.flush()
        action_row = await repo.db.get(TaskAction, action["id"])
        return dict(owner_id="local", task_id="task", attempt_id=attempt, action_id=action["id"],
                    connection_id=connection["id"], confirmation_ref=str(uuid4()),
                    approved_diff_hash=action_row.intent_hash,
                    approved_target_hash=target_hash(project.app_binding))


async def issue(data):
    async with repository() as repo:
        return await ActionPermissions(repo.db).issue(**data)


async def start(data, grant):
    async with repository() as repo:
        await repo.action_started(data["task_id"], data["attempt_id"], data["action_id"], grant_id=grant)


async def test_grant_consumption_and_admission_commit_together(execution_db):
    data = await setup_action(execution_db)
    grant = await issue(data)
    await start(data, grant)
    async with execution_db() as db:
        assert (await db.get(ActionGrantRecord, grant)).consumed_at is not None
        assert (await db.get(TaskAction, data["action_id"])).status == "in_flight"
    with pytest.raises(TaskError):
        await start(data, grant)


async def test_without_grant_never_admitted(execution_db):
    data = await setup_action(execution_db)
    with pytest.raises(TaskError, match="action_grant_required"):
        await start(data, None)


@pytest.mark.parametrize("mutation", ["revoked", "expired", "future", "connection", "connection_version",
    "project_version", "app", "task_revision", "task_cancel", "action_version", "diff", "owner"])
async def test_queued_grant_revalidated_after_changes(execution_db, mutation):
    data = await setup_action(execution_db)
    grant_id = await issue(data)
    async with execution_db() as db:
        grant = await db.get(ActionGrantRecord, grant_id)
        if mutation == "revoked":
            await ActionPermissions(db).revoke(grant_id, owner_id="local")
        elif mutation == "expired":
            grant.issued_at, grant.expires_at = utc_now() - timedelta(hours=2), utc_now() - timedelta(hours=1)
        elif mutation == "future":
            grant.issued_at, grant.expires_at = utc_now() + timedelta(hours=1), utc_now() + timedelta(hours=2)
        elif mutation.startswith("connection"):
            conn = await db.get(CompanionConnection, data["connection_id"])
            if mutation == "connection":
                await ActionPermissions(db).disconnect(conn.id, owner_id="local", expected_version=conn.version)
            else:
                conn.version += 1
        elif mutation in {"app", "project_version"}:
            project = await db.get(Project, "project")
            if mutation == "app":
                project.app_binding = {"app_id": "456", "version_id": "v1"}
            else:
                project.version += 1
        elif mutation.startswith("task"):
            task = await db.get(CompanionTask, "task")
            if mutation == "task_cancel":
                task.cancel_requested = True
            else:
                task.spec_revision += 1
        elif mutation in {"action_version", "diff"}:
            action = await db.get(TaskAction, data["action_id"])
            if mutation == "diff":
                action.intent_hash = "a" * 64
            else:
                action.version += 1
        elif mutation == "owner":
            grant.owner_id = "other"
        await db.commit()
    with pytest.raises(TaskError):
        await start(data, grant_id)
    async with execution_db() as db:
        assert (await db.get(ActionGrantRecord, grant_id)).consumed_at is None
        assert (await db.get(TaskAction, data["action_id"])).status == "prepared"


@pytest.mark.parametrize("field,value", [
    ("approved_diff_hash", "b" * 64), ("approved_target_hash", "b" * 64),
    ("connection_id", "invented"), ("owner_id", "other"), ("confirmation_ref", "fake"),
    ("lifetime_seconds", 901), ("lifetime_seconds", True),
])
async def test_forged_or_stale_confirmation_rejected(execution_db, field, value):
    data = await setup_action(execution_db)
    with pytest.raises(TaskError):
        await issue({**data, field: value})
    async with execution_db() as db:
        assert (await db.scalars(select(ActionGrantRecord))).all() == []


@pytest.mark.parametrize("tool", ["asc.submit", "asc.publish", "asc.tax.update", "asc.privacy.guess"])
async def test_high_impact_capabilities_unavailable(execution_db, tool):
    data = await setup_action(execution_db, tool)
    with pytest.raises(TaskError, match="grant_action_unavailable"):
        await issue(data)


async def test_rollback_does_not_burn_approval(execution_db):
    data = await setup_action(execution_db)
    grant = await issue(data)
    with pytest.raises(RuntimeError):
        async with repository() as repo:
            await repo.action_started("task", data["attempt_id"], data["action_id"], grant_id=grant)
            raise RuntimeError("failed commit")
    await start(data, grant)


async def test_concurrent_admission_only_one_wins(execution_db):
    data = await setup_action(execution_db)
    grant = await issue(data)
    async def attempt():
        try:
            await start(data, grant)
            return "admitted"
        except TaskError:
            return "denied"
    assert sorted(await asyncio.gather(attempt(), attempt())) == ["admitted", "denied"]


async def test_restore_revokes_grants_and_connection_attestation(execution_db):
    from server.services.task_restore import quarantine_sync
    data = await setup_action(execution_db)
    grant = await issue(data)
    async with execution_db.kw["bind"].begin() as connection:
        await connection.run_sync(quarantine_sync)
    async with execution_db() as db:
        assert (await db.get(ActionGrantRecord, grant)).revoked_at is not None
        conn = await db.get(CompanionConnection, data["connection_id"])
        assert conn.status == "needs_attention" and conn.version == 2
    with pytest.raises(TaskError):
        await start(data, grant)


async def test_grant_cannot_be_retargeted_to_second_action(execution_db):
    data = await setup_action(execution_db)
    grant = await issue(data)
    async with repository() as repo:
        second = await repo.prepare_action("task", data["attempt_id"], tool_key="asc.draft.update",
                                           arguments={"after": "different"}, effect="external_write")
    with pytest.raises(TaskError, match="grant_binding_stale"):
        await start({**data, "action_id": second["id"]}, grant)
    await start(data, grant)


async def test_disconnected_registration_does_not_authorize(execution_db):
    data = await setup_action(execution_db)
    async with repository() as repo:
        conn = await ActionPermissions(repo.db).register(owner_id="local", provider="app_store_connect",
                                                         credential_ref=str(uuid4()))
    with pytest.raises(TaskError, match="grant_connection_unavailable"):
        await issue({**data, "connection_id": conn["id"]})


async def test_migration_idempotent_preserves_existing_grant(execution_db):
    from server.db.migrations.versions._0053_action_grants import upgrade_sync
    data = await setup_action(execution_db)
    grant = await issue(data)
    async with execution_db.kw["bind"].begin() as connection:
        await connection.run_sync(upgrade_sync)
        await connection.run_sync(upgrade_sync)
    await start(data, grant)

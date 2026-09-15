"""Synthetic field writes only: no HTTP transport, credentials or account."""
import asyncio
import hashlib
import json
from copy import deepcopy

import pytest

from server.connectors.app_store_connect.client import ASCError, ReadClient, production_client
from server.connectors.app_store_connect.preparation import plan_draft
from server.db.models import ActionGrantRecord, Project, Run, TaskAction
from server.services.action_permissions import target_hash
from server.services.asc_draft_execution import execute_field_draft
from server.services.task_repository import TaskError, repository
from tests.server.test_action_permissions import issue, setup_action
from tests.server.test_asc_preparation import FixtureTransport, TARGET, snapshot


class Writes(FixtureTransport):
    def __init__(self, behavior="success"):
        super().__init__()
        self.behavior, self.writes = behavior, []

    @property
    def attrs(self):
        return self.pages["/v1/appStoreVersions/version-1/appStoreVersionLocalizations"]["data"][0]["attributes"]

    async def patch(self, path, body):
        self.writes.append((path, deepcopy(body)))
        if self.behavior in {"success", "timeout_applied"}:
            self.attrs.update(body["data"]["attributes"])
        if self.behavior == "conflict":
            self.attrs["description"] = "Another editor"
        if self.behavior == "cancel":
            raise asyncio.CancelledError
        if self.behavior.startswith("timeout"):
            raise TimeoutError
        if self.behavior == "read_failure":
            self.pages["/v1/apps/123"] = (500, {"error": "remote-canary"}, {})
        return 200 if self.behavior == "success" else 500


async def setup(execution_db, transport=None, desired=None):
    transport = transport or Writes()
    plan = plan_draft(await snapshot(transport), desired or {"en-US": {"description": "After"}})
    data = await setup_action(execution_db)
    async with repository() as repo:
        project = await repo.db.get(Project, "project")
        project.app_binding = {**TARGET.model_dump(), "connection_id": data["connection_id"]}
        run = Run(conversation_id="conversation", user_message="Synthetic draft fixture")
        repo.db.add(run)
        await repo.db.flush()
        await repo.link_run("task", data["attempt_id"], run.id)
        run_id = run.id
        action = await repo.prepare_action("task", data["attempt_id"], tool_key="asc.draft.update",
                                           arguments=plan.model_dump(mode="json"), effect="external_write")
        row = await repo.db.get(TaskAction, action["id"])
        data.update(action_id=row.id, approved_diff_hash=row.intent_hash,
                    approved_target_hash=target_hash(project.app_binding))
    grant = await issue(data)
    kwargs = {key: data[key] for key in ("owner_id", "task_id", "attempt_id", "action_id")}
    kwargs.update(grant_id=grant, plan=plan, run_id=run_id,
                  reader=ReadClient(transport, evidence_kind="fixture"), writer=transport)
    return kwargs, transport


@pytest.mark.parametrize("behavior,status,journal", [
    ("success", "verified", "succeeded"), ("timeout_applied", "verified", "succeeded"),
    ("timeout_not_applied", "not_applied", "uncertain"), ("conflict", "conflict", "uncertain"),
    ("read_failure", "unknown", "uncertain"),
])
async def test_single_request_and_independent_readback(execution_db, behavior, status, journal):
    kwargs, transport = await setup(execution_db, Writes(behavior))
    result = await execute_field_draft(**kwargs)
    assert result["status"] == status and result["automatic_retry"] is False
    assert result["evidence_kind"] == "fixture"
    assert "remote-canary" not in str(result)
    assert transport.writes == [("/v1/appStoreVersionLocalizations/locale-1", {
        "data": {"type": "appStoreVersionLocalizations", "id": "locale-1", "attributes": {"description": "After"}}})]
    async with execution_db() as db:
        assert (await db.get(TaskAction, kwargs["action_id"])).status == journal
        if status != "unknown":
            assert (await db.get(TaskAction, kwargs["action_id"])).evidence[0]["sha256"] == result["artifact"]["sha256"]
            from server.services.artifact_store import root
            content = (root() / result["artifact"]["filename"]).read_bytes()
            assert hashlib.sha256(content).hexdigest() == result["artifact"]["sha256"]
            report = json.loads(content)
            assert report["result"]["status"] == status
            assert report["result"]["evidence_kind"] == "fixture"
            assert report["target"] == TARGET.model_dump()
            assert report["result"]["atomic_remote_compare_and_swap"] is False
        assert (await db.get(ActionGrantRecord, kwargs["grant_id"])).consumed_at is not None
    with pytest.raises(TaskError, match="task_action_stale"):
        await execute_field_draft(**kwargs)
    assert len(transport.writes) == 1


@pytest.mark.parametrize("mutation", ["remote", "project", "plan", "revoked", "many_fields"])
async def test_stale_or_expanded_approval_never_sends(execution_db, mutation):
    desired = {"en-US": {"description": "After", "supportUrl": "https://example.com/new"}} if mutation == "many_fields" else None
    kwargs, transport = await setup(execution_db, desired=desired)
    if mutation == "remote":
        transport.attrs["description"] = "Other editor"
    elif mutation == "project":
        async with execution_db() as db:
            project = await db.get(Project, "project")
            project.app_binding = {**project.app_binding, "app_id": "456"}
            await db.commit()
    elif mutation == "plan":
        kwargs["plan"] = plan_draft(await snapshot(transport), {"en-US": {"description": "Unapproved"}})
    elif mutation == "revoked":
        from server.services.action_permissions import ActionPermissions
        async with repository() as repo:
            await ActionPermissions(repo.db).revoke(kwargs["grant_id"], owner_id="local")
    reads_before = len(transport.calls)
    with pytest.raises((TaskError, ASCError)):
        await execute_field_draft(**kwargs)
    assert transport.writes == []
    if mutation != "remote":
        assert len(transport.calls) == reads_before
    async with execution_db() as db:
        assert (await db.get(ActionGrantRecord, kwargs["grant_id"])).consumed_at is None
        assert (await db.get(TaskAction, kwargs["action_id"])).status == "prepared"


async def test_cancelled_write_is_uncertain_not_replayed(execution_db):
    kwargs, transport = await setup(execution_db, Writes("cancel"))
    with pytest.raises(asyncio.CancelledError):
        await execute_field_draft(**kwargs)
    async with execution_db() as db:
        assert (await db.get(TaskAction, kwargs["action_id"])).status == "uncertain"
    assert len(transport.writes) == 1


@pytest.mark.parametrize("mutation", ["revoke", "target", "cancel"])
async def test_local_authority_rechecked_after_remote_preflight(execution_db, mutation):
    kwargs, transport = await setup(execution_db)
    class ChangedReader(ReadClient):
        async def snapshot(self, target):
            value = await super().snapshot(target)
            async with repository() as repo:
                if mutation == "revoke":
                    from server.services.action_permissions import ActionPermissions
                    await ActionPermissions(repo.db).revoke(kwargs["grant_id"], owner_id="local")
                elif mutation == "target":
                    project = await repo.db.get(Project, "project")
                    project.app_binding = {**project.app_binding, "app_id": "456"}
                else:
                    from server.db.models import CompanionTask
                    (await repo.db.get(CompanionTask, "task")).cancel_requested = True
            return value
    kwargs["reader"] = ChangedReader(transport, evidence_kind="fixture")
    with pytest.raises((TaskError, ASCError)):
        await execute_field_draft(**kwargs)
    assert transport.writes == []
    async with execution_db() as db:
        assert (await db.get(ActionGrantRecord, kwargs["grant_id"])).consumed_at is None


async def test_readback_must_be_durably_saved_before_success(execution_db, monkeypatch):
    kwargs, transport = await setup(execution_db)
    def unavailable(*args, **kw):
        raise OSError("disk-canary")
    monkeypatch.setattr("server.services.asc_draft_execution.store_bytes", unavailable)
    result = await execute_field_draft(**kwargs)
    assert result["status"] == "unknown" and "artifact" not in result
    assert "disk-canary" not in str(result)
    async with execution_db() as db:
        assert (await db.get(TaskAction, kwargs["action_id"])).status == "uncertain"
    assert len(transport.writes) == 1


async def test_unlinked_artifact_owner_denied_before_network(execution_db):
    kwargs, transport = await setup(execution_db)
    kwargs["run_id"] += 1000
    reads_before = len(transport.calls)
    with pytest.raises(TaskError, match="task_run_scope_denied"):
        await execute_field_draft(**kwargs)
    assert len(transport.calls) == reads_before and not transport.writes


async def test_null_write_is_explicitly_unsupported(execution_db):
    kwargs, transport = await setup(execution_db, desired={"en-US": {"description": None}})
    with pytest.raises(ASCError, match="asc_null_write_not_supported"):
        await execute_field_draft(**kwargs)
    assert not transport.writes


def test_no_production_activation():
    with pytest.raises(ASCError, match="isolated_credential_broker_review_required"):
        production_client()

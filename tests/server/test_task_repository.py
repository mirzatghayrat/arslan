import asyncio
import pytest
from sqlalchemy import select

from arslan.companion.contracts import CheckResult, ResourceRef, TaskSpec
from arslan.execution_budget import Budget, BudgetExceeded, Limits
from server.db.models import CompanionTask, TaskAction, TaskAttempt, TaskCheckpoint, TaskEvent
from server.services.task_repository import Progress, TaskError, repository


def spec(identity="task-one", **changes):
    return TaskSpec.model_validate({
        "id": identity, "scope": {"kind": "task", "owner_id": "local", "task_id": identity},
        "instruction": "Create and verify a document", "locale": "en",
        "acceptance": [{"id": "openable", "description": "The file exists and opens",
                        "evaluator": "deterministic", "critical": True}], **changes,
    })


async def started():
    async with repository() as repo:
        created = await repo.create(spec(), "conversation")
        return await repo.start("task-one", created["version"])


def evidence():
    return ResourceRef(id="artifact-one", kind="artifact", revision=1, sha256="a" * 64)


async def test_checkpoint_rebuilds_state_results_and_budget_across_sessions(execution_db):
    initial = await started()
    attempt = initial["state"]["run_id"]
    budget = Budget.from_snapshot(initial["budget"])
    budget.model_request(100)
    budget.tool()
    budget.tokens = 42
    budget.reserve_artifact(300)
    progress = Progress(completed_steps=("written",), artifacts=(evidence(),))
    async with repository() as repo:
        checkpoint = await repo.checkpoint("task-one", attempt, budget.snapshot(), progress)
    async with repository() as repo:
        assert await repo.latest_checkpoint("task-one") == {
            "progress": progress.model_dump(mode="json"), "budget": checkpoint["budget"], "spec_revision": 1}
        assert await repo.recover_interrupted() == 1
    async with repository() as repo:
        row = await repo.get("task-one")
        assert row.phase == "waiting_user" and row.pause_reason == "process_interrupted"
        with pytest.raises(TaskError, match="explicit_resume"):
            await repo.start(row.id, row.version)
        resumed = await repo.start(row.id, row.version, explicit_resume=True)
        assert resumed["state"]["run_id"] != attempt
        assert resumed["budget"]["id"] == initial["budget"]["id"]
        assert resumed["budget"]["used"]["model_requests"] == 1
        assert resumed["budget"]["used"]["tool_calls"] == 1
        assert resumed["budget"]["used"]["tokens"] == 42
        assert resumed["budget"]["used"]["artifact_bytes"] == 300
        assert resumed["state"]["checkpoint_ref"] == checkpoint["state"]["checkpoint_ref"]
    async with repository() as repo:
        with pytest.raises(TaskError, match="attempt_stale"):
            await repo.checkpoint("task-one", attempt, budget.snapshot(), progress)


async def test_double_start_is_fenced_in_persistent_storage(execution_db):
    async with repository() as repo:
        initial = await repo.create(spec(), "conversation")
    async def start():
        try:
            async with repository() as repo:
                await repo.start("task-one", initial["version"])
            return "started"
        except TaskError:
            return "refused"
    assert sorted(await asyncio.gather(start(), start())) == ["refused", "started"]
    async with execution_db() as db:
        assert len((await db.execute(select(TaskAttempt))).scalars().all()) == 1


async def test_two_tasks_cannot_execute_in_the_same_conversation(execution_db):
    await started()
    with pytest.raises(TaskError, match="version_conflict"):
        async with repository() as repo:
            second = await repo.create(spec("other-task"), "conversation")
            await repo.start("other-task", second["version"])


async def test_restore_keeps_budget_and_cancellation_but_invalidates_prior_success(execution_db):
    from server.services.task_restore import quarantine_sync
    initial = await started()
    async with repository() as repo:
        await repo.finish("task-one", initial["state"]["run_id"], phase="succeeded", results=(
            CheckResult(check_id="openable", status="passed", evaluator="deterministic", evidence=(evidence(),)),))
        await repo.create(spec("cancelled-task"), "other-conversation")
        await repo.cancel("cancelled-task")
    async with execution_db.kw["bind"].begin() as connection:
        await connection.run_sync(quarantine_sync)
    async with repository() as repo:
        row = await repo.get("task-one")
        assert row.phase == "waiting_user" and row.pause_reason == "backup_restore_review_required"
        assert row.results == [] and row.privacy["no_learning"] and not row.privacy["cloud_memory_allowed"]
        assert row.budget["id"] == initial["budget"]["id"]
        assert (await repo.get("cancelled-task")).phase == "cancelled"
        assert await repo.recover_interrupted() == 0


async def test_cancel_is_idempotent_retains_completed_work_and_never_boot_resumes(execution_db):
    initial = await started()
    attempt = initial["state"]["run_id"]
    async with repository() as repo:
        checkpoint = await repo.checkpoint("task-one", attempt, initial["budget"],
                                           Progress(completed_steps=("finished-file",), artifacts=(evidence(),)))
        cancelled = await repo.cancel("task-one", expected_version=checkpoint["version"])
        again = await repo.cancel("task-one", expected_version=1)
        assert cancelled == again
        assert await repo.recover_interrupted() == 0
    async with repository() as repo:
        row = await repo.get("task-one")
        assert row.cancel_requested and row.phase == "cancelled"
        assert (await repo.latest_checkpoint(row.id))["progress"]["completed_steps"] == ["finished-file"]
        with pytest.raises(TaskError, match="explicit_resume"):
            await repo.start(row.id, row.version)
        with pytest.raises(TaskError, match="task_cancelled"):
            await repo.finish(row.id, attempt, phase="waiting_user")


async def test_uncertain_write_requires_readback_and_never_automatically_replays(execution_db):
    initial = await started()
    attempt = initial["state"]["run_id"]
    async with repository() as repo:
        action = await repo.prepare_action("task-one", attempt, tool_key="publish_listing",
                                          arguments={"app_id": "synthetic-app", "version": "1"}, effect="external_write")
        await repo.action_started("task-one", attempt, action["id"])
    # Simulated external success followed by a process crash before its receipt.
    async with repository() as repo:
        await repo.recover_interrupted()
    async with repository() as repo:
        row = await repo.get("task-one")
        with pytest.raises(TaskError, match="reconciliation_required"):
            await repo.start(row.id, row.version, explicit_resume=True)
        unresolved = await repo.db.get(TaskAction, action["id"])
        assert unresolved.status == "uncertain"
        with pytest.raises(TaskError, match="evidence_required"):
            await repo.reconcile_action(row.id, action["id"], expected_version=unresolved.version,
                                        applied=True, evidence=())
        await repo.reconcile_action(row.id, action["id"], expected_version=unresolved.version,
                                    applied=True, evidence=(evidence(),))
        resumed = await repo.start(row.id, row.version, explicit_resume=True)
    async with repository() as repo:
        with pytest.raises(TaskError, match="already_completed"):
            await repo.prepare_action("task-one", resumed["state"]["run_id"], tool_key="publish_listing",
                                      arguments={"version": "1", "app_id": "synthetic-app"}, effect="external_write")


async def test_failed_write_is_uncertain_not_proof_of_no_effect(execution_db):
    initial = await started()
    async with repository() as repo:
        attempt = initial["state"]["run_id"]
        action = await repo.prepare_action("task-one", attempt, tool_key="save_file", arguments={"path": "a"}, effect="local_write")
        await repo.action_started("task-one", attempt, action["id"])
        await repo.action_finished("task-one", attempt, action["id"], status="failed", error_code="connection_lost")
        assert (await repo.db.get(TaskAction, action["id"])).status == "uncertain"
        with pytest.raises(TaskError, match="reconciliation_required"):
            await repo.finish("task-one", attempt, phase="succeeded", results=(
                CheckResult(check_id="openable", status="passed", evaluator="deterministic", evidence=(evidence(),)),))


async def test_event_cursor_is_ordered_deduplicable_and_persistent(execution_db):
    initial = await started()
    async with repository() as repo:
        await repo.checkpoint("task-one", initial["state"]["run_id"], initial["budget"], Progress())
        await repo.finish("task-one", initial["state"]["run_id"], phase="waiting_user", reason="review_required")
    async with repository() as repo:
        first = await repo.events("task-one", limit=2)
        second = await repo.events("task-one", after=first["cursor"])
        assert [item["sequence"] for item in first["events"] + second["events"]] == [1, 2, 3]
        assert first["has_more"] and not second["has_more"]
        assert (await repo.events("task-one", after=second["cursor"]))["events"] == []
        with pytest.raises(TaskError, match="task_not_found"):
            await repo.events("task-one", owner_id="other-owner")


async def test_success_requires_all_real_acceptance_results(execution_db):
    initial = await started()
    async with repository() as repo:
        with pytest.raises(ValueError, match="all acceptance"):
            await repo.finish("task-one", initial["state"]["run_id"], phase="succeeded")
        result = await repo.finish("task-one", initial["state"]["run_id"], phase="succeeded", results=(
            CheckResult(check_id="openable", status="passed", evaluator="deterministic", evidence=(evidence(),)),))
        assert result["state"]["phase"] == "succeeded"
        with pytest.raises(TaskError, match="cannot_start"):
            await repo.start("task-one", result["version"], explicit_resume=True)


async def test_checkpoint_rejects_reset_and_credentials_never_enter_journal(execution_db):
    initial = await started()
    budget = Budget.from_snapshot(initial["budget"])
    budget.tool()
    async with repository() as repo:
        await repo.checkpoint("task-one", initial["state"]["run_id"], budget.snapshot(), Progress())
    async with repository() as repo:
        with pytest.raises(TaskError, match="cannot_reset"):
            await repo.checkpoint("task-one", initial["state"]["run_id"], initial["budget"], Progress())
        with pytest.raises(TaskError, match="not_journalable"):
            await repo.prepare_action("task-one", initial["state"]["run_id"], tool_key="send",
                                      arguments={"text": "password: synthetic-private-value"}, effect="external_write")
        for arguments in ({"password": "synthetic-private-value"}, {"nested": [{"api_key": "abc"}]},
                          {"headers": {"Authorization": "synthetic-private-value"}}):
            with pytest.raises(TaskError, match="not_journalable"):
                await repo.prepare_action("task-one", initial["state"]["run_id"], tool_key="send",
                                          arguments=arguments, effect="external_write")
    async with execution_db() as db:
        assert (await db.execute(select(TaskAction))).scalars().all() == []
        for model in (TaskEvent, TaskCheckpoint):
            rows = (await db.execute(select(model))).scalars().all()
            assert "synthetic-private-value" not in str([row.__dict__ for row in rows])


async def test_temporary_tasks_and_scope_spoofing_are_not_persisted(execution_db):
    async with repository() as repo:
        with pytest.raises(TaskError, match="temporary"):
            await repo.create(spec(memory_mode="temporary"), "conversation")
        with pytest.raises(TaskError, match="scope_denied"):
            await repo.create(spec(), "conversation", owner_id="someone-else")
        with pytest.raises(TaskError, match="credentials_not_task_data"):
            await repo.create(spec(instruction="password: synthetic-secret"), "conversation")
    async with execution_db() as db:
        assert (await db.execute(select(CompanionTask))).scalars().all() == []


async def test_goal_revision_preserves_usage_and_fences_old_attempt_cleanup(execution_db):
    from server.db.models import TaskRevision
    initial = await started()
    budget = Budget.from_snapshot(initial["budget"])
    budget.model_request(10)
    async with repository() as repo:
        await repo.checkpoint("task-one", initial["state"]["run_id"], budget.snapshot(), Progress(completed_steps=("old-step",)))
        failed = await repo.finish("task-one", initial["state"]["run_id"], phase="failed")
        revised = await repo.revise("task-one", failed["version"], spec(revision=2, instruction="Verify the revised document",
                                                                         budget={"model_requests": 64}))
        assert revised["state"]["phase"] == "waiting_user"
        assert revised["budget"]["id"] == initial["budget"]["id"]
        assert revised["budget"]["used"]["model_requests"] == 1
        assert revised["budget"]["limits"]["model_requests"] == 64
        assert (await repo.db.get(TaskRevision, ("task-one", 1))).spec["instruction"] == "Create and verify a document"
        assert (await repo.latest_checkpoint("task-one"))["spec_revision"] == 1
        with pytest.raises(TaskError, match="attempt_stale"):
            await repo.checkpoint("task-one", initial["state"]["run_id"], budget.snapshot(), Progress(), retain_stopped=True)
        with pytest.raises(TaskError, match="explicit_resume"):
            await repo.start("task-one", revised["version"])
        next_attempt = await repo.start("task-one", revised["version"], explicit_resume=True)
        assert next_attempt["state"]["spec_revision"] == 2


async def test_project_change_is_checked_at_the_actual_action_boundary(execution_db):
    from server.db.models import Project
    async with execution_db() as db:
        db.add(Project(id="project", name="Project", version=1))
        await db.commit()
    scoped = spec(scope={"kind": "task", "owner_id": "local", "task_id": "task-one", "project_id": "project"})
    async with repository() as repo:
        created = await repo.create(scoped, "conversation")
        initial = await repo.start("task-one", created["version"])
    async with execution_db() as db:
        project = await db.get(Project, "project")
        project.version = 2
        await db.commit()
    async with repository() as repo:
        with pytest.raises(TaskError, match="project_changed"):
            await repo.prepare_action("task-one", initial["state"]["run_id"], tool_key="publish", arguments={}, effect="external_write")
        failed = await repo.finish("task-one", initial["state"]["run_id"], phase="failed", reason="task_project_changed")
        with pytest.raises(TaskError, match="project_changed"):
            await repo.start("task-one", failed["version"], explicit_resume=True)
        assert (await repo.db.execute(select(TaskAction))).scalars().all() == []


def test_budget_restore_preserves_limits_usage_and_stop_reason():
    budget = Budget(Limits(model_requests=3, tokens=100))
    budget.model_request(10)
    budget.tokens = 130  # Usage can overshoot a post-response threshold.
    snapshot = budget.snapshot()
    restored = Budget.from_snapshot(snapshot, limits=Limits(model_requests=99, tokens=999))
    assert restored.limits.tokens == 100 and restored.limits.model_requests == 3
    assert restored.tokens == 130 and restored.model_requests == 1
    with pytest.raises(BudgetExceeded, match="tokens"):
        restored.model_request(10)
    stopped = Budget.from_snapshot(restored.snapshot())
    with pytest.raises(BudgetExceeded, match="tokens"):
        stopped.check()


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), True, "1"])
def test_budget_restore_rejects_invalid_usage(bad):
    snapshot = Budget().snapshot()
    snapshot["used"]["tokens"] = bad
    with pytest.raises(ValueError):
        Budget.from_snapshot(snapshot)

"""Approval must bind both effect classification and the bytes sent to a tool."""
import pytest
from uuid import uuid4

from server.db.models import ActionGrantRecord, TaskAction
from server.services.task_repository import TaskError, repository
from tests.server.test_action_permissions import issue, setup_action, start


@pytest.mark.parametrize("tool", ["asc.draft.update", "asc.screenshot.upload"])
@pytest.mark.parametrize("effect", ["read", "local_write"])
async def test_account_writes_cannot_be_prepared_with_weaker_effect(execution_db, tool, effect):
    data = await setup_action(execution_db)
    with pytest.raises(TaskError, match="task_action_effect_mismatch"):
        async with repository() as repo:
            await repo.prepare_action(data["task_id"], data["attempt_id"], tool_key=tool,
                                      arguments={"after": "another value"}, effect=effect)


async def test_legacy_or_tampered_effect_cannot_receive_approval(execution_db):
    data = await setup_action(execution_db)
    async with execution_db() as db:
        action = await db.get(TaskAction, data["action_id"])
        action.effect = "read"
        await db.commit()
    with pytest.raises(TaskError, match="grant_action_unavailable"):
        await issue(data)


async def test_account_admission_requires_actual_arguments_without_burning_grant(execution_db):
    data = await setup_action(execution_db)
    grant = await issue(data)
    with pytest.raises(TaskError, match="task_action_arguments_required"):
        async with repository() as repo:
            await repo.action_started(data["task_id"], data["attempt_id"], data["action_id"], grant_id=grant)
    async with execution_db() as db:
        assert (await db.get(ActionGrantRecord, grant)).consumed_at is None
        assert (await db.get(TaskAction, data["action_id"])).status == "prepared"


async def test_changed_arguments_rejected_and_original_canonical_order_accepted(execution_db):
    data = await setup_action(execution_db)
    grant = await issue(data)
    with pytest.raises(TaskError, match="task_action_intent_mismatch"):
        await start(data, grant, {"before": "old", "after": "unapproved"})
    async with execution_db() as db:
        assert (await db.get(ActionGrantRecord, grant)).consumed_at is None
        assert (await db.get(TaskAction, data["action_id"])).status == "prepared"
    await start(data, grant, {"after": "new", "before": "old"})


async def test_account_reads_repeat_with_distinct_verifiable_intents(execution_db):
    data = await setup_action(execution_db, "asc.read")
    await start(data, await issue(data))
    async with repository() as repo:
        second = await repo.prepare_action("task", data["attempt_id"], tool_key="asc.read",
            arguments={"before": "old", "after": "new"}, effect="read")
        row = await repo.db.get(TaskAction, second["id"])
        assert row.intent_hash != data["approved_diff_hash"]
        second_data = {**data, "action_id": row.id, "approved_diff_hash": row.intent_hash,
                       "confirmation_ref": str(uuid4())}
    await start(second_data, await issue(second_data))


async def test_changed_effect_after_approval_cannot_consume_grant(execution_db):
    data = await setup_action(execution_db)
    grant = await issue(data)
    async with execution_db() as db:
        (await db.get(TaskAction, data["action_id"])).effect = "local_write"
        await db.commit()
    with pytest.raises(TaskError, match="grant_action_unavailable"):
        await start(data, grant)
    async with execution_db() as db:
        assert (await db.get(ActionGrantRecord, grant)).consumed_at is None


async def test_failed_account_write_requires_reconciliation(execution_db):
    data = await setup_action(execution_db)
    await start(data, await issue(data))
    async with repository() as repo:
        await repo.action_finished("task", data["attempt_id"], data["action_id"], status="failed")
    async with execution_db() as db:
        assert (await db.get(TaskAction, data["action_id"])).status == "uncertain"


async def test_legacy_read_hash_with_unknown_nonce_fails_closed(execution_db):
    data = await setup_action(execution_db, "asc.read")
    async with execution_db() as db:
        row = await db.get(TaskAction, data["action_id"])
        row.intent_hash = "c" * 64
        await db.commit()
    data = {**data, "approved_diff_hash": "c" * 64}
    grant = await issue(data)
    with pytest.raises(TaskError, match="task_action_intent_mismatch"):
        await start(data, grant)
    async with execution_db() as db:
        assert (await db.get(ActionGrantRecord, grant)).consumed_at is None
        assert (await db.get(TaskAction, data["action_id"])).status == "prepared"

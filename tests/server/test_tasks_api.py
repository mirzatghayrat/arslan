import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from arslan.companion.contracts import TaskSpec
from server import auth
from server.api.tasks import router
from server.db.models import TaskAction, TaskEvent
from server.services.task_repository import repository


@pytest.fixture
async def api(execution_db, monkeypatch):
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-task-token")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                headers={"Authorization": "Bearer synthetic-task-token"}) as client:
        yield client


async def seed():
    spec = TaskSpec.model_validate({
        "id": "api-task", "scope": {"kind": "task", "owner_id": "local", "task_id": "api-task"},
        "instruction": "Prepare a result", "locale": "en",
        "acceptance": [{"id": "review", "description": "Review result", "evaluator": "human"}],
    })
    async with repository() as repo:
        row = await repo.create(spec, "api-conversation")
        return await repo.start("api-task", row["version"])


async def test_task_read_and_acceptance_require_auth_and_current_version(api):
    initial = await seed()
    async with repository() as repo:
        waiting = await repo.finish("api-task", initial["state"]["run_id"], phase="waiting_user",
                                    reason="acceptance_review_required")
    assert (await api.get("/api/v1/tasks", headers={"Authorization": "Bearer wrong"})).status_code == 401
    assert len((await api.get("/api/v1/tasks?conversation_id=api-conversation")).json()) == 1
    assert (await api.get("/api/v1/tasks?conversation_id=other")).json() == []
    assert (await api.get("/api/v1/tasks/unknown")).status_code == 404
    assert (await api.post("/api/v1/tasks/api-task/accept", json={"expected_version": 1})).status_code == 409
    response = await api.post("/api/v1/tasks/api-task/accept", json={"expected_version": waiting["version"]})
    assert response.status_code == 200 and response.json()["state"]["phase"] == "succeeded"
    check = response.json()["state"]["results"][0]
    assert check["evaluator"] == "human" and check["evidence"][0]["id"].startswith("human-review:")
    events = (await api.get("/api/v1/tasks/api-task/events")).json()
    assert events["events"][-1]["kind"] == "human_acceptance"
    assert events["events"][-1]["payload"]["review_id"] == check["evidence"][0]["id"]
    assert (await api.get("/api/v1/tasks/api-task/events?after=999")).status_code == 422


async def test_manual_reconciliation_records_review_not_automatic_verification(api, execution_db):
    initial = await seed()
    async with repository() as repo:
        action = await repo.prepare_action("api-task", initial["state"]["run_id"], tool_key="synthetic_write",
                                          arguments={"private_business_text": "not returned"}, effect="external_write")
        await repo.action_started("api-task", initial["state"]["run_id"], action["id"])
        await repo.recover_interrupted()
    detail = (await api.get("/api/v1/tasks/api-task")).json()
    assert "not returned" not in str(detail) and "intent_hash" not in str(detail)
    review = {"expected_version": detail["actions"][0]["version"], "applied": False,
              "note": "I checked the target system; the value was not changed."}
    path = f"/api/v1/tasks/api-task/actions/{action['id']}/reconcile"
    assert (await api.post(path, json={**review, "note": "password: synthetic-secret"})).status_code == 422
    response = await api.post(path, json=review)
    assert response.status_code == 200
    async with execution_db() as db:
        row = await db.get(TaskAction, action["id"])
        assert row.status == "not_applied" and row.evidence[0]["id"].startswith("human-review:")
        before = len((await db.execute(select(TaskEvent))).scalars().all())
    assert (await api.post(path, json=review)).status_code == 409
    async with execution_db() as db:
        assert len((await db.execute(select(TaskEvent))).scalars().all()) == before


async def test_cancel_is_durable_and_does_not_claim_execution_resumed(api):
    initial = await seed()
    response = await api.post("/api/v1/tasks/api-task/cancel", json={"expected_version": initial["version"]})
    assert response.status_code == 200 and response.json()["cancel_requested"]
    assert response.json()["state"]["phase"] == "cancelled"
    # Reading or reconnecting to events has no execution side effect.
    assert (await api.get("/api/v1/tasks/api-task/events")).status_code == 200
    assert (await api.get("/api/v1/tasks/api-task")).json()["state"]["phase"] == "cancelled"

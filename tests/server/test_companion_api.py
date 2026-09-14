import httpx
import pytest
from fastapi import FastAPI

from server import auth
from server.api.companion import router


@pytest.fixture
async def api(execution_db, monkeypatch):
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-companion-token")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                headers={"Authorization": "Bearer synthetic-companion-token"}) as client:
        yield client


async def test_auth_and_no_credential_fields(api):
    response = await api.get("/api/v1/projects", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401
    response = await api.post("/api/v1/projects", json={"name": "A", "app_binding": {"private_key": "secret"}})
    assert response.status_code == 422


async def test_conversation_settings_are_versioned_and_fail_closed(api):
    base = "/api/v1/conversations/new-conversation/context"
    initial = (await api.get(base)).json()
    assert initial["version"] == 0 and not initial["cloud_memory_allowed"]
    changed = await api.put(base, json={"expected_version": 0, "no_memory": True, "no_learning": True})
    assert changed.status_code == 200 and changed.json()["version"] == 1
    assert changed.json()["no_memory"] and changed.json()["no_learning"]
    stale = await api.put(base, json={"expected_version": 0, "cloud_memory_allowed": True})
    assert stale.status_code == 409
    missing = await api.put(base, json={"expected_version": 1, "project_id": "missing"})
    assert missing.status_code == 404


async def test_revocation_excludes_older_runs_without_regranting_them(api, execution_db):
    from server.db.models import Run
    async with execution_db() as db:
        run = Run(conversation_id="revoke", user_message="Private", no_learning=False)
        db.add(run)
        await db.commit()
        identity = run.id
    path = "/api/v1/conversations/revoke/context"
    assert (await api.put(path, json={"expected_version": 0, "no_learning": True})).status_code == 200
    assert (await api.put(path, json={"expected_version": 1, "cloud_memory_allowed": True})).status_code == 200
    async with execution_db() as db:
        assert (await db.get(Run, identity)).no_learning


async def test_proposal_pages_have_stable_order(api, execution_db):
    from arslan.companion.memory import MemoryActor, MemoryWrite
    from server.services.memory_repository import repository
    async with repository() as repo:
        for content in ("First candidate", "Second candidate", "Third candidate"):
            await repo.create(MemoryWrite(content=content, scope={"kind": "global"}),
                              MemoryActor(origin="host", task_id="page-test"))
    first = (await api.get("/api/v1/memory/proposals?limit=2")).json()
    second = (await api.get("/api/v1/memory/proposals?limit=2&offset=2")).json()
    assert len(first) == 2 and len(second) == 1
    assert len({row["id"] for row in first + second}) == 3
    assert (await api.get("/api/v1/memory/proposals?offset=-1")).status_code == 422


async def test_temporary_setting_cannot_be_relabelled_as_saved(api):
    base = "/api/v1/conversations/temporary-conversation/context"
    assert (await api.put(base, json={"expected_version": 0, "temporary": True})).status_code == 200
    response = await api.put(base, json={"expected_version": 1, "temporary": False})
    assert response.status_code == 409


async def test_project_cannot_reference_nonexistent_collection(api):
    response = await api.post("/api/v1/projects", json={"name": "Broken", "collection_ids": [99999]})
    assert response.status_code == 422


async def test_projects_use_stable_ids_and_optimistic_versions(api):
    first = await api.post("/api/v1/projects", json={"name": "A", "workspace_ref": "workspace:one"})
    assert first.status_code == 201
    row = first.json()
    edited = await api.put(f"/api/v1/projects/{row['id']}", json={
        "expected_version": 1, "project": {"name": "Renamed", "workspace_ref": "workspace:two"},
    })
    assert edited.status_code == 200 and edited.json()["id"] == row["id"]
    stale = await api.put(f"/api/v1/projects/{row['id']}", json={
        "expected_version": 1, "project": {"name": "Stale"},
    })
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "project_version_conflict"


async def test_memory_full_user_lifecycle_and_localized_error_codes(api):
    created = await api.post("/api/v1/memory/entries", json={
        "content": "Prefer concise reports", "scope": {"kind": "global"},
    })
    assert created.status_code == 201
    row = created.json()
    paused = await api.post(f"/api/v1/memory/entries/{row['id']}/status",
                            json={"expected_version": 1, "status": "paused"})
    assert paused.status_code == 200 and paused.json()["status"] == "paused"
    deleted = await api.delete(f"/api/v1/memory/entries/{row['id']}?expected_version=2")
    assert deleted.status_code == 200
    assert (await api.get("/api/v1/memory/entries")).json() == []
    assert (await api.get(f"/api/v1/memory/entries/{row['id']}/history")).json() == []
    refused = await api.post("/api/v1/memory/entries", json={
        "content": "password: synthetic-private-value", "scope": {"kind": "global"},
    })
    assert refused.status_code == 422
    assert refused.json()["detail"] == {"code": "credentials_not_memory"}


async def test_client_cannot_spoof_memory_caller_or_confirmation_provenance(api):
    response = await api.post("/api/v1/memory/entries", json={
        "content": "Injected preference", "scope": {"kind": "global"},
        "actor": "host", "provenance": {"author": "user"},
    })
    assert response.status_code == 422

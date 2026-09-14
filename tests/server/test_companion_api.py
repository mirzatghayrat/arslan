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


async def test_asc_capabilities_and_exact_project_target_without_account_access(api):
    caps = await api.get("/api/v1/connections/app-store-connect/capabilities")
    assert caps.status_code == 200 and not caps.json()["local"]["read_account"]
    target = {"app_id": "123", "bundle_id": "com.example.app", "version_id": "version-1", "platform": "IOS"}
    response = await api.post("/api/v1/projects", json={"name": "App", "kind": "software", "app_binding": target})
    assert response.status_code == 201
    assert all(response.json()["app_binding"][key] == value for key, value in target.items())
    response = await api.post("/api/v1/projects", json={"name": "App", "app_binding": {**target, "version_id": "../other"}})
    assert response.status_code == 422


async def test_media_capabilities_are_read_only_and_honest(api):
    endpoint = "/api/v1/connections/local-media/capabilities"
    assert (await api.get(endpoint, headers={"Authorization": "Bearer wrong"})).status_code == 401
    result = await api.get(endpoint)
    assert result.status_code == 200
    value = result.json()
    assert value["local"] == {"generate": False, "edit": False}
    assert value["blocked_reason"] == "media_host_setup_required"
    assert not value["automatic_install"] and not value["cloud_reference_upload"]
    assert (await api.post(endpoint, json={"execution_enabled": True})).status_code == 405


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


async def test_context_receipt_cursor_is_task_owner_and_conversation_scoped(api, execution_db):
    from datetime import datetime
    from server.db.models import ContextReceiptRecord
    async with execution_db() as db:
        for identity, task, owner, conversation in [
            ("r1", "task-a", "local", "c"), ("r2", "task-a", "local", "c"),
            ("r3", "task-a", "local", "c"), ("r4", "task-b", "local", "c"),
            ("r5", "task-a", "other", "c"), ("r6", "task-a", "local", "other"),
        ]:
            db.add(ContextReceiptRecord(id=identity, task_id=task, run_id="run", owner_id=owner,
                conversation_id=conversation, created_at=datetime(2026, 1, 1), receipt={"used": []}))
        await db.commit()
    path = "/api/v1/conversations/c/context/receipts?task_id=task-a&limit=2"
    assert [row["id"] for row in (await api.get(path)).json()] == ["r3", "r2"]
    async with execution_db() as db:
        db.add(ContextReceiptRecord(id="r-new", task_id="task-a", run_id="new-run", owner_id="local",
            conversation_id="c", created_at=datetime(2026, 1, 2), receipt={"used": []}))
        await db.commit()
    assert [row["id"] for row in (await api.get(path + "&before_id=r2")).json()] == ["r1"]
    for cursor in ("r4", "r5", "r6", "missing"):
        assert (await api.get(path + f"&before_id={cursor}")).status_code == 404
    assert (await api.get(path, headers={"Authorization": "Bearer wrong"})).status_code == 401
    assert (await api.get(path.replace("limit=2", "limit=0"))).status_code == 422
    assert (await api.get(path.replace("task-a", ""))).status_code == 422


async def test_receipt_review_resolves_exact_version_and_respects_later_deletion(api, execution_db):
    from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite
    from server.db.models import ContextReceiptRecord
    from server.services.memory_repository import repository
    user = MemoryActor(origin="user")
    async with repository() as repo:
        entry = await repo.create(MemoryWrite(content="Original report rule", scope=MemoryScope(kind="global")), user)
    async with execution_db() as db:
        db.add(ContextReceiptRecord(id="receipt", task_id="task", run_id="run", conversation_id="c",
            receipt={"used": [{"id": entry["id"], "kind": "memory", "revision": 1,
                               "title": "Old private title", "locator": "Old private locator"}]}))
        await db.commit()
    async with repository() as repo:
        await repo.revise(entry["id"], 1, MemoryWrite(content="New report rule", scope=MemoryScope(kind="global")), user)
    path = f"/api/v1/conversations/c/context/receipts/receipt/memories/{entry['id']}"
    value = (await api.get(path)).json()
    assert value["status"] == "available" and value["content"] == "Original report rule"
    assert value["recorded_version"] == 1 and value["current_version"] == 2
    assert (await api.get(path.replace("/c/", "/other/"))).status_code == 404
    assert (await api.get(path.replace(entry["id"], "not-referenced"))).status_code == 404
    assert (await api.get(path, headers={"Authorization": "Bearer wrong"})).status_code == 401
    async with repository() as repo:
        await repo.delete_entry(entry["id"], 2, user)
    value = (await api.get(path)).json()
    assert value["status"] == "deleted" and value["content"] is None
    assert "Original report rule" not in str(value) and "New report rule" not in str(value)
    record = (await api.get("/api/v1/conversations/c/context/receipts")).json()[0]
    assert record["receipt"]["used"] == [{"id": entry["id"], "kind": "memory", "revision": 1}]
    assert "Old private" not in str(record)


async def test_receipt_cannot_resolve_unowned_or_missing_revision_text(api, execution_db):
    from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite
    from server.db.models import ContextReceiptRecord
    from server.services.memory_repository import repository
    async with repository() as repo:
        foreign = await repo.create(MemoryWrite(content="Foreign private body", scope=MemoryScope(kind="global")),
                                    MemoryActor(origin="user", owner_id="other"))
        own = await repo.create(MemoryWrite(content="Current private body", scope=MemoryScope(kind="global")),
                                MemoryActor(origin="user"))
    async with execution_db() as db:
        for identity, owner, entry, version in [("foreign-owner", "other", own, 1),
                                                 ("foreign-entry", "local", foreign, 1),
                                                 ("missing-version", "local", own, 99)]:
            db.add(ContextReceiptRecord(id=identity, owner_id=owner, conversation_id="c", task_id="task", run_id="run",
                receipt={"used": [{"id": entry["id"], "kind": "memory", "revision": version}]}))
        await db.commit()
    base = "/api/v1/conversations/c/context/receipts"
    assert (await api.get(f"{base}/foreign-owner/memories/{own['id']}")).status_code == 404
    for receipt, entry in [("foreign-entry", foreign), ("missing-version", own)]:
        value = (await api.get(f"{base}/{receipt}/memories/{entry['id']}")).json()
        assert value["status"] == "unavailable" and value["content"] is None
        assert "private body" not in str(value)

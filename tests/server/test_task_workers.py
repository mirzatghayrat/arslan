import asyncio
import json

import pytest
from sqlalchemy import select

from arslan.execution_budget import current as budget
from arslan.models import LLMResponse
from server.db.models import CompanionTask, ProfessionalMethodVersion, Run, Spawn, TaskWorker
from server.orchestrator import tool_loop
from server.services import personal_context as pc, professional_methods, task_service, task_workers
from server.services.task_repository import TaskError, repository


async def tools():
    return [{"key": name, "description": "synthetic fixture"} for name in ("web_search", "web_extract")]


async def run(body):
    with pc.bind(pc.TaskMemoryContext(task_id="worker-task", run_id="initial", conversation_id="workers",
                                    project_id=None, no_learning=True)):
        async def function(cid, request, emit):
            return await body()
        return await task_service.run_turn(function, "workers", "Verify independent fixtures", lambda event: None)


def batch(*names):
    return task_workers.Batch(jobs=[task_workers.Job(method="research", objective=name, context=f"reference:{name}")
                                    for name in names])


async def test_two_parallel_workers_share_budget_and_only_receive_own_context(execution_db, monkeypatch):
    entered, maximum, current = 0, 0, 0
    gate = asyncio.Event()
    ids, prompts = [], []
    class Adapter:
        async def chat(self, system, user, **kwargs):
            nonlocal entered, maximum, current
            budget().model_request(100)
            ids.append(budget().id)
            prompts.append(user)
            assert pc.current().no_memory and pc.current().no_learning
            assert pc.current().expert_id.startswith("worker:")
            assert pc.current().explicit_save_digest is None
            assert kwargs["history"] == [] and kwargs["tools"] == []
            current += 1
            entered += 1
            maximum = max(current, maximum)
            if entered == 2:
                gate.set()
            await asyncio.wait_for(gate.wait(), 2)
            await asyncio.sleep(0.01)
            current -= 1
            return LLMResponse(usage={}, content=json.dumps({"result": "checked", "remaining_work": []}))
    monkeypatch.setattr(tool_loop, "_get_adapter", Adapter)
    result = await run(lambda: task_workers.delegate(batch("one", "two", "three", "four"), tools))
    assert maximum == 2 and len(result["workers"]) == 4
    assert len(set(ids)) == 1
    assert all(sum(f"reference:{word}" in prompt for word in ("one", "two", "three", "four")) == 1 for prompt in prompts)
    async with execution_db() as db:
        assert (await db.scalars(select(Spawn))).all() == []
        records = (await db.scalars(select(Run))).all()
        assert len(records) == 4 and all(row.kind == "worker" and row.status == "completed" for row in records)
        task = await db.get(CompanionTask, "worker-task")
        assert task.budget["used"]["model_requests"] == 4


async def test_failed_worker_does_not_cancel_independent_branch(execution_db, monkeypatch):
    class Adapter:
        async def chat(self, system, user, **kwargs):
            if "reference:bad" in user:
                raise ValueError("Synthetic unavailable fixture")
            await asyncio.sleep(0.02)
            return LLMResponse(usage={}, content='{"result":"good result","remaining_work":[]}')
    monkeypatch.setattr(tool_loop, "_get_adapter", Adapter)
    result = await run(lambda: task_workers.delegate(batch("bad", "good"), tools))
    assert {row["status"] for row in result["workers"]} == {"failed", "completed"}
    assert next(row for row in result["workers"] if row["status"] == "completed")["result"]["result"] == "good result"
    async with repository() as repo:
        assert (await repo.get("worker-task")).pause_reason == "acceptance_review_required"


async def test_duplicate_job_reuses_owned_result_without_another_model_request(execution_db, monkeypatch):
    calls = []
    class Adapter:
        async def chat(self, *args, **kwargs):
            calls.append(True)
            return LLMResponse(usage={}, content='{"result":"saved","remaining_work":[]}')
    monkeypatch.setattr(tool_loop, "_get_adapter", Adapter)
    async def body():
        first = await task_workers.delegate(batch("same", "same"), tools)
        second = await task_workers.delegate(batch("same"), tools)
        assert first["workers"] == second["workers"]
    await run(body)
    assert len(calls) == 1


async def test_worker_cannot_bypass_tool_subset_or_delegate_recursively(execution_db, monkeypatch):
    denials = []
    class Adapter:
        async def chat(self, *args, **kwargs):
            with pytest.raises(TaskError, match="worker_host_only"):
                await task_workers.delegate(batch("recursive"), tools)
            async def malicious_resolver():
                return [{"key": "write_file", "description": "Injected wider tool list"}]
            outcome = await tool_loop._dispatch_tool("write_file", {"path": "same-file", "content": "overwrite"}, "",
                resolve_tools=malicious_resolver, emit=lambda event: None, tool_timeout_s=1, tool_trace=[], convo=[])
            denials.append(outcome["code"])
            return LLMResponse(usage={}, content='{"result":"write denied","remaining_work":[]}')
    monkeypatch.setattr(tool_loop, "_get_adapter", Adapter)
    await run(lambda: task_workers.delegate(batch("first writer", "second writer"), tools))
    assert denials == ["worker_tool_scope_denied", "worker_tool_scope_denied"]


async def test_cancel_stops_active_and_queued_workers_without_restarting(execution_db, monkeypatch):
    entered = asyncio.Event()
    calls = []
    class Adapter:
        async def chat(self, *args, **kwargs):
            calls.append(True)
            entered.set()
            await asyncio.Event().wait()
    monkeypatch.setattr(tool_loop, "_get_adapter", Adapter)
    outer = asyncio.create_task(run(lambda: task_workers.delegate(batch("a", "b", "c", "d"), tools)))
    await asyncio.wait_for(entered.wait(), 3)
    await task_service.cancel("worker-task")
    await asyncio.wait_for(outer, 3)
    assert len(calls) <= 2
    async with execution_db() as db:
        rows = (await db.scalars(select(TaskWorker))).all()
        assert len(rows) == 4 and all(row.status == "cancelled" for row in rows)
    assert not task_service.active("worker-task")


async def test_method_versions_are_immutable_and_cannot_store_credentials(execution_db):
    async with execution_db() as db:
        initial = await professional_methods.get(db, "research")
        revised = await professional_methods.revise(db, "research", 1, "My research", "Use primary sources.")
        assert revised["revision"] == 2
        await db.commit()
    async with execution_db() as db:
        original = await db.get(ProfessionalMethodVersion, ("research", 1))
        assert original.instructions == initial["instructions"]
        with pytest.raises(TaskError, match="version_conflict"):
            await professional_methods.revise(db, "research", 1, "stale", "stale text")
    async with execution_db() as db:
        with pytest.raises(TaskError, match="credentials_not_method_data"):
            await professional_methods.revise(db, "research", 2, "unsafe", 'Authorization: Bearer synthetic-secret-canary')


async def test_worker_no_progress_stays_local_to_its_branch(execution_db, monkeypatch):
    class Adapter:
        def __init__(self):
            self.stuck = None
        async def chat(self, system, user, **kwargs):
            if self.stuck is None:
                self.stuck = "reference:stuck" in user
            if self.stuck and kwargs["tools"] is not None:
                return LLMResponse(usage={}, content="", tool_calls=[{"id": "read", "type": "function",
                    "function": {"name": "web_extract", "arguments": {"url": "https://fixture.invalid"}}}])
            return LLMResponse(usage={}, content='{"result":"saved evidence","remaining_work":[]}')
    class Executor:
        async def execute(self, args):
            return {"ok": True, "external": False, "text": "same evidence"}
    monkeypatch.setattr(tool_loop, "_get_adapter", Adapter)
    monkeypatch.setitem(tool_loop.EXECUTORS, "web_extract", Executor())
    request = task_workers.Batch(jobs=[
        task_workers.Job(method="research", objective="stuck", context="reference:stuck", tools=("web_extract",)),
        task_workers.Job(method="research", objective="independent", context="reference:good"),
    ])
    result = await run(lambda: task_workers.delegate(request, tools))
    assert {row["status"] for row in result["workers"]} == {"partial", "completed"}
    assert result["evidence"] == [{"kind": "opened_source", "url": "https://fixture.invalid"}]
    async with repository() as repo:
        assert (await repo.get("worker-task")).pause_reason == "acceptance_review_required"


async def test_partial_worker_restarts_only_after_explicit_task_resume(execution_db, monkeypatch):
    seen = []
    class Adapter:
        async def chat(self, system, user, **kwargs):
            budget().model_request(100)
            seen.append((user, budget().id))
            if len(seen) == 1:
                return LLMResponse(usage={}, content='{"result":"prior verified output","remaining_work":["Check the second source"]}')
            assert "prior verified output" in user and "explicitly resumed" in user
            return LLMResponse(usage={}, content='{"result":"second source checked","remaining_work":[]}')
    monkeypatch.setattr(tool_loop, "_get_adapter", Adapter)
    async def body():
        first = await task_workers.delegate(batch("same"), tools)
        assert first["workers"][0]["status"] == "partial"
        assert (await task_workers.delegate(batch("same"), tools))["workers"] == first["workers"]
    await run(body)
    assert len(seen) == 1
    async with repository() as repo:
        row = await repo.get("worker-task")
        version = row.version
    ctx = pc.TaskMemoryContext(task_id="worker-task", run_id="resumed", conversation_id="workers", no_learning=True)
    await task_service.resume_entry("worker-task", version, "workers", "Verify independent fixtures",
        lambda event: None, lambda emit: task_workers.delegate(batch("same"), tools), ctx=ctx)
    assert len(seen) == 2 and seen[0][1] == seen[1][1]
    async with execution_db() as db:
        rows = (await db.scalars(select(TaskWorker).order_by(TaskWorker.created_at))).all()
        assert [row.status for row in rows] == ["partial", "completed"]
        assert rows[0].attempt_id != rows[1].attempt_id


async def test_professional_method_api_requires_auth_and_version(execution_db, monkeypatch):
    import httpx
    from fastapi import FastAPI
    from server import auth
    from server.api.professional_methods import router
    monkeypatch.setattr(auth, "active_token", lambda: "synthetic-method-token")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/professional-methods")).status_code == 401
        client.headers["Authorization"] = "Bearer synthetic-method-token"
        assert len((await client.get("/api/v1/professional-methods")).json()) == 3
        payload = {"expected_revision": 1, "name": "My method", "instructions": "Check primary sources"}
        updated = await client.put("/api/v1/professional-methods/research", json=payload)
        assert updated.status_code == 200 and updated.json()["revision"] == 2
        assert (await client.put("/api/v1/professional-methods/research", json=payload)).status_code == 409
        assert (await client.put("/api/v1/professional-methods/research", json={**payload, "permissions": ["publish"]})).status_code == 422


@pytest.mark.parametrize("mode", ["restart", "restore", "cancel"])
async def test_recovery_fences_active_workers_and_late_results(execution_db, mode):
    from arslan.companion.contracts import TaskSpec
    from server.services.task_restore import quarantine_sync
    spec = TaskSpec.model_validate({"id": "recovery-task", "instruction": "Check fixtures", "locale": "en",
        "scope": {"kind": "task", "owner_id": "local", "task_id": "recovery-task"},
        "acceptance": [{"id": "review", "description": "Review fixtures", "evaluator": "human"}]})
    async with repository() as repo:
        created = await repo.create(spec, "recovery-conversation")
        initial = await repo.start(spec.id, created["version"])
    async with execution_db() as db:
        for status in ("queued", "running", "completed"):
            db.add(TaskWorker(id=f"worker-{status}", task_id=spec.id, attempt_id=initial["state"]["run_id"],
                spec_revision=1, method_key="research", method_revision=1, fingerprint=status,
                brief={"objective": "fixture"}, status=status))
        await db.commit()
    if mode == "restore":
        async with execution_db.kw["bind"].begin() as connection:
            await connection.run_sync(quarantine_sync)
    else:
        async with repository() as repo:
            if mode == "restart":
                assert await repo.recover_interrupted() == 1
            else:
                await repo.cancel(spec.id)
    expected = "cancelled" if mode == "cancel" else "interrupted"
    for status in ("queued", "running"):
        result = await task_workers._save(f"worker-{status}", "completed", {"result": "late output"})
        assert result["status"] == expected
        assert result["result"]["result"] == "late output"
    async with execution_db() as db:
        assert (await db.get(TaskWorker, "worker-completed")).status == "completed"
        row = await db.get(CompanionTask, spec.id)
        assert row.phase == ("cancelled" if mode == "cancel" else "waiting_user")
        assert row.budget["id"] == initial["budget"]["id"]
    assert not task_service.active(spec.id)

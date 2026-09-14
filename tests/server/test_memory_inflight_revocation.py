import pytest
import json
from types import SimpleNamespace

import httpx
from sqlalchemy import insert, select, update

from server.db.models import ProviderConfig, CompanionTask, TaskAction, MemoryEntry, MemoryRevision, Run
from server.orchestrator import arslan, memory, tool_loop
from server.services import knowledge, task_context, task_service, personal_context as pc
from server.services.memory_repository import repository
from arslan.llm.adapter import LLMAdapter
from tests.server.test_context_request_evidence import selected
from server.services.task_repository import TaskError


@pytest.mark.parametrize("delete_before_tool", [True, False])
async def test_deleted_context_stops_real_host_before_next_action(selected, execution_db, monkeypatch, delete_before_tool):
    captured = []
    executed = []
    async with repository() as repo:
        entry = (await repo.list_entries())[0]
    async def handler(request):
        captured.append(json.loads(request.content))
        if len(captured) == 1:
            if delete_before_tool:
                await withdraw()
            return httpx.Response(200, json={"choices": [{"message": {"content": "", "tool_calls": [{
                "id": "fixture-read", "type": "function", "function": {"name": "web_search", "arguments": '{"query":"synthetic report"}'},
            }]}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(**{**kwargs, "transport": httpx.MockTransport(handler)}))
    adapter = LLMAdapter("openai", "fixture", base_url="https://model-fixture.invalid")
    async with execution_db() as db:
        await db.execute(insert(ProviderConfig).values(label="Synthetic", provider="ollama", model="fixture",
            base_url="http://127.0.0.1:11434/v1", api_key="", is_primary=True))
        await db.commit()
    async def empty(*args, **kwargs):
        return []
    async def no_roster(*args, **kwargs):
        return ""
    async def wired():
        return [{"key": "web_search", "description": "Synthetic read"}]
    async def execute(args):
        executed.append(args)
        if not delete_before_tool:
            await withdraw()
        return {"ok": True, "results": [], "summary": "Synthetic read completed"}
    async def withdraw():
        async with repository() as repo:
            from arslan.companion.memory import MemoryActor
            await repo.delete_entry(entry["id"], entry["version"], MemoryActor(origin="user"))
    monkeypatch.setattr(knowledge, "retrieve_scoped", empty)
    monkeypatch.setattr(arslan, "_team_roster", no_roster)
    monkeypatch.setattr(arslan, "_arslan_tools", wired)
    monkeypatch.setitem(tool_loop.EXECUTORS, "web_search", SimpleNamespace(execute=execute))
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    @task_context.scoped_turn
    async def turn(conversation_id, user_message, emit):
        mid = await memory.add_message(conversation_id, "user", user_message)
        task_context.source_message(mid)
        return await arslan._handle_answer(conversation_id, user_message, emit)
    events = []
    with pytest.raises(TaskError, match="task_memory_changed"):
        await turn("inflight-diagnostic", "Prepare a report", events.append)
    assert len(captured) == 1
    assert "Reports should have concise conclusions." in json.dumps(captured[0])
    assert len(executed) == (0 if delete_before_tool else 1)
    assert any(event.get("type") == "task_state" and event.get("phase") == "waiting_user"
               and event.get("pause_reason") == "task_memory_changed"
               for event in events), events
    async with execution_db() as db:
        task = (await db.scalars(select(CompanionTask))).one()
        task_id, version = task.id, task.version
        before_budget = task.budget["used"]["model_requests"]
        actions = (await db.scalars(select(TaskAction))).all()
        assert len(actions) == len(executed)
        assert all(action.status == "succeeded" for action in actions)
        runs = (await db.scalars(select(Run))).all()
        assert all(run.system_prompt is None and run.injected_kb is None for run in runs)
    await task_service.resume_turn(task_id, version, "inflight-diagnostic", events.append)
    assert len(captured) == 2
    assert "Reports should have concise conclusions." not in json.dumps(captured[1])
    assert len(executed) == (0 if delete_before_tool else 1)
    async with execution_db() as db:
        task = await db.get(CompanionTask, task_id)
        assert task.budget["used"]["model_requests"] > before_budget


@pytest.mark.parametrize("change", [
    {"status": "paused"}, {"owner_id": "someone-else"}, {"scope_kind": "expert", "scope_id": "other"},
    {"confirmed_at": None}, {"confirmation_kind": None}, {"superseded_by": "replacement"},
    {"sensitivity": "sensitive"}, {"version": 99},
])
async def test_selected_dependency_rechecks_eligibility(selected, execution_db, change):
    ctx, personal = selected
    dependencies = ((pc.MemoryReadScope.from_context(ctx), tuple((ref.id, ref.revision) for ref in personal.receipt.used)),)
    assert await pc.dependencies_current(dependencies)
    if "superseded_by" in change:
        from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite
        async with repository() as repo:
            replacement = await repo.create(MemoryWrite(content="Replacement report preference.", scope=MemoryScope(kind="global")), MemoryActor(origin="user"))
        change = {"superseded_by": replacement["id"]}
    async with execution_db() as db:
        await db.execute(update(MemoryEntry).where(MemoryEntry.id == personal.receipt.used[0].id).values(**change))
        await db.commit()
    assert not await pc.dependencies_current(dependencies)


async def test_expiry_and_erased_revision_stop_dependency(selected, execution_db):
    from datetime import datetime, timedelta
    ctx, personal = selected
    dependencies = ((pc.MemoryReadScope.from_context(ctx), tuple((ref.id, ref.revision) for ref in personal.receipt.used)),)
    for column in ("expires_at", "review_at", "valid_from"):
        async with execution_db() as db:
            value = datetime.utcnow() + timedelta(days=1 if column == "valid_from" else -1)
            await db.execute(update(MemoryEntry).values(**{column: value}))
            await db.commit()
        assert not await pc.dependencies_current(dependencies)
        async with execution_db() as db:
            await db.execute(update(MemoryEntry).values(**{column: None}))
            await db.commit()
    async with execution_db() as db:
        await db.execute(update(MemoryRevision).values(content=None))
        await db.commit()
    assert not await pc.dependencies_current(dependencies)


async def test_unrelated_change_does_not_stop_task(selected):
    from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite
    ctx, personal = selected
    dependencies = ((pc.MemoryReadScope.from_context(ctx), tuple((ref.id, ref.revision) for ref in personal.receipt.used)),)
    async with repository() as repo:
        other = await repo.create(MemoryWrite(content="Coffee is served in a blue mug.", scope=MemoryScope(kind="global")), MemoryActor(origin="user"))
        await repo.delete_entry(other["id"], other["version"], MemoryActor(origin="user"))
    assert await pc.dependencies_current(dependencies)


@pytest.mark.parametrize("recall", [False, True])
async def test_worker_selections_are_shared_with_root_guard(selected, execution_db, recall):
    import asyncio
    from server.services import memory_tools_v2
    from server.orchestrator.tool_caller import ToolCaller
    from arslan.companion.memory import MemoryActor
    ctx, personal = selected
    async def body(conversation, message, emit):
        runtime = task_service.current()
        async def worker():
            with pc.for_worker("worker"):
                if recall:
                    result = await memory_tools_v2.recall({"query": "report"}, ToolCaller(actor="spawn", spawn_id=1, conversation_id=conversation))
                    assert result["hits"]
                else:
                    await pc.record(await pc.assemble("report"))
        await asyncio.create_task(worker())
        assert runtime.memory_dependencies
        assert "Reports should" not in repr(runtime.memory_dependencies)
        async with repository() as repo:
            ref = personal.receipt.used[0]
            await repo.delete_entry(ref.id, ref.revision, MemoryActor(origin="user"))
        await runtime.check_memory()
    with pc.bind(ctx), pytest.raises(TaskError, match="task_memory_changed"):
        await task_service.run_turn(body, ctx.conversation_id, "Prepare report", lambda event: None)
    assert task_service.current() is None


async def test_guard_storage_failure_is_closed_and_sanitized(selected, monkeypatch):
    import asyncio
    ctx, personal = selected
    async def broken(_):
        raise RuntimeError("private diagnostic contents")
    async def body(conversation, message, emit):
        await pc.record(await pc.assemble("report"))
        runtime = task_service.current()
        monkeypatch.setattr(pc, "dependencies_current", broken)
        with pytest.raises(TaskError, match="^task_memory_check_failed$"):
            await runtime.check_memory()
        async def cancelled(_):
            raise asyncio.CancelledError()
        monkeypatch.setattr(pc, "dependencies_current", cancelled)
        with pytest.raises(asyncio.CancelledError):
            await runtime.check_memory()
    with pc.bind(ctx):
        await task_service.run_turn(body, ctx.conversation_id, "Prepare report", lambda event: None)


async def test_project_archive_and_cloud_policy_are_rechecked(selected, execution_db):
    from dataclasses import replace
    from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite
    from server.db.models import Project
    async with execution_db() as db:
        db.add(Project(id="project", name="Project"))
        await db.commit()
    async with repository() as repo:
        entry = await repo.create(MemoryWrite(content="Project report format.", use_policy="cloud_allowed",
            scope=MemoryScope(kind="project", id="project")), MemoryActor(origin="user"))
    ctx = replace(selected[0], project_id="project", model_is_local=False, cloud_memory_allowed=True)
    dependencies = ((pc.MemoryReadScope.from_context(ctx), ((entry["id"], entry["version"]),)),)
    assert await pc.dependencies_current(dependencies)
    async with execution_db() as db:
        await db.execute(update(Project).values(status="archived"))
        await db.commit()
    assert not await pc.dependencies_current(dependencies)
    async with execution_db() as db:
        await db.execute(update(Project).values(status="active"))
        await db.execute(update(MemoryEntry).where(MemoryEntry.id == entry["id"]).values(use_policy="local_only"))
        await db.commit()
    assert not await pc.dependencies_current(dependencies)


@pytest.mark.parametrize("replace_store", [False, True])
@pytest.mark.parametrize("oversized", [False, True])
async def test_inflight_summary_cannot_restore_deleted_snapshot(selected, execution_db, monkeypatch, replace_store, oversized):
    from server.db.models import ArslanSummary, MemoryStoreState
    from arslan.companion.memory import MemoryActor
    monkeypatch.setenv("ARSLAN_WORKING_TOKEN_BUDGET", "5")
    calls = []
    await memory.add_message("summary-race", "user", "Long first message with sufficient text")
    await memory.add_message("summary-race", "user", "Long second message with sufficient text")
    async def summarize(adapter, text):
        calls.append(text)
        if replace_store:
            async with execution_db() as db:
                await db.execute(update(MemoryStoreState).values(instance_id="replacement-store"))
                await db.commit()
        else:
            ref = selected[1].receipt.used[0]
            async with repository() as repo:
                await repo.delete_entry(ref.id, ref.revision, MemoryActor(origin="user"))
        return "Stale derived summary" * (1000 if oversized else 1)
    monkeypatch.setattr(memory, "_summarize", summarize)
    monkeypatch.setattr(memory, "_get_adapter", lambda: object())
    await memory.maybe_compact("summary-race")
    assert len(calls) == 1
    async with execution_db() as db:
        assert not (await db.scalars(select(ArslanSummary))).all()

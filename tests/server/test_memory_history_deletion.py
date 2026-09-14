from datetime import datetime, timedelta
import json

import httpx
import pytest
from sqlalchemy import insert, select

from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite
from server.db.models import ArslanMessage, ArslanSummary, MemorySuppression, ProviderConfig
from server.orchestrator import arslan, memory, tool_loop
from server.services import knowledge, memory_history, task_context, task_service
from server.services.memory_repository import repository
from tests.server.test_context_request_evidence import selected


@pytest.mark.parametrize("delete_during_request", [False, True])
async def test_real_host_filters_and_revokes_history(selected, execution_db, monkeypatch, delete_during_request):
    from arslan.llm.adapter import LLMAdapter
    from server.services.task_repository import TaskError
    cid = "deleted-source-host"
    body = "Report headings should always be violet."
    mid = await memory.add_message(cid, "user", "Remember: " + body)
    async with repository() as repo:
        entry = await repo.create(MemoryWrite(content=body, scope=MemoryScope(kind="global")),
            MemoryActor(origin="user", source_message_id=mid, conversation_id=cid))
    async def withdraw():
        async with repository() as repo:
            await repo.delete_entry(entry["id"], entry["version"], MemoryActor(origin="user"))
    if not delete_during_request:
        await withdraw()
    captured = []
    async def handler(request):
        captured.append(json.loads(request.content))
        if delete_during_request:
            # Exercise the history guard independently of personal-memory refs.
            runtime = task_service.current()
            assert runtime.history_dependencies[cid][0]
            runtime.memory_dependencies.clear()
            await withdraw()
            return httpx.Response(200, json={"choices": [{"message": {"content": "", "tool_calls": [{
                "id": "fixture-read", "type": "function", "function": {
                    "name": "web_search", "arguments": '{"query":"synthetic"}'}}]}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "Synthetic answer"}}]})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(**{**kwargs, "transport": httpx.MockTransport(handler)}))
    async with execution_db() as db:
        await db.execute(insert(ProviderConfig).values(label="Synthetic", provider="ollama", model="fixture",
            base_url="http://127.0.0.1:11434/v1", api_key="", is_primary=True))
        await db.commit()
    async def empty(*args, **kwargs): return []
    async def no_roster(*args, **kwargs): return ""
    monkeypatch.setattr(knowledge, "retrieve_scoped", empty)
    monkeypatch.setattr(arslan, "_team_roster", no_roster)
    monkeypatch.setattr(arslan, "_arslan_tools", empty)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: LLMAdapter("openai", "fixture", base_url="https://model-fixture.invalid"))
    @task_context.scoped_turn
    async def turn(conversation_id, user_message, emit):
        message_id = await memory.add_message(conversation_id, "user", user_message)
        task_context.source_message(message_id)
        return await arslan._handle_answer(conversation_id, user_message, emit)
    if delete_during_request:
        with pytest.raises(TaskError, match="task_memory_changed"):
            await turn(cid, "Prepare a report", lambda event: None)
    else:
        await turn(cid, "Prepare a report", lambda event: None)
    assert len(captured) == 1
    assert (body in json.dumps(captured[0])) is delete_during_request


async def test_deleted_source_not_in_context_or_new_summary(selected, execution_db, monkeypatch):
    cid = "history-deletion"
    mid = await memory.add_message(cid, "user", "Remember violet headings forever.")
    await memory.add_message(cid, "arslan", "I will use violet headings.")
    async with repository() as repo:
        entry = await repo.create(MemoryWrite(content="Use violet headings.", scope=MemoryScope(kind="global")),
            MemoryActor(origin="user", source_message_id=mid, conversation_id=cid))
        await repo.delete_entry(entry["id"], entry["version"], MemoryActor(origin="user"))
    await memory.add_message(cid, "user", "Prepare a sufficiently detailed new report.")
    await memory.add_message(cid, "arslan", "Here is the new report with sufficient detail.")
    context = await memory.assemble_working_context(cid)
    assert len(context["history"]) == 2
    assert "violet" not in str(context)
    assert not context["truncated"]
    monkeypatch.setenv("ARSLAN_WORKING_TOKEN_BUDGET", "5")
    monkeypatch.setattr(memory, "_summary_token_cap", lambda: 100)
    calls = []
    async def summarize(adapter, text):
        calls.append(text)
        assert "violet" not in text
        return "A new report was requested."
    monkeypatch.setattr(memory, "_summarize", summarize)
    monkeypatch.setattr(memory, "_get_adapter", lambda: object())
    await memory.maybe_compact(cid)
    assert len(calls) == 1
    async with execution_db() as db:
        assert len((await db.scalars(select(ArslanMessage))).all()) == 4
        assert (await db.scalars(select(ArslanSummary))).one().summary == "A new report was requested."


@pytest.mark.parametrize("kind", ["message_id", "conversation_id"])
async def test_cached_history_revalidated_without_bodies(execution_db, kind):
    cid = "cached-history"
    mid = await memory.add_message(cid, "user", "Private old source")
    snapshot = ((cid, (mid,), ()),)
    assert await memory_history.dependencies_current(snapshot)
    async with execution_db() as db:
        db.add(MemorySuppression(source_kind=kind, source_id=str(mid) if kind == "message_id" else cid,
            entry_id="deleted", cutoff_at=datetime.utcnow()))
        await db.commit()
    assert not await memory_history.dependencies_current(snapshot)
    new = await memory.add_message(cid, "user", "New source")
    assert await memory_history.dependencies_current(((cid, (new,), ()),))


async def test_unrelated_suppression_does_not_revoke_history(execution_db):
    mid = await memory.add_message("retained", "user", "Retained source")
    async with execution_db() as db:
        db.add(MemorySuppression(source_kind="conversation_id", source_id="unrelated",
            entry_id="deleted", cutoff_at=datetime.utcnow() + timedelta(seconds=1)))
        await db.commit()
    assert await memory_history.dependencies_current((("retained", (mid,), ()),))

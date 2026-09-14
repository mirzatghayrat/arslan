"""Real provider serialization and HTTP transport boundary; synthetic responses only."""
import asyncio
from dataclasses import replace
import json

import httpx
import pytest
from sqlalchemy import insert, select

from arslan.companion.memory import MemoryActor, MemoryScope, MemoryWrite
from arslan.execution_budget import Budget, BudgetExceeded, Limits, scope
from arslan.llm.adapter import LLMAdapter
from arslan.llm import request_evidence
from server.db.models import ContextReceiptRecord, ProviderConfig
from server.services import personal_context as pc
from server.services.memory_activation import activate_sync
from server.services.memory_migration import migrate_legacy_sync
from server.services.memory_repository import repository


@pytest.fixture
async def selected(execution_db):
    async with execution_db.kw["bind"].begin() as db:
        await db.run_sync(migrate_legacy_sync)
        await db.run_sync(activate_sync)
    async with repository() as repo:
        await repo.create(MemoryWrite(content="Reports should have concise conclusions.", scope=MemoryScope(kind="global")),
                          MemoryActor(origin="user"))
    ctx = pc.TaskMemoryContext(task_id="task", run_id="run", conversation_id="conversation", model_is_local=True)
    return ctx, await pc.assemble("report", context=ctx)


def transport(monkeypatch, provider="openai", *, stream=False, status=200, failure=None):
    captured = []
    response = {
        "openai": {"choices": [{"message": {"content": "ok"}}]},
        "anthropic": {"content": [{"type": "text", "text": "ok"}]},
        "gemini": {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
    }[provider]
    streamed = {
        "openai": {"choices": [{"delta": {"content": "ok"}}]},
        "anthropic": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ok"}},
        "gemini": response,
    }[provider]
    def handler(request):
        captured.append(json.loads(request.content))
        if failure:
            raise failure("Synthetic transport failure", request=request)
        if stream:
            return httpx.Response(status, text="data: " + json.dumps(streamed) + "\n\n",
                                  headers={"content-type": "text/event-stream"})
        return httpx.Response(status, json=response)
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(**{**kwargs, "transport": httpx.MockTransport(handler)}))
    adapter = LLMAdapter(provider, "fixture", api_key="synthetic-not-a-real-key", base_url="https://model-fixture.invalid")
    return adapter, captured


async def receipt(db, selected):
    async with db() as session:
        return (await session.get(ContextReceiptRecord, selected.receipt.id)).receipt


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
@pytest.mark.parametrize("stream", [False, True])
async def test_actual_payload_and_successful_response_are_counted(selected, execution_db, monkeypatch, provider, stream):
    ctx, personal = selected
    adapter, captured = transport(monkeypatch, provider, stream=stream)
    with pc.bind(ctx):
        await pc.record(personal)
        if stream:
            assert "".join([part async for part in adapter.chat_stream(personal.text, "Prepare a report")]) == "ok"
        else:
            assert (await adapter.chat(personal.text, "Prepare a report")).content == "ok"
    assert len(captured) == 1
    assert any(personal.text in part for part in pc._system_fragments(captured[0]))
    stored = await receipt(execution_db, personal)
    assert stored["request_attempts"] == stored["provider_responses"] == 1
    serialized = json.dumps(stored)
    assert "Reports should" not in serialized and "synthetic-not-a-real-key" not in serialized
    assert "model-fixture.invalid" not in serialized


@pytest.mark.parametrize("failure,status", [(None, 403), (httpx.ConnectError, 200)])
async def test_failed_request_does_not_claim_provider_response(selected, execution_db, monkeypatch, failure, status):
    ctx, personal = selected
    adapter, _ = transport(monkeypatch, failure=failure, status=status)
    with pc.bind(ctx):
        await pc.record(personal)
        with pytest.raises(httpx.HTTPError):
            await adapter.chat(personal.text, "report")
    stored = await receipt(execution_db, personal)
    assert stored["request_attempts"] == 1 and stored["provider_responses"] == 0


async def test_budget_refusal_happens_before_request_evidence(selected, execution_db, monkeypatch):
    ctx, personal = selected
    adapter, captured = transport(monkeypatch)
    with pc.bind(ctx), scope(Budget(limits=Limits(model_requests=1))) as budget:
        await pc.record(personal)
        budget.model_request(1)
        with pytest.raises(BudgetExceeded):
            await adapter.chat(personal.text, "report")
    assert captured == []
    assert (await receipt(execution_db, personal))["request_attempts"] == 0


async def test_selection_not_in_system_and_user_quotation_are_not_attributed(selected, execution_db, monkeypatch):
    ctx, personal = selected
    adapter, _ = transport(monkeypatch)
    with pc.bind(ctx):
        await pc.record(personal)
        await adapter.chat("A different synthesis prompt", personal.text)
        await adapter.chat(personal.text[:-10], "report")
    assert (await receipt(execution_db, personal))["request_attempts"] == 0


async def test_new_task_cannot_reuse_prior_registration(selected, execution_db, monkeypatch):
    ctx, personal = selected
    adapter, _ = transport(monkeypatch)
    with pc.bind(ctx):
        await pc.record(personal)
        with pc.bind(replace(ctx, task_id="another-task")):
            await adapter.chat(personal.text, "report")
        assert (await receipt(execution_db, personal))["request_attempts"] == 0
        await adapter.chat(personal.text, "report")
    assert (await receipt(execution_db, personal))["request_attempts"] == 1


async def test_latest_identical_selection_is_the_one_attributed(selected, execution_db, monkeypatch):
    ctx, first = selected
    adapter, _ = transport(monkeypatch)
    with pc.bind(ctx):
        await pc.record(first)
        second = await pc.assemble("report")
        await pc.record(second)
        await adapter.chat(second.text, "report")
    assert (await receipt(execution_db, first))["request_attempts"] == 0
    assert (await receipt(execution_db, second))["request_attempts"] == 1


async def test_worker_and_host_with_identical_text_keep_separate_attribution(selected, execution_db, monkeypatch):
    ctx, host = selected
    adapter, _ = transport(monkeypatch)
    with pc.bind(ctx):
        await pc.record(host)
        with pc.for_worker("expert"):
            worker = await pc.assemble("report")
            await pc.record(worker)
            await adapter.chat(worker.text, "report")
        assert (await receipt(execution_db, host))["request_attempts"] == 0
        await adapter.chat(host.text, "report")
    assert (await receipt(execution_db, host))["request_attempts"] == 1
    assert (await receipt(execution_db, worker))["request_attempts"] == 1


async def test_concurrent_requests_do_not_lose_counts(selected, execution_db, monkeypatch):
    ctx, personal = selected
    adapter, _ = transport(monkeypatch)
    with pc.bind(ctx):
        await pc.record(personal)
        await asyncio.gather(adapter.chat(personal.text, "one report"), adapter.chat(personal.text, "another report"))
    stored = await receipt(execution_db, personal)
    assert stored["request_attempts"] == stored["provider_responses"] == 2


async def test_response_callback_is_once_only_and_expired_scope_is_ignored(selected, execution_db):
    ctx, personal = selected
    ctx = replace(ctx, lease=pc.ContextLease())
    with pc.bind(ctx):
        await pc.record(personal)
        ack = await request_evidence.begin({"system": personal.text})
        await request_evidence.acknowledge(ack)
        await request_evidence.acknowledge(ack)
        ctx.lease.active = False
        assert await request_evidence.begin({"system": personal.text}) is None
    stored = await receipt(execution_db, personal)
    assert stored["request_attempts"] == stored["provider_responses"] == 1


async def test_evidence_failure_does_not_leak_details_or_block_request(selected, execution_db, monkeypatch, caplog):
    ctx, personal = selected
    adapter, _ = transport(monkeypatch)
    async def broken(*args, **kwargs):
        raise RuntimeError("Private request diagnostic")
    monkeypatch.setattr(pc, "_count_request", broken)
    with pc.bind(ctx):
        await pc.record(personal)
        assert (await adapter.chat(personal.text, "report")).content == "ok"
    assert "Private request diagnostic" not in caplog.text
    assert (await receipt(execution_db, personal))["request_attempts"] == 0


async def test_evidence_timeouts_are_bounded_but_user_cancellation_propagates(monkeypatch):
    monkeypatch.setattr(request_evidence, "_TIMEOUT_SECONDS", 0.01)
    async def slow(*args):
        await asyncio.sleep(10)
    with request_evidence.bind(slow):
        assert await request_evidence.begin({}) is None
    await request_evidence.acknowledge(slow)
    async def cancelled(*args):
        raise asyncio.CancelledError
    with request_evidence.bind(cancelled), pytest.raises(asyncio.CancelledError):
        await request_evidence.begin({})


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
async def test_real_host_task_binds_its_receipt_to_the_serialized_request(selected, execution_db, monkeypatch, provider):
    from server.orchestrator import arslan, memory, tool_loop
    from server.services import knowledge, task_context
    adapter, captured = transport(monkeypatch, provider)
    async with execution_db() as db:
        await db.execute(insert(ProviderConfig).values(label="Synthetic local transport", provider="ollama",
            model="fixture", base_url="http://127.0.0.1:11434/v1", api_key="", is_primary=True))
        await db.commit()
    async def empty(*args, **kwargs):
        return []
    async def no_roster(*args, **kwargs):
        return ""
    monkeypatch.setattr(knowledge, "retrieve_scoped", empty)
    monkeypatch.setattr(arslan, "_team_roster", no_roster)
    monkeypatch.setattr(arslan, "_arslan_tools", empty)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    @task_context.scoped_turn
    async def turn(conversation_id, user_message, emit):
        message = await memory.add_message(conversation_id, "user", user_message)
        task_context.source_message(message)
        return await arslan._handle_answer(conversation_id, user_message, emit)
    events = []
    await turn("host-conversation", "Prepare a report", events.append)
    assert captured and not any(event["type"] == "error" for event in events)
    async with execution_db() as db:
        records = (await db.scalars(select(ContextReceiptRecord).where(
            ContextReceiptRecord.conversation_id == "host-conversation"))).all()
    assert len(records) == 1
    stored = records[0]
    assert stored.task_id and stored.run_id.startswith("run:")
    assert stored.receipt["request_attempts"] == stored.receipt["provider_responses"] == len(captured)
    assert any("Reports should have concise conclusions." in part for part in pc._system_fragments(captured[0]))

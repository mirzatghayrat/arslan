"""Shared admission budget is checked before work, never reset by nested calls."""
import asyncio
import json

import httpx
import pytest
from sqlalchemy import select

from arslan import execution_budget as budget
from arslan.llm.providers.anthropic_provider import AnthropicProvider
from arslan.llm.providers.gemini_provider import GeminiProvider
from server.db.models import Run
from server.orchestrator import tool_loop
from server.registry import executors
from server.services import host_run


@pytest.mark.parametrize("provider_class", [AnthropicProvider, GeminiProvider])
async def test_request_count_and_output_limit_reach_transport(provider_class):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}],
                                       "candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    provider = provider_class("test", transport=httpx.MockTransport(handler))
    with budget.scope(budget.Budget(budget.Limits(model_requests=1, output_tokens_per_request=17))):
        await provider.chat([{"role": "user", "content": "hello"}])
        with pytest.raises(budget.BudgetExceeded, match="model_requests"):
            await provider.chat([{"role": "user", "content": "again"}])
    assert len(requests) == 1
    sent = requests[0]
    assert sent.get("max_tokens", sent.get("generationConfig", {}).get("maxOutputTokens")) == 17


async def test_nested_governed_calls_share_one_budget():
    @budget.governed
    async def child():
        budget.model_request(100)
        return budget.current().id

    with budget.scope(budget.Budget(budget.Limits(model_requests=1))) as shared:
        assert await child() == shared.id
        with pytest.raises(budget.BudgetExceeded):
            await child()
        assert shared.model_requests == 1


async def test_parallel_admission_is_atomic():
    async def attempt():
        await asyncio.sleep(0)
        try:
            budget.model_request(10)
            return True
        except budget.BudgetExceeded:
            return False

    with budget.scope(budget.Budget(budget.Limits(model_requests=3))) as shared:
        results = await asyncio.gather(*(attempt() for _ in range(10)))
        assert sum(results) == 3 and shared.model_requests == 3


async def test_many_tools_in_one_model_reply_cannot_bypass_shared_limit(monkeypatch):
    from arslan.models import LLMResponse
    calls = []

    class Adapter:
        async def chat(self, *args, **kwargs):
            return LLMResponse(content="", usage={}, tool_calls=[
                {"id": str(i), "function": {"name": "run_python", "arguments": {"code": str(i)}}}
                for i in range(3)])

    class Executor:
        async def execute(self, args):
            calls.append(args)
            return {"ok": True, "external": False}

    async def resolve():
        return [{"key": "run_python", "description": "Compute"}]

    monkeypatch.setattr(tool_loop, "_get_adapter", Adapter)
    monkeypatch.setitem(executors.EXECUTORS, "run_python", Executor())
    with budget.scope(budget.Budget(budget.Limits(tool_calls=2))):
        with pytest.raises(budget.BudgetExceeded, match="tool_calls"):
            await tool_loop.run_native(system="test", user_content="test", history=[],
                                       emit=lambda e: None, on_chunk=lambda c: None, resolve_tools=resolve)
    assert len(calls) == 2


def test_token_threshold_is_honestly_post_response():
    with budget.scope(budget.Budget(budget.Limits(tokens=10))) as shared:
        assert budget.model_request(8192) == 10
        budget.charge_tokens(15)  # Actual usage can exceed the admission estimate.
        with pytest.raises(budget.BudgetExceeded, match="tokens"):
            budget.model_request(8192)
        assert shared.snapshot()["monetary_limit"] is False
        assert shared.snapshot()["token_limit_mode"] == "post_response_admission"


async def test_wall_timeout_finalizes_host_and_preserves_budget(execution_db, monkeypatch):
    monkeypatch.setenv("ARSLAN_RUN_MAX_WALL_SECONDS", "0.1")

    async def body(emit):
        emit({"type": "stream_chunk", "content": "partial"})
        await asyncio.Event().wait()

    with pytest.raises(budget.BudgetExceeded, match="wall_seconds"):
        await host_run.execute("deadline", "test", lambda e: None, body)
    async with execution_db() as db:
        run = (await db.execute(select(Run))).scalar_one()
    assert run.status == "cancelled" and run.final_output == "partial"
    assert run.execution_budget["stop_reason"] == "wall_seconds"


async def test_detached_maintenance_does_not_inherit_user_budget():
    async def inspect():
        return budget.current()

    with budget.scope():
        task = asyncio.create_task(inspect(), context=budget.detached_context())
        assert await task is None


async def test_unrelated_timeout_is_not_mislabeled():
    @budget.governed
    async def fail():
        raise TimeoutError("database timeout")

    with pytest.raises(TimeoutError, match="database timeout"):
        await fail()

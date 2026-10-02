"""0.1.49 completion first for conversational turns: the configured limits are
the wrap-up point, the hard limit (1.5x) only stops runaways. Kernel bench T2:
twice a chat turn hit its hard budget and ended with an empty reply after 11+
successful page reads."""
import json

from arslan.execution_budget import Budget, Limits, configured_limits, scope, turn_budget
from arslan.models import LLMResponse
from server.orchestrator import tool_loop


def test_turn_budget_wraps_up_at_the_configured_limits():
    b = turn_budget()
    soft = configured_limits()
    assert b.soft == soft
    assert b.limits.tool_calls == 36 and b.limits.tokens == 192_000 and b.limits.model_requests == 48
    assert b.limits.output_tokens_per_request == soft.output_tokens_per_request
    assert b.limits.artifact_bytes == soft.artifact_bytes


def test_default_scope_is_a_turn_budget():
    with scope() as b:
        assert b.soft is not None


async def test_a_turn_past_its_soft_point_delivers_instead_of_aborting(monkeypatch):
    systems = []
    calls = iter(range(100))

    class Adapter:
        async def chat(self, system, user, history=None, tools=None, **kw):
            systems.append((user, tools))       # 0.1.50: step notes ride in the last message
            if tools and any(t["function"]["name"] == "fixture_read" for t in tools):
                i = next(calls)
                return LLMResponse(usage={}, content="", tool_calls=[
                    {"id": f"c{i}", "type": "function", "function": {"name": "fixture_read", "arguments": {"i": i}}}])
            return LLMResponse(usage={}, content="Here is what I found so far: A, B.")

    class Executor:
        async def execute(self, args):
            return {"ok": True, "external": False, "text": f"page {args['i']}"}
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: Adapter())
    monkeypatch.setitem(tool_loop.EXECUTORS, "fixture_read", Executor())

    async def tools():
        return [{"key": "fixture_read", "description": "read"}]
    soft = Limits(tool_calls=3)
    with scope(Budget(Limits(tool_calls=5), soft=soft)) as budget:
        result = await tool_loop.run_native(system="S", user_content="research", history=[],
                                            resolve_tools=tools, emit=lambda e: None, on_chunk=lambda c: None)
    assert result["final"] == "Here is what I found so far: A, B."
    assert budget.tool_calls == 3                      # stopped researching at the soft point
    wrap = [s for s, t in systems if "Work budget nearly used" in s]
    assert wrap and wrap[0] and json.dumps(systems[-1][1] or []).count("fixture_read") == 0


async def test_a_real_chat_turn_runs_on_a_turn_budget(execution_db):
    """run_turn (the entry for persisted chat turns) must create the soft/hard
    budget, not a hard-only one."""
    from arslan.execution_budget import current
    from server.services import personal_context as pc, task_service
    seen = {}
    with pc.bind(pc.TaskMemoryContext(task_id="turn-budget-task", run_id="initial", conversation_id="tb",
                                      project_id=None, no_learning=True)):
        async def function(cid, request, emit):
            b = current()
            seen.update(soft=b.soft, hard=b.limits)
            return "done"
        await task_service.run_turn(function, "tb", "anything", lambda event: None)
    assert seen["soft"] == configured_limits()
    assert seen["hard"].tool_calls > seen["soft"].tool_calls

"""K4a (docs/plans/0162/K4-one-stop-policy.md): one stop policy for chat turns and background jobs.

- One set of limits: the tier in Settings (standard by default) for a chat turn and a job alike; the
  tier is the wrap-up point, 1.5× stops a run that cannot stop itself.
- Near its token limit a run still gets room to answer (the M1 T2 case: the budget clamped the output
  to a few hundred tokens, a thinking model spent them on reasoning, and the answer came back empty).
- How large the current context is never stops a run (it only decides compaction, K2).
"""
import httpx

from arslan import execution_budget as eb
from arslan.llm import usage_sink
from arslan.llm.usage_weight import charged_tokens
from tests.llm.test_k1b_anthropic_context import END

STANDARD = eb.Limits(model_requests=120, tool_calls=80, tokens=600_000, wall_seconds=1800)


def test_chat_turns_and_background_jobs_get_one_set_of_limits():
    budget = eb.run_budget()
    assert budget.soft == eb.tier_limits("standard") == eb.Limits() == STANDARD
    assert (budget.limits.model_requests, budget.limits.tool_calls, budget.limits.tokens,
            budget.limits.wall_seconds) == (180, 120, 900_000, 2700)
    with eb.scope() as scoped:
        assert scoped.soft == STANDARD and scoped.limits == budget.limits
    for gone in ("turn_budget", "job_budget", "job_limits", "configured_limits", "JOB_TIERS"):
        assert not hasattr(eb, gone), gone                  # one policy, no chat-only path left


def test_a_task_made_through_the_api_gets_the_same_default_limits():
    """Q10: BudgetSpec (a task created through the API) mirrors the one set of limits."""
    from arslan.companion.contracts import BudgetSpec
    assert BudgetSpec().to_native() == eb.Limits() == STANDARD


def test_every_tier_is_a_wrap_up_point_with_a_hard_stop_half_again_above_it():
    for tier, soft in eb.TIERS.items():
        budget = eb.run_budget(tier)
        assert budget.soft == eb.Limits(**soft)
        assert budget.limits.model_requests == -(-soft["model_requests"] * 3 // 2)
    assert eb.run_budget("no-such-tier").soft == STANDARD


def test_environment_overrides_apply_to_every_tier(monkeypatch):
    monkeypatch.setenv("ARSLAN_RUN_MAX_WALL_SECONDS", "5")
    assert eb.tier_limits("ample").wall_seconds == 5 and eb.run_budget("lean").soft.wall_seconds == 5


async def test_an_entry_point_takes_its_budget_from_the_registered_settings():
    """A chat turn starts in a `governed` entry point, before anything has read the settings: the
    server registers how a run's budget is made (the tier the user picked), and `governed` uses it."""
    seen = []

    @eb.governed
    async def entry():
        seen.append(eb.current().soft)

    async def ample():
        return eb.run_budget("ample")
    eb.use_budget_factory(ample)
    try:
        await entry()
    finally:
        eb.use_budget_factory(None)
    await entry()
    assert seen == [eb.tier_limits("ample"), STANDARD]


async def test_the_settings_tier_makes_the_budget(execution_db):
    from server.db import session as db_session
    from server.services import settings_service
    assert (await settings_service.run_budget_from_settings()).soft == STANDARD
    async with db_session.AsyncSessionLocal() as db:
        await settings_service.update_settings(db, {"background_job_budget": "ample"})
    assert (await settings_service.run_budget_from_settings()).soft == eb.tier_limits("ample")


def test_how_large_the_context_is_never_stops_a_run():
    """A 950k-token context that is 940k cached is charged about 104k; the run goes on."""
    budget = eb.run_budget()
    with eb.scope(budget):
        usage_sink.report(950_500, charged=charged_tokens(
            {"input_tokens": 10_000, "cache_read_input_tokens": 940_000, "output_tokens": 500}))
        assert budget.tokens == 104_500 and not budget.soft_reached()
        assert budget.model_request(32_000) == 32_000


def test_near_its_token_limit_a_run_still_gets_room_to_answer():
    budget = eb.run_budget()
    budget.tokens = budget.limits.tokens - 300
    assert budget.model_request(64_000) == eb.MIN_OUTPUT_TOKENS == 16_384
    assert budget.model_request(4_000) == 4_000              # never more than was asked for


async def test_t2_a_turn_near_its_token_limit_answers_instead_of_coming_back_empty(monkeypatch):
    """M1's T2: late in a long research turn the budget left a few hundred output tokens, a thinking model
    spent them on reasoning, and the answer came back empty. A request now gets what it asked for up to
    MIN_OUTPUT_TOKENS, and the model's answer comes through. Real Anthropic payloads, no network."""
    import json

    from arslan.llm.adapter import LLMAdapter
    from arslan.llm.providers.anthropic_provider import AnthropicProvider
    from server.orchestrator import tool_loop
    sent = []

    def handler(request):
        payload = json.loads(request.content)
        sent.append(payload)
        if payload["max_tokens"] < 8_192:                      # a tight limit goes on reasoning alone
            return httpx.Response(200, json={
                "role": "assistant", "stop_reason": "max_tokens", "usage": {"input_tokens": 20, "output_tokens": 300},
                "content": [{"type": "thinking", "thinking": "", "signature": "s0"}]})
        return httpx.Response(200, json=END)
    adapter = LLMAdapter("anthropic", "claude-opus-5-5")
    adapter._provider = AnthropicProvider("claude-opus-5-5", api_key="k", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    async def no_tools():
        return []
    budget = eb.run_budget()
    budget.tokens = budget.limits.tokens - 300
    with eb.scope(budget):
        result = await tool_loop.run_native(system="S", user_content="Write the report", history=[],
                                            emit=lambda e: None, on_chunk=lambda c: None, resolve_tools=no_tools)
    assert sent[0]["max_tokens"] >= 8_192                       # what the request asked for, not the 300 left
    assert result["final"] == "Done."


async def test_a_persisted_turn_runs_on_the_tier_in_settings(execution_db):
    """run_turn makes a turn's budget from the work budget setting when nothing above it did."""
    from server.db import session as db_session
    from server.services import personal_context as pc, settings_service, task_service
    async with db_session.AsyncSessionLocal() as db:
        await settings_service.update_settings(db, {"background_job_budget": "lean"})
    seen = {}
    with pc.bind(pc.TaskMemoryContext(task_id="k4a-tier-task", run_id="initial", conversation_id="k4a",
                                      project_id=None, no_learning=True)):
        async def function(cid, request, emit):
            seen["soft"] = eb.current().soft
            return "done"
        await task_service.run_turn(function, "k4a", "anything", lambda event: None)
    assert seen["soft"] == eb.tier_limits("lean")


def test_the_app_registers_the_settings_budget_at_startup():
    """The suite doesn't run the whole lifespan (see test_curation_loop's wiring test), so the wiring is
    pinned at the source; the factory itself and governed's use of it are tested above."""
    from pathlib import Path

    import server.main as main
    src = Path(main.__file__).read_text(encoding="utf-8")
    assert "execution_budget.use_budget_factory(_settings_for_budget.run_budget_from_settings)" in src

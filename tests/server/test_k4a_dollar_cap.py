"""K4a: a per-task dollar cap, on by default ($2; Settings → Advanced, up to $100).

A run wraps up at cap / 1.5 and stops at the cap, saying it was the dollar limit. Only responses with a known
price count (prices.usd_for_usage); an unpriced one is counted as such and the token cap still holds.
"""
import json

import httpx
import pytest

from arslan import execution_budget as eb
from arslan.llm import prices, usage_sink


def test_the_dollar_cap_is_on_by_default():
    assert eb.DEFAULT_USD_CAP == 2.0
    assert eb.run_budget().usd_cap == 2.0 and eb.run_budget(usd_cap=5.0).usd_cap == 5.0


def test_a_run_wraps_up_at_two_thirds_of_the_cap_and_stops_at_the_cap():
    budget = eb.Budget(eb.Limits(), soft=eb.Limits(), usd_cap=0.30)
    budget.charge_usd(0.19)
    assert not budget.soft_reached()
    budget.charge_usd(0.02)                                             # 0.21 ≥ 0.30 / 1.5
    assert budget.soft_reached()
    assert budget.model_request(1000) == 1000                           # wrap-up, not stopped yet
    budget.charge_usd(0.09)
    with pytest.raises(eb.BudgetExceeded, match="usd"):
        budget.model_request(1000)
    assert budget.stop_reason == "usd"


def test_an_unpriced_response_is_counted_and_the_token_cap_still_holds():
    budget = eb.Budget(eb.Limits(tokens=100), usd_cap=0.10)
    budget.charge_usd(None)
    assert (budget.usd, budget.unpriced_requests) == (0.0, 1)
    budget.tokens = 100
    with pytest.raises(eb.BudgetExceeded, match="tokens"):
        budget.model_request(10)


def test_the_snapshot_carries_the_spend_and_an_old_one_gets_todays_cap():
    budget = eb.run_budget(usd_cap=3.0)
    budget.charge_usd(0.5)
    budget.charge_usd(None)
    snap = budget.snapshot()
    assert snap["monetary_limit"] is True
    assert snap["spend"] == {"usd": 0.5, "usd_cap": 3.0, "unpriced_requests": 1}
    restored = eb.Budget.from_snapshot(snap)
    assert (restored.usd, restored.usd_cap, restored.unpriced_requests) == (0.5, 3.0, 1)
    old = {k: v for k, v in snap.items() if k != "spend"}                # before K4a: no spend recorded
    old["monetary_limit"] = False
    again = eb.Budget.from_snapshot(old, usd_cap=4.0)
    assert (again.usd, again.usd_cap) == (0.0, 4.0)                      # Q13: today's cap, spend 0
    assert eb.Budget.from_snapshot(old).usd_cap == eb.DEFAULT_USD_CAP


def test_a_dollar_stop_survives_a_snapshot():
    budget = eb.run_budget(usd_cap=0.01)
    budget.charge_usd(0.02)
    with pytest.raises(eb.BudgetExceeded):
        budget.model_request(10)
    assert eb.Budget.from_snapshot(budget.snapshot()).stop_reason == "usd"


def test_usage_reports_charge_the_runs_dollars():
    budget = eb.run_budget()
    with eb.scope(budget):
        usage_sink.report(100, charged=100, usd=0.25)
        usage_sink.report(100, charged=100, usd=None)                   # a real response with no price
        usage_sink.report(100)                                          # a report that says nothing of price
    assert (budget.usd, budget.unpriced_requests) == (0.25, 1)


async def test_a_claude_response_charges_its_price_by_cache_tier(monkeypatch):
    from arslan.llm.adapter import LLMAdapter
    from arslan.llm.providers.anthropic_provider import AnthropicProvider
    monkeypatch.setattr(prices, "PRICES", {"claude-x": (4.0, 20.0)})
    monkeypatch.setattr(prices, "CACHE_PRICES", {"claude-x": (0.4, 5.0, 8.0)})
    reply = {"role": "assistant", "stop_reason": "end_turn", "content": [{"type": "text", "text": "Done."}],
             "usage": {"input_tokens": 100_000, "cache_read_input_tokens": 200_000,
                       "cache_creation_input_tokens": 0, "output_tokens": 10_000}}

    def handler(request):
        json.loads(request.content)
        return httpx.Response(200, json=reply)
    adapter = LLMAdapter("anthropic", "claude-x")
    adapter._provider = AnthropicProvider("claude-x", api_key="k", transport=httpx.MockTransport(handler))
    budget = eb.run_budget()
    with eb.scope(budget):
        await adapter.chat("S", "hi")
    assert budget.usd == pytest.approx(0.4 + 0.08 + 0.2)


async def test_the_work_budget_settings_carry_the_cap(execution_db):
    from server.db import session as db_session
    from server.services import settings_service
    assert (await settings_service.run_budget_from_settings()).usd_cap == 2.0
    for stored, cap in (("5", 5.0), ("0", 2.0), ("-1", 2.0), ("abc", 2.0), ("500", 100.0)):
        async with db_session.AsyncSessionLocal() as db:
            await settings_service.update_settings(db, {"task_usd_cap": stored})
        assert (await settings_service.run_budget_from_settings()).usd_cap == cap, stored


async def test_a_chat_turns_closing_names_the_dollar_limit(monkeypatch):
    from server.orchestrator import tool_loop
    from server.services import runtime_messages

    async def english():
        return "en"
    monkeypatch.setattr(runtime_messages, "selected_locale", english)
    budget = eb.run_budget(usd_cap=0.01)
    budget.stop_reason = "usd"
    with eb.scope(budget):
        text = await tool_loop._budget_closing([], None, 0.0)
    assert runtime_messages.render("limit_usd", "en") in text and "dollar" in text


def test_every_language_names_the_dollar_limit():
    from server.services import runtime_messages
    for locale in ("en", "zh", "ja", "es", "de", "fr"):
        for key in ("limit_usd", "budget_usd", "job_out_of_budget_usd"):
            assert runtime_messages.render(key, locale, goal="g", used="$0.11", limit="$0.10", steps=3) != key


def test_a_jobs_dollar_stop_shows_dollars():
    from server.services import background_jobs
    stop = background_jobs.budget_stop_of({"stop_reason": "usd", "spend": {"usd": 0.1149, "usd_cap": 0.1}},
                                          pause_reason="task_budget_exhausted", tier="standard")
    assert stop == {"reason": "usd", "used": "$0.11", "limit": "$0.10", "tier": "standard"}


async def test_a_task_that_spent_its_cap_is_not_started_again(execution_db):
    from server.services.task_repository import TaskError, repository
    from tests.server.test_task_repository import spec
    budget = eb.run_budget(usd_cap=0.5)
    budget.charge_usd(0.6)
    async with repository() as repo:
        created = await repo.create(spec(), "conversation", budget_snapshot=budget.snapshot())
        with pytest.raises(TaskError, match="task_budget_exhausted"):
            await repo.start("task-one", created["version"])


async def test_a_job_stopped_by_the_dollar_cap_says_so_in_dollars(monkeypatch):
    from server.services import background_jobs, runtime_messages

    async def english():
        return "en"
    monkeypatch.setattr(runtime_messages, "selected_locale", english)
    job = background_jobs.Job(job_id="j", conversation_id="c", goal="collect prices", acceptance=[])
    job.budget_stop = {"reason": "usd", "used": "$0.11", "limit": "$0.10", "tier": "standard"}
    note = await background_jobs._budget_note(job)
    assert "$0.11" in note and "$0.10" in note
    # Q14: the dollar variant points to the dollar limit, not to the work budget it doesn't depend on
    assert "per-task dollar limit" in note and "background work budget" not in note

"""The history budget follows the model's context window (K2).

The window comes from a static table of model families, never from the model catalog cache: the
chat path does not read ModelCatalogCache (its docstring's rule; ⓪Plan, 2026-10-20).
"""
import pytest

from server.orchestrator import context_window as cw


@pytest.mark.parametrize("model,window", [
    ("deepseek-chat", 128_000), ("deepseek-reasoner", 128_000),
    ("claude-opus-5-5", 200_000), ("claude-sonnet-5-5", 200_000),
    ("gpt-4o-mini", 128_000), ("gpt-4.1", 1_047_576), ("gemini-2.5-pro", 1_048_576),
])
def test_a_known_family_gets_its_window_from_the_table(model, window):
    assert cw.window_for(model) == (window, "table")


def test_an_unknown_model_gets_the_conservative_default():
    assert cw.window_for("some-new-model-7b") == (cw.DEFAULT_WINDOW, "default")
    assert cw.window_for(None) == (cw.DEFAULT_WINDOW, "default")


def test_matching_ignores_case_and_provider_prefixes():
    assert cw.window_for("deepseek/DeepSeek-Chat") == (128_000, "table")


def test_a_small_local_model_gets_a_small_budget_but_never_less_than_today():
    window, source = cw.window_for("llama3.1:8b")
    assert source == "table" and window <= 8192
    assert cw.FLOOR <= cw.history_budget(window) < cw.history_budget(cw.DEFAULT_WINDOW)
    assert cw.history_budget(2048) == cw.FLOOR


def test_a_big_window_is_capped():
    assert cw.history_budget(1_048_576) == cw.CAP


def test_a_middle_window_gets_its_fraction():
    assert cw.history_budget(32_000) == int(32_000 * cw.FRACTION)
    assert cw.FLOOR < cw.history_budget(32_000) < cw.CAP


def test_the_default_window_is_small_and_the_cap_bounds_cost():
    assert cw.DEFAULT_WINDOW <= 32_000
    assert cw.history_budget(cw.DEFAULT_WINDOW) < cw.history_budget(128_000) <= cw.CAP


class _Adapter:
    def __init__(self, model):
        self.model = model


async def test_the_turn_budget_follows_the_turns_model(execution_db, monkeypatch):
    from server.orchestrator import memory, tool_loop
    monkeypatch.delenv("ARSLAN_WORKING_TOKEN_BUDGET", raising=False)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _Adapter("claude-sonnet-5-5"))
    big = await memory.turn_budget("c")
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _Adapter("some-unknown-model"))
    small = await memory.turn_budget("c")
    assert big == cw.history_budget(200_000) > small == cw.history_budget(cw.DEFAULT_WINDOW)


async def test_the_run_records_where_the_window_came_from(execution_db, monkeypatch):
    from arslan.execution_budget import Budget, scope
    from server.orchestrator import memory, tool_loop
    monkeypatch.delenv("ARSLAN_WORKING_TOKEN_BUDGET", raising=False)
    for model, source, window in (("deepseek-chat", "table", 128_000), ("mystery", "default", cw.DEFAULT_WINDOW)):
        monkeypatch.setattr(tool_loop, "_get_adapter", lambda model=model: _Adapter(model))
        budget = Budget()
        with scope(budget):
            await memory.turn_budget("c")
        assert budget.snapshot()["history"] == {"window": window, "source": source,
                                                "budget": cw.history_budget(window)}


async def test_the_fixed_budget_fallback_wins(execution_db, monkeypatch):
    # Kept for v0.1.63 as the way back to the old fixed budget; deleted in v0.1.64 (card).
    from arslan.execution_budget import Budget, scope
    from server.orchestrator import memory, tool_loop
    monkeypatch.setenv("ARSLAN_WORKING_TOKEN_BUDGET", "1234")
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _Adapter("claude-sonnet-5-5"))
    budget = Budget()
    with scope(budget):
        assert await memory.turn_budget("c") == 1234
    assert budget.snapshot()["history"]["source"] == "fixed"


async def test_a_model_that_cannot_be_resolved_gets_todays_budget(execution_db, monkeypatch):
    from server.orchestrator import memory, tool_loop
    monkeypatch.delenv("ARSLAN_WORKING_TOKEN_BUDGET", raising=False)

    def broken():
        raise RuntimeError("no provider configured")
    monkeypatch.setattr(tool_loop, "_get_adapter", broken)
    assert await memory.turn_budget("c") == cw.FLOOR


async def test_history_admission_uses_the_turns_budget(execution_db):
    from arslan.context_budget import estimate_tokens
    from server.orchestrator import memory
    for i in range(10):
        await memory.add_message("w", "user", f"{i} " + "word " * 400)
    small = await memory.assemble_working_context("w", budget=1200)
    large = await memory.assemble_working_context("w", budget=4000)
    assert len(large["history"]) > len(small["history"])
    assert sum(estimate_tokens(m["content"]) for m in small["history"]) <= 1200
    assert large["history"][-1]["content"].startswith("9")


class _Reply:
    content, tool_calls = "ok", []


class _Recording:
    def __init__(self, model):
        self.model, self.histories = model, []

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        self.histories.append(list(history or []))
        return _Reply()


async def test_a_real_turn_carries_history_by_its_models_window(execution_db, monkeypatch):
    from server.orchestrator import arslan, memory, tool_loop
    from server.services import turn_facts
    monkeypatch.delenv("ARSLAN_WORKING_TOKEN_BUDGET", raising=False)

    async def no_facts(conversation_id, message):
        return []
    monkeypatch.setattr(turn_facts, "extract", no_facts)
    carried = {}
    for model in ("claude-sonnet-5-5", "some-unknown-model"):
        cid = f"window-{model}"
        for i in range(30):
            await memory.add_message(cid, "user" if i % 2 == 0 else "arslan", f"{i} " + "word " * 400)
        adapter = _Recording(model)
        monkeypatch.setattr(tool_loop, "_get_adapter", lambda adapter=adapter: adapter)
        await arslan.handle_user_message(cid, "and next?", lambda event: None)
        carried[model] = len(adapter.histories[0])
    assert carried["claude-sonnet-5-5"] > carried["some-unknown-model"] > 0

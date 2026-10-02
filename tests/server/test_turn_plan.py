"""update_plan (0.1.50 P2 S2): the run's checklist, kept by the host."""
import json

from arslan.execution_budget import scope
from server.orchestrator import tool_loop
from server.orchestrator.turn_plan import MAX_ITEMS, MAX_TEXT, Plan
from tests.server import test_trajectory_golden as golden

ITEMS = [{"text": "find sources", "status": "done"},
         {"text": "collect jobs 6/10", "status": "in_progress"},
         {"text": "save table", "status": "pending"}]


def test_update_replaces_the_plan_and_renders_one_line():
    plan = Plan()
    out = plan.update({"items": ITEMS})
    assert out == {"ok": True, "external": False, "summary": "1/3 done"}
    assert plan.render() == "[x] find sources  [>] collect jobs 6/10  [ ] save table"
    plan.update({"items": [{"text": "save table", "status": "done"}]})
    assert plan.render() == "[x] save table"                 # replaced, not merged


def test_no_plan_renders_nothing():
    assert Plan().render() == ""


def test_text_is_one_line_and_bounded():
    plan = Plan()
    plan.update({"items": [{"text": "a\n  b\tc " + "x" * 400, "status": "pending"}]})
    assert plan.items[0]["text"].startswith("a b c x") and len(plan.items[0]["text"]) == MAX_TEXT


def test_a_bad_update_is_refused_and_keeps_the_old_plan():
    plan = Plan()
    plan.update({"items": ITEMS})
    before = plan.render()
    for bad in ({}, {"items": []}, {"items": "x"},
                {"items": [{"text": "", "status": "done"}]},
                {"items": [{"text": "a", "status": "finished"}]},
                {"items": ["a"]},
                {"items": [{"text": "a", "status": "pending"}] * (MAX_ITEMS + 1)}):
        out = plan.update(bad)
        assert out["ok"] is False and out["code"] == "invalid_arguments", bad
        assert "Plan not changed" in out["error"]
    assert plan.render() == before


PLAN_TOOL = {"key": "update_plan", "description": "plan"}


async def _run(monkeypatch, replies, *, wired_plan=True):
    adapter = golden._Recorder(replies)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    from server.registry import executors
    monkeypatch.setitem(executors.EXECUTORS, "web_search", golden._Search())
    assert "update_plan" not in executors.EXECUTORS           # host bookkeeping, no executor

    async def resolve():
        return [*(await golden._resolve()), *([PLAN_TOOL] if wired_plan else [])]
    with scope() as budget:
        result = await tool_loop.run_native(system="S", user_content="find 10 jobs", history=[],
                                            emit=lambda e: None, on_chunk=lambda c: None,
                                            resolve_tools=resolve)
    return result, adapter, budget


async def test_the_loop_keeps_the_plan_without_an_executor_or_tool_budget(monkeypatch):
    result, adapter, budget = await _run(monkeypatch, [
        golden._Resp(None, [golden._tc("update_plan", {"items": ITEMS}, "c1"),
                            golden._tc("web_search", {"query": "jobs"}, "c2")]),
        golden._Resp("Here are the jobs.")])
    assert result["final"] == "Here are the jobs."
    plan_rec = next(r for r in result["tool_trace"] if r["tool"] == "update_plan")
    assert plan_rec["result"]["ok"] is True and plan_rec["result"]["summary"] == "1/3 done"
    assert budget.tool_calls == 1                               # only web_search counted
    assert "1/3 done" in json.dumps(adapter.calls[1], ensure_ascii=False)


async def test_an_unwired_plan_tool_is_not_handled_by_the_host(monkeypatch):
    """Spawns/workers never get update_plan: a call from them is the ordinary
    'not available' error, never a silent success."""
    result, _, _ = await _run(monkeypatch, [
        golden._Resp(None, [golden._tc("update_plan", {"items": ITEMS}, "c1")]),
        golden._Resp("ok")], wired_plan=False)
    rec = next(r for r in result["tool_trace"] if r["tool"] == "update_plan")
    assert rec["result"]["ok"] is False


async def test_host_turns_and_background_jobs_get_the_tool_but_workers_do_not(monkeypatch, tmp_path):
    from tests.server.test_workspace_tool_gate import _wire
    engine = await _wire(tmp_path, monkeypatch, workspace=None)
    from server.orchestrator import arslan
    from server.services import task_service, task_workers
    assert "update_plan" not in task_workers.READ_TOOLS       # workers' fixed subset
    keys = {t["key"] for t in await arslan._arslan_tools()}
    assert "update_plan" in keys
    assert "update_plan" in {t["key"] for t in await arslan._background_tools()}
    assert await task_service.effect_of("update_plan", {}) == "read"
    await engine.dispose()

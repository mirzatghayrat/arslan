"""SUB5e (v0.1.64, card docs/plans/0164/SUB-sub-sessions.md, "how" point 3): `start_sub_session` in the tool tables.

Through a real turn's tables (`arslan._arslan_tools` shown, `arslan._callable_tools` callable), the tool loop and a
scripted model, with the real EXECUTORS entry (no test puts the executor in):

- A chat turn is not shown it but finds it on demand (find_tools) and starts a sub-session with use_tool.
- The sub-session's own job is offered `sub_sessions.TOOLS` only, and can't start one either way. Two guards hold
  that: the tool's offer leaves out every job (test_tool_offer_table pins it) and TOOLS leaves it out; this test fails
  only with both gone.
- A typed turn in a sub-session reaches it; one in a sub-session's sub-session (the bottom layer) doesn't.
- The tree's spending limit stops a sub-session started this way.
"""
import pytest
from sqlalchemy import select

from server.db.companion_models import ConversationContext
from server.orchestrator import arslan as arslan_mod, on_demand, tool_loop
from server.orchestrator.tool_caller import ToolCaller
from server.registry import executors, hands_tools
from server.registry.task_tools import StartSubSessionExecutor
from server.services import (agent_browser, approvals, background_jobs, permissions, personal_context as pc,
                             run_registry, settings_service, sub_sessions, task_service)
from tests.server.test_s64_0_outside_content_gaps import (  # noqa: F401  (the fixture)
    _Page, memory)
from tests.server.test_sub3_runner import (BRIEF, ROOT, _Asker, _Cards, _ctx, _Model, _spent_task, _steps, _sub,
                                           _wait)

# The real tables, taken before the `memory` fixture puts a helper's table in `_arslan_tools`.
SHOWN, CALLABLE = arslan_mod._arslan_tools, arslan_mod._callable_tools
FIND = ("find_tools", {"query": "sub session"})
USE = ("use_tool", {"name": "start_sub_session", "arguments": {"brief": BRIEF}})


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(sub_sessions, "ended", lambda job, text: None)   # SUB4's summary turn: test_sub4_report
    assert not run_registry._sinks.get(ROOT), f"an earlier test left a window sink on {ROOT}"
    for reset in (background_jobs._reset_for_tests, approvals._reset_for_tests, sub_sessions._reset_for_tests,
                  on_demand._used.clear):
        reset()
    yield
    for reset in (background_jobs._reset_for_tests, approvals._reset_for_tests, sub_sessions._reset_for_tests,
                  on_demand._used.clear):
        reset()


@pytest.fixture
def real(memory, monkeypatch):  # noqa: F811
    """The sub-session's job runs for real; only the done-judge (another model) is left out. EXECUTORS is the real
    one for start_sub_session."""
    async def reached(job, text):
        return False
    monkeypatch.setattr(background_jobs, "_goal_not_reached", reached)
    monkeypatch.setattr(agent_browser, "available", lambda: True)
    monkeypatch.setattr(hands_tools, "desktop_available", lambda: False)
    monkeypatch.setitem(executors.EXECUTORS, "web_extract", _Page())
    assert isinstance(executors.EXECUTORS["start_sub_session"], StartSubSessionExecutor)
    return memory


def _names(tools) -> set[str]:
    return {t.get("function", {}).get("name") for t in tools or []}


class _Seeing(_Model):
    """SUB3's scripted model, also keeping the tool names each request was shown."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.shown = {"host": [], "child": []}

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        side = "child" if "BACKGROUND" in str(system) else "host" if "SUB3-HOST" in str(system) else None
        if side:
            self.shown[side].append(_names(tools))
        return await super().chat(system, user, history=history, tools=tools, temperature=temperature)


async def _turn(monkeypatch, model, cid=ROOT):
    """One chat turn of `cid` through the real tables; returns its tool trace."""
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)

    async def function(conversation_id, message, emit):
        return await tool_loop.run_native(
            system="SUB3-HOST", user_content=message, history=[], emit=lambda e: None, on_chunk=lambda c: None,
            resolve_tools=SHOWN, resolve_callable=CALLABLE, confirm_command=_Cards(), conversation_id=conversation_id,
            caller=ToolCaller(actor="host", spawn_id=None, conversation_id=conversation_id))
    with pc.bind(_ctx(cid)), permissions.asking_with(_Asker()):
        return (await task_service.run_turn(function, cid, "split the work", lambda e: None))["tool_trace"]


def _result(trace, tool):
    return [t["result"] for t in trace if t["tool"] == tool]


async def _finished(child):
    [job] = [j for j in background_jobs._jobs.values() if j.conversation_id == child]
    await _wait(lambda: job.task.done())
    return job


async def _children(db, cid):
    return await sub_sessions.children(db, cid)


async def test_a_chat_turn_finds_it_on_demand_and_starts_a_sub_session_offered_its_tools_only(real, monkeypatch):
    model = _Seeing(host=_steps(FIND, USE))
    trace = await _turn(monkeypatch, model)
    first = model.shown["host"][0]
    assert "start_sub_session" not in first and {"find_tools", "use_tool"} <= first      # on demand (K7)
    [found] = _result(trace, "find_tools")
    assert "start_sub_session" in [t["name"] for t in found["tools"]]
    [started] = _result(trace, "start_sub_session")
    assert (started["ok"], started["status"]) == (True, "queued"), started
    child = started["sub_session_id"]
    job = await _finished(child)
    assert (job.parent_id, job.outcome) == (ROOT, "done")
    async with real() as db:
        row = await db.get(ConversationContext, child)
        assert (row.kind, row.parent_id) == ("sub", ROOT)
    # The sub-session is offered its own tools, never this one, find_tools or use_tool.
    assert model.shown["child"] and all(shown <= sub_sessions.TOOLS for shown in model.shown["child"])


async def test_a_sub_sessions_own_job_cannot_start_one_directly_or_through_use_tool(real, monkeypatch):
    deeper = {"brief": "Go one layer further down"}
    model = _Seeing(host=_steps(USE), child=_steps(("start_sub_session", deeper),
                                                   ("use_tool", {"name": "start_sub_session", "arguments": deeper})))
    trace = await _turn(monkeypatch, model)
    child = _result(trace, "start_sub_session")[0]["sub_session_id"]
    await _finished(child)
    assert len(model.shown["child"]) == 3                       # both calls answered, then its answer
    async with real() as db:
        assert await _children(db, child) == []
        assert len(await _children(db, ROOT)) == 1
    assert [j.conversation_id for j in background_jobs._jobs.values()] == [child]


async def test_a_typed_turn_in_a_sub_session_reaches_it_and_one_on_the_bottom_layer_does_not(real, monkeypatch):
    async with real() as db:
        await _sub(db, ROOT, "sub-a")
        await _sub(db, "sub-a", "sub-b")
    bottom = _Seeing(host=_steps(FIND, USE))
    trace = await _turn(monkeypatch, bottom, "sub-b")
    [found] = _result(trace, "find_tools")
    assert "start_sub_session" not in [t["name"] for t in found["tools"]]
    [refused] = _result(trace, "use_tool")
    assert refused["code"] == "tool_unavailable", refused   # not offered: no card, never reaches the executor
    middle = _Seeing(host=_steps(USE))
    trace = await _turn(monkeypatch, middle, "sub-a")
    [started] = _result(trace, "start_sub_session")
    assert started["ok"] is True, started
    await _finished(started["sub_session_id"])
    async with real() as db:
        assert await _children(db, "sub-b") == []
        assert await _children(db, "sub-a") == ["sub-b", started["sub_session_id"]]
        layers = (await db.scalars(select(ConversationContext.id).where(ConversationContext.kind == "sub"))).all()
    assert set(layers) == {"sub-a", "sub-b", started["sub_session_id"]}


async def test_a_sub_session_started_through_the_tables_stops_at_its_trees_limit(real, monkeypatch):
    """As test_sub3's, reached through use_tool: a sibling spent $5.50 of the tree's $6; this child pays $0.30 a
    request, far from its own $2, and is stopped by the tree's limit."""
    async def cap(db):
        return 2.0
    monkeypatch.setattr(settings_service, "task_usd_cap", cap)
    async with real() as db:
        await _sub(db, ROOT, "c-sibling")
        await _spent_task(db, "c-sibling", 5.5)
    plan = {"items": [{"text": "outline", "status": "in_progress"}]}
    model = _Seeing(host=_steps(USE), child=_steps(*[("update_plan", plan)] * 3), price=0.3)
    trace = await _turn(monkeypatch, model)
    job = await _finished(_result(trace, "start_sub_session")[0]["sub_session_id"])
    assert (job.outcome, job.budget_stop["scope"], job.budget_stop["limit"]) == ("out_of_budget", "tree", "$6.00")

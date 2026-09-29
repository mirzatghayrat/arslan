"""0.1.44: a failed READ never stops a turn, and an unknown outcome stops only
its own repetition — never the rest of the work.

Field case (owner, 2026-09-29): Playwright MCP's browser_take_screenshot failed,
was journaled as an external write of unknown outcome, and the next model step
ended the turn with "An action may already have happened"."""
import pytest
from sqlalchemy import select

from server.db.models import CompanionTask, MCPServer, TaskAction
from server.services import host_run, task_service
from tests.server.test_task_service import run


@pytest.fixture
async def playwright(execution_db):
    async with execution_db() as db:
        db.add(MCPServer(id=4, label="Playwright", transport="stdio", command="npx", args=["@playwright/mcp@latest"]))
        db.add(MCPServer(id=5, label="Unknown", transport="stdio", command="npx", args=["some-unknown-server"]))
        await db.commit()


async def test_effects_follow_what_the_tool_really_is(playwright):
    effect = task_service.effect_of
    assert await effect("mcp_4__browser_take_screenshot", {}) == "read"
    assert await effect("mcp_4__browser_click", {}) == "external_write"
    assert await effect("mcp_5__frobnicate", {}) == "external_write"          # unknown stays cautious
    assert await effect("mcp_5__list_items", {}) == "read"                    # verb heuristic
    assert await effect("run_command", {"command": "ls", "argv": ["-la"]}) == "read"
    assert await effect("run_command", {"command": "git", "argv": ["push"]}) == "external_write"
    assert await effect("background_status", {}) == "read"
    assert await effect("write_file", {}) == "local_write"
    assert await effect("some_new_tool", {}) == "external_write"


async def _turn(calls):
    """One turn that makes each (tool, args, ok) call in order, then answers."""
    async def function(conversation, message, emit):
        async def body(sink):
            runtime = task_service.current()
            for tool, args, ok in calls:
                async def execute(admitted, ok=ok):
                    return {"ok": ok, "error": None if ok else "synthetic failure"}
                try:
                    await runtime.execute_tool(tool, args, execute)
                except Exception as exc:  # noqa: BLE001
                    return f"stopped by {type(exc).__name__}: {getattr(exc, 'code', '')}"
            # the model's next step: must still be allowed after the failures above
            await runtime.checkpoint("before_model")
            return "Answer delivered"
        return await host_run.execute(conversation, message, emit, body)
    return await run(function)


async def test_a_failed_screenshot_does_not_stop_the_turn(playwright, execution_db):
    answer = await _turn([("mcp_4__browser_take_screenshot", {"page": 1}, False)])
    assert answer == "Answer delivered"
    async with execution_db() as db:
        action = (await db.execute(select(TaskAction))).scalar_one()
        task = (await db.execute(select(CompanionTask))).scalar_one()
    assert (action.effect, action.status) == ("read", "failed")
    assert task.phase == "succeeded"


async def test_a_cleanly_refused_local_write_is_failed_not_unknown(execution_db):
    answer = await _turn([("write_file", {"path": "../outside.md"}, False)])
    assert answer == "Answer delivered"
    async with execution_db() as db:
        action = (await db.execute(select(TaskAction))).scalar_one()
    assert (action.effect, action.status) == ("local_write", "failed")


async def test_an_unknown_outcome_blocks_only_its_repeat_and_the_turn_still_answers(playwright, execution_db):
    click = ("mcp_4__browser_click", {"ref": "e1"}, False)
    answer = await _turn([click, ("mcp_4__browser_take_screenshot", {}, True)])
    assert answer == "Answer delivered", "other work continues after an unknown outcome"
    async with execution_db() as db:
        statuses = {a.tool_key: a.status for a in (await db.execute(select(TaskAction))).scalars()}
        task = (await db.execute(select(CompanionTask))).scalar_one()
    assert statuses == {"mcp_4__browser_click": "uncertain", "mcp_4__browser_take_screenshot": "succeeded"}
    assert (task.phase, task.pause_reason) == ("waiting_user", "task_reconciliation_required"), \
        "the user is still asked to check that one action"


async def test_repeating_the_unknown_action_is_refused_as_a_tool_result_not_a_crash(playwright, execution_db,
                                                                                     monkeypatch):
    from server.orchestrator import tool_loop

    class Executor:
        calls = 0

        async def execute(self, args):
            Executor.calls += 1
            return {"ok": False, "error": "synthetic failure"}

    async def resolve(key):
        return Executor()

    async def tools():
        return [{"key": "mcp_4__browser_click", "description": "click"}]
    monkeypatch.setattr(tool_loop, "resolve_executor", resolve)
    results = []

    async def function(conversation, message, emit):
        async def body(sink):
            for _ in range(2):
                results.append(await tool_loop._dispatch_tool(
                    "mcp_4__browser_click", {"ref": "e1"}, "", resolve_tools=tools, emit=emit,
                    tool_timeout_s=2, tool_trace=[], convo=[], conversation_id=conversation))
            return "Answer delivered"
        return await host_run.execute(conversation, message, emit, body)
    assert await run(function) == "Answer delivered"
    assert Executor.calls == 1, "the unknown action is never executed twice"
    assert results[1]["code"] == "task_reconciliation_required" and "Do not repeat" in results[1]["error"]

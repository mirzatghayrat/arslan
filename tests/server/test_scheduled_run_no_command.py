"""v0.1.63 (the user's decision until S2a-3 lands in v0.1.64): a scheduled run runs no command at all.

A scheduled run has nobody to ask. Until S2a-3 closes the command classifier's known gaps, it gets no run_command:
it is not offered there, and the tool loop refuses one anyway (a model may still name it, or reach it through
use_tool) before any rule, grant or "always" answer is read. The refusal is listed in the Inbox as the row decide()
writes for a run with nobody to ask (U14 c). Writes still go through write_file into Arslan's own folder.
DELETE-BY: v0.1.64, with S2a-3 and PR4 (scheduled runs get read-only commands back).
"""
from __future__ import annotations

import json

import pytest

from arslan.models import LLMResponse
from server.db import session as db_session
from server.db.models import Setting
from server.orchestrator import arslan as arslan_mod
from server.orchestrator import tool_loop
from server.services import permission_store, permissions, terminal_exec

CID = "sched-no-command"


@pytest.fixture(autouse=True)
def _fresh(execution_db, monkeypatch, tmp_path):
    permission_store._reset_for_tests()
    monkeypatch.setenv("ARSLAN_DEFAULT_WORKSPACE", str(tmp_path / "Arslan"))


@pytest.fixture
def ran(monkeypatch):
    """terminal_exec.run replaced: records every command that would have started, runs nothing."""
    calls: list[str] = []

    async def run(command, **kw):
        calls.append(command)
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "cwd": str(kw.get("cwd"))}
    monkeypatch.setattr(terminal_exec, "run", run)
    return calls


async def _ask(frame):
    raise AssertionError("no card in this test")


async def _yes(command, argv, **kw):
    return True


async def _stand(answer: str, command: str) -> None:
    """A standing answer that would let `command` run with no card in a turn with someone to ask."""
    from server.services import terminal_policy
    async with db_session.AsyncSessionLocal() as db:
        if answer == "ask only for risky commands":
            db.add(Setting(key="shell_confirm_policy", value="ask_risky"))
        elif answer == "always, this exact command":
            await permission_store.add_rule(db, "command", "text:" + command)
        elif answer == "always, the rules it matches":
            await permission_store.add_rule(db, "command", "rules:" + "|".join(sorted(terminal_policy.ask_rules(command))))
        elif answer == "this conversation, this exact command":
            await permission_store.add_grant(db, CID, "", "command", "text:" + command)
        elif answer == "this conversation, outside the sandbox":
            await permission_store.add_grant(db, CID, "", "outside", "*")
        await db.commit()


async def _dispatch(command: str, **kw):
    async def tools():
        return [{"key": "run_command", "description": "run_command"}]
    return await tool_loop._dispatch_tool("run_command", {"command": command, **kw}, "", resolve_tools=tools,
                                          emit=lambda e: None, tool_timeout_s=5, tool_trace=[], convo=[],
                                          conversation_id=CID, **({"confirm_command": _yes} if kw.pop("_yes", False) else {}))


async def _rows():
    async with db_session.AsyncSessionLocal() as db:
        return list(reversed(await permission_store.recent(db)))


STANDING = ["none", "ask only for risky commands", "always, this exact command", "always, the rules it matches",
            "this conversation, this exact command", "this conversation, outside the sandbox"]


@pytest.mark.parametrize("answer", STANDING)
@pytest.mark.parametrize("command", ["ls", "git push origin main"])
async def test_a_scheduled_run_never_starts_a_command_whatever_answer_stands(ran, answer, command):
    await _stand(answer, command)
    out = await _dispatch(command)
    assert ran == [] and out["ok"] is False
    assert "nobody to ask" in out["error"] and "don't run commands" in out["note"]
    [row] = await _rows()                                            # listed in the Inbox, once
    assert (row.kind, row.target, row.decided_by, row.decision, row.conversation_id) == (
        "command", "text:" + command, "policy", "deny", CID)
    assert permission_store.could_not_ask(row) and not (row.extra or {}).get(permissions.ALWAYS_KEY)


async def test_asked_to_run_outside_the_sandbox_it_is_refused_the_same_way(ran):
    await _stand("this conversation, outside the sandbox", "ls")
    out = await _dispatch("ls", outside_sandbox=True)
    [row] = await _rows()
    assert ran == [] and out["ok"] is False and (row.kind, row.target) == ("command", "text:ls")


async def test_with_someone_to_ask_a_command_still_runs(ran):
    """Only a run with nobody to ask loses commands: a chat turn's card is answered and the command starts."""
    with permissions.asking_with(_ask):
        out = await _dispatch("ls", _yes=True)
    assert ran == ["ls"] and out.get("ok") is not False


async def _in_a_turn(body):
    """Inside a turn, as a scheduled fire runs one (scheduler._fire: task_context.execute_entry, headless)."""
    from server.services import task_context
    return await task_context.execute_entry(CID, "list the folder", lambda e: None, lambda _sink: body(),
                                            headless=True)


async def test_run_command_is_offered_only_where_someone_can_be_asked():
    async def offered():
        return {tool["key"] for tool in await arslan_mod._callable_tools()}
    unattended = await _in_a_turn(offered)
    with permissions.asking_with(_ask):
        attended = await _in_a_turn(offered)
    outside_a_turn = await offered()                                 # the Capabilities page's list
    assert "run_command" not in unattended and "run_command" in attended and "run_command" in outside_a_turn
    assert "write_file" in unattended                                # writes still go to Arslan's own folder


class _CallsACommand:
    """A model that asks for `ls` once, then answers; keeps what it was offered and told."""

    def __init__(self):
        self.offered: list[set] = []
        self.inputs: list[str] = []

    async def chat(self, system, user, history=None, tools=None, temperature=0.7, **kwargs):
        self.offered.append({str((t.get("function") or t).get("name") or t.get("key")) for t in tools or []})
        self.inputs.append(json.dumps([*(history or []), {"role": "user", "content": user}], default=str))
        if len(self.inputs) == 1:
            return LLMResponse(content="", usage={}, tool_calls=[
                {"id": "c1", "type": "function", "function": {"name": "run_command", "arguments": {"command": "ls"}}}])
        return LLMResponse(content="done", tool_calls=[], usage={})


@pytest.mark.parametrize("offered", [False, True], ids=["as offered", "offered by mistake"])
async def test_a_real_scheduled_turn_with_every_standing_answer_runs_no_command(ran, monkeypatch, offered):
    """The scheduler's own path (run_arslan_turn: no callbacks, no card surface), with every answer that would
    let `ls` run in a chat turn standing at once. As offered, the model never sees run_command and naming it
    anyway is "not available"; were it offered by mistake, the tool loop still refuses it. Nothing starts."""
    for answer in STANDING[1:]:
        await _stand(answer, "ls")
    model = _CallsACommand()
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: model)
    if offered:
        for name in ("_arslan_tools", "_callable_tools"):
            assembled = getattr(arslan_mod, name)

            async def with_command(assembled=assembled):
                return [*await assembled(), {"key": "run_command", "description": "Run a shell command."}]
            monkeypatch.setattr(arslan_mod, name, with_command)
    from server.services import scheduler
    await _in_a_turn(lambda: scheduler.run_arslan_turn(CID, "list the folder"))
    assert ran == [] and len(model.inputs) == 2
    assert ("run_command" in model.offered[0]) is offered
    assert ("nobody to ask" if offered else "tool_unavailable") in model.inputs[1]

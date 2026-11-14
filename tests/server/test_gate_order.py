"""The order of a tool call's gates, and the words each one answers with.

For each tool, in order: a call that trips two gates is answered by the earlier one, the later one never runs (no card,
no executor), and the `tool_call` frame goes out only past the gates that come before it. Each gate alone is checked
too, so a pair can't pass because a trip did nothing. The pairs are each neighbour and the two ends of each list: a
swap of any two gates puts some neighbouring pair out of order. It tests the order and what each gate says, not what
each gate decides: that is what the gates' own tests are for, so a trip uses the simplest input that reaches its gate.
A PR that adds, removes or moves a gate on purpose changes the lists below.

The end of the file reads the outside grant and the sandbox setting for real, and has a card say no the way a real
one does (#761's review).
"""
import json
import types
from dataclasses import dataclass
from typing import Callable

import pytest

from arslan.execution_budget import Budget, BudgetExceeded, Limits, scope
from server.db import session as db_session
from server.orchestrator import command_gate, tool_gates, tool_loop
from server.orchestrator.turn_state import ToolTurn
from server.registry import executors, ssh_tools
from server.services import (
    approvals,
    command_sandbox,
    permission_store,
    permissions,
    task_service,
)
from tests.server.scripted_turn import booted_db_fixture, turn_db_fixture  # noqa: F401 — the fixtures

SECRET = {"password": "not-a-real-one"}


class _Env:
    """One call: what it passes and what happens around it. The trips change this; `run` makes the call."""

    def __init__(self, tool, args, monkeypatch):
        self.tool, self.args, self.monkeypatch = tool, dict(args), monkeypatch
        self.live, self.conversation_id, self.budget = {tool}, "c1", None
        self.frames, self.trace, self.convo, self.cards, self.ran = [], [], [], [], []
        self.confirm_command = self._card("command", True)
        self.confirm_workspace_write = self._card("write", True)
        self.confirm_schedule = self._card("schedule", True)
        self.mcp_fail_counts = {}
        self.fails = None

    def _card(self, name, answer):
        async def card(*_args, **_own):
            self.cards.append(name)
            return answer
        return card

    async def run(self):
        async def resolve():
            return [{"key": key, "description": "d"} for key in self.live]

        async def execute(_args):
            self.ran.append(self.tool)
            if self.fails is not None:
                raise self.fails
            return {"ok": True, "summary": "the executor ran"}
        self.monkeypatch.setitem(executors.EXECUTORS, self.tool, types.SimpleNamespace(key=self.tool, execute=execute))
        turn = ToolTurn(resolve_tools=resolve, emit=self.frames.append, tool_timeout_s=5, tool_trace=self.trace,
                        convo=self.convo, confirm_command=self.confirm_command,
                        confirm_workspace_write=self.confirm_workspace_write, confirm_schedule=self.confirm_schedule,
                        mcp_fail_counts=self.mcp_fail_counts, conversation_id=self.conversation_id)
        with scope(self.budget or Budget()):
            return await tool_loop._run_tool(self.tool, self.args, "{}", turn)


@dataclass(frozen=True)
class Gate:
    name: str
    trip: Callable[[_Env], None]
    says: str | type            # the key phrase of what the model reads, or the exception it raises
    before_frame: bool = False  # answers before the `tool_call` frame goes out
    card: str | None = None     # the card it shows on the way to its answer


def _spent(env):
    env.budget = Budget(Limits(tool_calls=1))
    env.budget.tool_calls = 1


def _secret(env):
    env.args.update(SECRET)


def _nobody(env):
    env.confirm_command = None
    env.monkeypatch.setattr(permissions, "current_asker", lambda: None)


def _not_live(env):
    env.live = set()


def _plan(env):
    async def plan(_conversation_id):
        return "plan"
    env.monkeypatch.setattr(permissions, "_chosen", plan)


def _no_path(env):
    env.args["path"] = ""


def _no_write_card(env):
    env.confirm_workspace_write = None


def _write_declined(env):
    env.confirm_workspace_write = env._card("write", False)


def _no_schedule_card(env):
    env.confirm_schedule = None


def _too_long(env):
    env.args["prompt"] = "x" * 20_000


def _schedule_declined(env):
    env.confirm_schedule = env._card("schedule", False)


def _words(env, word):
    env.args["command"] = f"{word} ; {env.args['command']}" if env.args.get("command") else word


def _forbidden(env):
    _words(env, "rm -rf /")


def _heredoc(env):
    _words(env, "X=$(cat <<EOF\nhi\nEOF\n)")


def _jxa(env):
    _words(env, "osascript -l JavaScript -e x")


def _outside_no_callback(env):
    env.args["outside_sandbox"] = True
    env.confirm_command = None
    env.monkeypatch.setattr(permissions, "current_asker", lambda: object())


def _outside_no_why(env):
    env.args["outside_sandbox"] = True
    env.args.pop("why", None)


def _outside_declined(env):
    env.args.update(outside_sandbox=True, why="it needs the keychain")
    env.confirm_command = env._card("command", False)


def _ask_no_callback(env):
    _words(env, "git push origin main")
    env.confirm_command = None
    env.monkeypatch.setattr(permissions, "current_asker", lambda: object())


def _command_declined(env):
    _words(env, "git push origin main")
    env.confirm_command = env._card("command", False)


def _network_refused(env):
    async def refused(*_args, **_own):
        return {"refused": "the network was refused"}
    env.monkeypatch.setattr(command_gate, "_network_after_outside_content", refused)


def _remote_no_callback(env):
    env.confirm_command = None


def _remote_declined(env):
    env.confirm_command = env._card("command", False)


async def _prepared(_args):
    return {"ok": True, "command": "uptime", "argv": [], "user": "me", "host": "10.0.0.2", "node_name": None,
            "name": "box", "fingerprints": {"sha256": "x"}}


async def _unprepared(_args):
    return {"ok": False, "error": "could not prepare it"}


def _ssh_unreachable(env):
    env.monkeypatch.setattr(ssh_tools, "prepare_confirmation", _unprepared)
    env.monkeypatch.setattr(ssh_tools, "prepare_enrollment", _unprepared)


BUDGET = Gate("budget", _spent, BudgetExceeded, before_frame=True)
CREDENTIALS = Gate("credentials", _secret,
                   "Credentials cannot be passed as ordinary tool arguments. Use an approved connection.",
                   before_frame=True)
UNAVAILABLE = Gate("unavailable", _not_live, "is not available to you; you may escalate a need instead")
COMMON = [BUDGET, CREDENTIALS, UNAVAILABLE]
# S5a (#893): after the common gates and before the tool's own, for a command or any tool that isn't a read.
PLAN = Gate("plan mode", _plan, "Plan mode: this conversation only reads and plans for now")
FILE_ARGUMENTS = Gate("file arguments", _no_path, "A non-empty string path is required; write_file also requires "
                      "string content. No permission decision was requested and no file was accessed.")
WRITE_DECLINED = Gate("write declined", _write_declined, "user declined workspace write access", card="write")
FORBIDDEN = Gate("forbidden", _forbidden, "Arslan never runs this: recursive delete of the whole disk")
HEREDOC = Gate("here-document", _heredoc,
               "A here-document inside $( ) can't run here: in bash 3.2 its text can end the substitution early")
JXA = Gate("JXA", _jxa, "JXA (osascript -l JavaScript) cannot control apps from run_command")
NETWORK = Gate("network refused", _network_refused, "the network was refused")


CHAINS = {
    "web_search": ({"query": "x"}, [*COMMON]),
    "read_file": ({"path": "a.md"}, [*COMMON, FILE_ARGUMENTS]),
    "write_file": ({"path": "a.md", "content": "x"}, [
        *COMMON, PLAN, FILE_ARGUMENTS,
        Gate("no write card", _no_write_card, "writing to the workspace needs your permission, which is not "
             "available on this channel"),
        WRITE_DECLINED]),
    "edit_file": ({"path": "a.md"}, [*COMMON, PLAN, WRITE_DECLINED]),
    "schedule_task": ({"name": "n", "when": "every: 3600", "prompt": "p"}, [
        *COMMON, PLAN,
        Gate("no schedule card", _no_schedule_card, "scheduling needs your permission, which is not available on "
             "this channel"),
        Gate("too long", _too_long, "Not scheduled: the task's text is 20000 characters, more than a card can show "
             "the user (4000). Shorten it."),
        Gate("schedule declined", _schedule_declined, "user declined to schedule this task", card="schedule")]),
    "run_command": ({"command": "ls"}, [
        BUDGET, CREDENTIALS,
        Gate("nobody to ask", _nobody, "needs the user's OK, and this run has nobody to ask: a scheduled run never "
             "takes such a step, and no earlier answer counts here. It was not done."),
        UNAVAILABLE, PLAN, FORBIDDEN, HEREDOC, JXA,
        Gate("outside, no click", _outside_no_callback, "running a command outside the sandbox needs the user's "
             "click, which is not available here"),
        Gate("outside, no why", _outside_no_why, "outside_sandbox needs a why: one short sentence on why this has to "
             "run outside the sandbox. The user reads it on the card."),
        Gate("outside declined", _outside_declined, "user declined running this command outside the sandbox",
             card="command"),
        NETWORK]),
    "run_command#ask": ({"command": "ls"}, [
        FORBIDDEN, HEREDOC, JXA,
        Gate("ask, no click", _ask_no_callback, "run_command requires user confirmation, which is not available in "
             "this context"),
        Gate("command declined", _command_declined, "user declined this command'", card="command"),
        NETWORK]),
    "ssh_run": ({"host": "10.0.0.2", "user": "me", "command": "uptime"}, [
        *COMMON, PLAN,
        Gate("no remote card", _remote_no_callback, "running a command on another machine requires your "
             "confirmation, which is not available in this context"),
        Gate("cannot reach", _ssh_unreachable, "could not prepare it"),
        Gate("remote declined", _remote_declined, "user declined this remote command", card="command")]),
    "enroll_node": ({"host": "10.0.0.2", "user": "me", "name": "box"}, [
        *COMMON, PLAN,
        Gate("no enrol card", _remote_no_callback, "enrolling a machine has to be proposed to you directly, and there "
             "is nobody on this channel to propose it to"),
        Gate("cannot enrol", _ssh_unreachable, "could not prepare it")]),
    "mac_applescript": ({"script": "x"}, [*COMMON, PLAN]),
    "run_python": ({"code": "x"}, [*COMMON, PLAN]),
    "mcp_1__lookup": ({}, [*COMMON, PLAN]),
}


def _pairs(gates):
    """Each neighbour, and the first against the last."""
    pairs = list(zip(gates, gates[1:]))
    return pairs + [(gates[0], gates[-1])] if len(gates) > 2 else pairs


PAIRS = [pytest.param(chain, earlier, later, id=f"{chain}: {earlier.name} before {later.name}")
         for chain, (_args, gates) in CHAINS.items() for earlier, later in _pairs(gates)]
SINGLES = [pytest.param(chain, gate, id=f"{chain}: {gate.name}")
           for chain, (_args, gates) in CHAINS.items() for gate in gates]


@pytest.fixture(autouse=True)
def _a_mac_with_a_sandbox(monkeypatch, turn_db):
    """Whichever way the settings read, the gates under test are reached the same way."""
    async def no():
        return False

    async def yes():
        return True

    async def nothing(*_args, **_own):
        return {}

    async def no_grant(*_args, **_own):
        return None
    monkeypatch.setattr(tool_gates, "_writing_in_own_folder", no)
    monkeypatch.setattr(command_gate, "_asks_for_everything", no)
    monkeypatch.setattr(command_gate, "_sandbox_enabled", yes)
    monkeypatch.setattr(command_gate, "_network_after_outside_content", nothing)
    monkeypatch.setattr(command_gate, "_outside_grant", no_grant)
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    monkeypatch.setattr(ssh_tools, "prepare_confirmation", _prepared)
    monkeypatch.setattr(ssh_tools, "prepare_enrollment", _prepared)
    monkeypatch.setattr(permissions, "current_asker", lambda: object())
    monkeypatch.setattr(task_service, "current", lambda: None)
    yield


def _env(chain, monkeypatch):
    args, _gates = CHAINS[chain]
    return _Env(chain.split("#")[0], args, monkeypatch)


async def _outcome(env):
    """What answered the call: the result as text, or the exception's class."""
    try:
        return str(await env.run())
    except BudgetExceeded as exc:
        return type(exc)


def _answered_by(gate, env, outcome):
    assert (outcome is gate.says) if isinstance(gate.says, type) else (gate.says in str(outcome)), (
        f"{gate.name} did not answer: {str(outcome)[:300]}")
    assert env.ran == [], f"the executor ran past {gate.name}"
    assert env.cards == ([gate.card] if gate.card else []), f"cards past {gate.name}: {env.cards}"
    framed = any(frame.get("type") == "tool_call" for frame in env.frames)
    assert framed is not gate.before_frame, f"the tool_call frame around {gate.name}"


@pytest.mark.parametrize("chain,gate", SINGLES)
async def test_each_gate_answers_on_its_own_in_its_words(chain, gate, monkeypatch):
    env = _env(chain, monkeypatch)
    gate.trip(env)
    _answered_by(gate, env, await _outcome(env))


@pytest.mark.parametrize("chain,earlier,later", PAIRS)
async def test_the_earlier_gate_answers(chain, earlier, later, monkeypatch):
    env = _env(chain, monkeypatch)
    later.trip(env)     # the earlier one goes second: where both set the same thing, it stands
    earlier.trip(env)
    _answered_by(earlier, env, await _outcome(env))


@pytest.mark.parametrize("chain", list(CHAINS))
async def test_with_no_gate_tripped_the_executor_runs(chain, monkeypatch):
    env = _env(chain, monkeypatch)
    outcome = await _outcome(env)
    if env.tool == "enroll_node":
        assert "asked the user to enrol" in outcome and env.ran == []     # a card, never the executor
    else:
        assert env.ran == [env.tool], outcome


async def test_a_former_eval_id_gets_the_live_gates(monkeypatch):
    """C7c-3b: `evolution-replay` names an ordinary conversation now. Its write card still binds, and a yes runs the
    write as under any other id (the eval backstop used to refuse it after the card)."""
    declined = _env("write_file", monkeypatch)
    declined.conversation_id = "evolution-replay"
    WRITE_DECLINED.trip(declined)
    _answered_by(WRITE_DECLINED, declined, await _outcome(declined))
    approved = _env("write_file", monkeypatch)
    approved.conversation_id = "evolution-replay"
    outcome = await _outcome(approved)
    assert approved.cards == ["write"] and approved.ran == ["write_file"], outcome


@pytest.mark.parametrize("gate,recorded_args,counted", [(CREDENTIALS, {}, 1), (UNAVAILABLE, {"q": 1}, 1)])
async def test_what_a_refusal_records(gate, recorded_args, counted, monkeypatch):
    """A credentials refusal records no arguments, in the trace and in the call's own text. The rest record the call
    as it came. Each counts against an MCP tool's streak. (The helpers' scope refusal, which recorded none and didn't
    count, went with the helpers in v0.1.64 SUB6.)"""
    env = _Env("mcp_1__lookup", {"q": 1}, monkeypatch)
    gate.trip(env)
    await _outcome(env)
    assert env.trace[-1]["args"] == recorded_args
    assert env.convo[-1]["_legacy_call"] == ("{}" if recorded_args else json.dumps({"tool": env.tool, "args": {}}))
    assert env.mcp_fail_counts.get("mcp_1__lookup", 0) == counted


@pytest.mark.parametrize("chain,failure,says", [
    ("read_file", RuntimeError("it broke"), "tool 'read_file' failed: it broke"),
    ("read_file", TimeoutError(), "tool 'read_file' timed out"),
    ("run_command", TimeoutError(), "stopped by the time limit; no output was captured"),
], ids=["read_file: the executor raises", "read_file: the executor times out", "run_command: the executor times out"])
async def test_what_a_failing_executor_answers(chain, failure, says, monkeypatch):
    env = _env(chain, monkeypatch)
    env.fails = failure
    result = await env.run()
    assert result["ok"] is False and result["error"] == says, result


# ── #761's review: the words of a card that says no, the stored grant and the sandbox setting, read for real ──────────
# The fixture above stubs `_outside_grant` and `_sandbox_enabled`, and its cards leave no decision behind. Here a card
# says no the way a real one does, and the grant and the setting are read.

REAL_OUTSIDE_GRANT = command_gate._outside_grant
REAL_SANDBOX_ENABLED = command_gate._sandbox_enabled
NOTE = "Not in this folder, please."
# The tool, its arguments, the card's callback, the card, and what the expired card names
DECLINING = {
    "write_file": ({"path": "a.md", "content": "x"}, "confirm_workspace_write", "write", "writing to the workspace"),
    "edit_file": ({"path": "a.md"}, "confirm_workspace_write", "write", "writing to the workspace"),
    "schedule_task": ({"name": "n", "when": "every: 3600", "prompt": "p"}, "confirm_schedule", "schedule",
                      "scheduling this task"),
    "run_command#outside": ({"command": "ls", "outside_sandbox": True, "why": "it needs the keychain"},
                            "confirm_command", "command", "running this command outside the sandbox"),
    "run_command#ask": ({"command": "git push origin main"}, "confirm_command", "command", "this command"),
    "ssh_run": ({"host": "10.0.0.2", "user": "me", "command": "uptime"}, "confirm_command", "command",
                "this remote command"),
}


def _declining(env, card, *, expired):
    """A card that says no as a real one does: with the user's note, or with nobody answering it."""
    async def no(*_args, **_own):
        env.cards.append(card)
        if expired:
            approvals.LAST_OUTCOME.set("expired")
        else:
            permissions.LAST_DECISION.set(permissions.Decision(False, "user", note=NOTE, model_text=NOTE))
        return False
    return no


@pytest.mark.parametrize("expired", [False, True], ids=["with the user's note", "nobody answered"])
@pytest.mark.parametrize("chain", list(DECLINING))
async def test_a_card_that_says_no_tells_the_model_what_it_said(chain, expired, monkeypatch):
    args, callback, card, subject = DECLINING[chain]
    env = _Env(chain.split("#")[0], args, monkeypatch)
    setattr(env, callback, _declining(env, card, expired=expired))
    result = await env.run()
    assert result["error"] == (f"Nobody answered the card for {subject} in 30 minutes. This is NOT a refusal. "
                               "Don't retry it in this turn. Finish what you can and tell the user what is waiting."
                               if expired else NOTE)
    assert env.cards == [card] and env.ran == []


async def _stored_grant():
    """The outside card's "In this conversation", as it is stored."""
    async with db_session.AsyncSessionLocal() as db:
        grant = await permission_store.add_grant(db, "c1", "", "outside", "*", call_id="card-1")
        await db.commit()
        return grant.id


async def _ledger():
    async with db_session.AsyncSessionLocal() as db:
        return [(row.kind, row.decided_by, row.decision, row.detail)
                for row in reversed(await permission_store.recent(db))]


async def _no_card_surface_is_used(frame):
    raise AssertionError(f"a card was shown: {frame}")


async def test_a_stored_grant_lets_a_command_out_with_no_card_and_writes_its_row(monkeypatch):
    monkeypatch.setattr(command_gate, "_outside_grant", REAL_OUTSIDE_GRANT)
    await _stored_grant()
    env = _Env("run_command", {"command": "ls"}, monkeypatch)
    with permissions.asking_with(_no_card_surface_is_used):
        result = await env.run()
    assert result.get("ran_outside_sandbox") is True and "grant_note" not in result, result
    assert env.cards == [] and env.ran == ["run_command"]
    assert await _ledger() == [("outside", "grant", "allow", "ls")]


@pytest.mark.parametrize("sandbox", [True, False], ids=["it runs in the sandbox", "with no sandbox it doesn't run"])
async def test_a_grant_taken_back_while_its_card_waits_is_read_again(sandbox, monkeypatch):
    """The grant is read before any card and again after the last one: taken back in between, the command doesn't
    leave the sandbox, and where no sandbox can start it doesn't run. No grant row either way."""
    monkeypatch.setattr(command_gate, "_outside_grant", REAL_OUTSIDE_GRANT)
    monkeypatch.setattr(command_sandbox, "available", lambda: sandbox)
    grant = await _stored_grant()
    env = _Env("run_command", {"command": "git push origin main"}, monkeypatch)     # its own card, grant or not

    async def take_it_back(*_args, **_own):
        env.cards.append("command")
        async with db_session.AsyncSessionLocal() as db:
            await permission_store.delete_conversation_grant(db, grant)
            await db.commit()
        return True
    env.confirm_command = take_it_back
    with permissions.asking_with(_no_card_surface_is_used):
        result = await env.run()
    assert env.cards == ["command"] and "ran_outside_sandbox" not in result, result
    if sandbox:
        assert env.ran == ["run_command"] and result["grant_note"].endswith("it ran in the sandbox")
    else:
        assert env.ran == [] and result["error"].endswith("taken back while this one waited; it did not run")
    assert await _ledger() == []


@pytest.mark.parametrize("reads,answer", [("unreadable", "outside_sandbox needs a why"), ("off", "the executor ran")])
async def test_an_unreadable_sandbox_setting_means_the_sandbox_is_on(reads, answer, monkeypatch):
    """Asked to leave the sandbox with no why: refused while the sandbox is on, which it is when the setting can't be
    read; with the sandbox off there is nothing to leave, and the command takes its own card."""
    from server.services import settings_service
    monkeypatch.setattr(command_gate, "_sandbox_enabled", REAL_SANDBOX_ENABLED)

    async def setting(_db):
        if reads == "unreadable":
            raise RuntimeError("the settings can't be read")
        return False
    monkeypatch.setattr(settings_service, "terminal_sandbox_enabled", setting)
    env = _Env("run_command", {"command": "ls", "outside_sandbox": True}, monkeypatch)
    assert answer in await _outcome(env)
    assert env.cards == ([] if reads == "unreadable" else ["command"])

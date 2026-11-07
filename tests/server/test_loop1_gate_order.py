"""LOOP1 L0: the order of `_dispatch_tool`'s gates, pinned pair by pair, before any gate moves.

For each tool, in today's order: a call that trips two gates is answered by the earlier one, the later one never runs
(no card, no executor), and the `tool_call` frame goes out only past the gates that come before it. Each gate alone is
checked too, so a pair can't pass because a trip did nothing. It tests the order and what each gate says, not what each
gate decides: that is what the gates' own tests are for, so a trip uses the simplest input that reaches its gate.

Temporary: DELETE-BY: v0.1.64, with LOOP1's slice z (docs/plans/0164/LOOP1-agent-loop.md). A PR that adds, removes or
moves a gate on purpose changes the lists below.
"""
import itertools
import json
import os
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

from arslan.execution_budget import Budget, BudgetExceeded, Limits, scope
from server.orchestrator import tool_loop
from server.registry import executors, ssh_tools
from server.db import session as db_session
from server.services import approvals, command_sandbox, permission_store, permissions, task_service, task_workers
from tests.server.test_loop1_pinned_turns import _booted, _database  # noqa: F401 — the fixtures
from server.orchestrator import command_gate

HERMETIC = "evolution-replay"
SECRET = {"password": "not-a-real-one"}
ANSWERS = Path(__file__).parent / "golden" / "loop1_gate_answers.json"
REGENERATE = "ARSLAN_UPDATE_GOLDEN=1 pytest tests/server/test_loop1_gate_order.py"


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
        with scope(self.budget or Budget()):
            return await tool_loop._dispatch_tool(
                self.tool, self.args, "{}", resolve_tools=resolve, emit=self.frames.append, tool_timeout_s=5,
                tool_trace=self.trace, convo=self.convo, confirm_command=self.confirm_command,
                confirm_workspace_write=self.confirm_workspace_write, confirm_schedule=self.confirm_schedule,
                mcp_fail_counts=self.mcp_fail_counts, conversation_id=self.conversation_id)


@dataclass(frozen=True)
class Gate:
    name: str
    trip: Callable[[_Env], None]
    answer: str | type          # in the result's text, or the exception it raises
    before_frame: bool = False  # answers before the `tool_call` frame goes out
    card: str | None = None     # the card it shows on the way to its answer


def _set(**fields):
    def trip(env):
        for key, value in fields.items():
            setattr(env, key, value)
    return trip


def _spent(env):
    env.budget = Budget(Limits(tool_calls=1))
    env.budget.tool_calls = 1


def _secret(env):
    env.args.update(SECRET)


def _other_worker(env):
    token = task_workers._worker.set(task_workers.WorkerScope("w1", "t1", frozenset()))
    env.monkeypatch.setattr(task_service, "current", lambda: types.SimpleNamespace(task_id="t1", closed=False))
    env.tokens = (task_workers._worker, token)


def _nobody(env):
    env.confirm_command = None
    env.monkeypatch.setattr(permissions, "current_asker", lambda: None)


def _not_live(env):
    env.live = set()


def _fetches_spent(env):
    env.conversation_id = HERMETIC
    tool_loop.reset_hermetic_fetch_budget()
    tool_loop._hermetic_fetches[HERMETIC] = tool_loop.HERMETIC_FETCH_BUDGET


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


def _hermetic(env):
    env.conversation_id = HERMETIC


def _valve(env):
    env.conversation_id = HERMETIC
    env.monkeypatch.setenv("ARSLAN_ALLOW_UNSANDBOXED_PY", "1")


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
CREDENTIALS = Gate("credentials", _secret, "credentials_not_tool_data", before_frame=True)
WORKER = Gate("worker", _other_worker, "worker_tool_scope_denied", before_frame=True)
UNAVAILABLE = Gate("unavailable", _not_live, "tool_unavailable")
HERMETIC_GATE = Gate("hermetic", _hermetic, "evaluation context")
COMMON = [BUDGET, CREDENTIALS, WORKER, UNAVAILABLE]


AFTER_THE_GATES = {"read_file: the executor raises": RuntimeError("it broke"),
                   "read_file: the executor times out": TimeoutError(),
                   "run_command: the executor times out": TimeoutError()}


def _hermetic_after(card):
    """The eval backstop comes after the tool's own card: an approved card is shown, then the call is refused."""
    return Gate("hermetic", _hermetic, "evaluation context", card=card)



CHAINS = {
    "web_search": ({"query": "x"}, [*COMMON, Gate("fetch budget", _fetches_spent, "evaluation fetch budget")]),
    "read_file": ({"path": "a.md"}, [*COMMON, Gate("file arguments", _no_path, "invalid_file_arguments"), HERMETIC_GATE]),
    "write_file": ({"path": "a.md", "content": "x"}, [
        *COMMON, Gate("file arguments", _no_path, "invalid_file_arguments"),
        Gate("no write card", _no_write_card, "writing to the workspace needs your permission"),
        Gate("write declined", _write_declined, "user declined workspace write access", card="write"),
        _hermetic_after("write")]),
    "edit_file": ({"path": "a.md"}, [
        *COMMON, Gate("write declined", _write_declined, "user declined workspace write access", card="write"),
        _hermetic_after("write")]),
    "schedule_task": ({"name": "n", "when": "every: 3600", "prompt": "p"}, [
        *COMMON, Gate("no schedule card", _no_schedule_card, "scheduling needs your permission"),
        Gate("too long", _too_long, "too_long_to_show"),
        Gate("schedule declined", _schedule_declined, "user declined to schedule this task", card="schedule"),
        _hermetic_after("schedule")]),
    "run_command": ({"command": "ls"}, [
        BUDGET, CREDENTIALS, WORKER, Gate("nobody to ask", _nobody, "Scheduled runs don't run commands"), UNAVAILABLE,
        Gate("forbidden", _forbidden, "Arslan never runs this"),
        Gate("here-document", _heredoc, "A here-document inside $( ) can't run here"),
        Gate("JXA", _jxa, "JXA (osascript -l JavaScript)"),
        Gate("outside, no click", _outside_no_callback, "needs the user's click"),
        Gate("outside, no why", _outside_no_why, "outside_sandbox needs a why"),
        Gate("outside declined", _outside_declined, "user declined running this command outside", card="command"),
        Gate("network refused", _network_refused, "the network was refused"), HERMETIC_GATE]),
    "run_command#ask": ({"command": "ls"}, [
        Gate("forbidden", _forbidden, "Arslan never runs this"),
        Gate("here-document", _heredoc, "A here-document inside $( ) can't run here"),
        Gate("JXA", _jxa, "JXA (osascript -l JavaScript)"),
        Gate("ask, no click", _ask_no_callback, "requires user confirmation"),
        Gate("command declined", _command_declined, "user declined this command", card="command"),
        Gate("network refused", _network_refused, "the network was refused"), HERMETIC_GATE]),
    "ssh_run": ({"host": "10.0.0.2", "user": "me", "command": "uptime"}, [
        *COMMON, Gate("no remote card", _remote_no_callback, "running a command on another machine requires"),
        Gate("cannot reach", _ssh_unreachable, "could not prepare it"),
        Gate("remote declined", _remote_declined, "user declined this remote command", card="command"),
        _hermetic_after("command")]),
    "enroll_node": ({"host": "10.0.0.2", "user": "me", "name": "box"}, [
        *COMMON, Gate("no enrol card", _remote_no_callback, "enrolling a machine has to be proposed"),
        Gate("cannot enrol", _ssh_unreachable, "could not prepare it")]),
    "mac_applescript": ({"script": "x"}, [*COMMON, HERMETIC_GATE]),
    "run_python": ({"code": "x"}, [*COMMON, Gate("the escape valve", _valve, "unsandboxed escape valve")]),
    "mcp_1__lookup": ({}, [*COMMON, HERMETIC_GATE]),
}


PAIRS = [pytest.param(chain, earlier, later, id=f"{chain}: {earlier.name} before {later.name}")
         for chain, (_args, gates) in CHAINS.items() for earlier, later in itertools.combinations(gates, 2)]
SINGLES = [pytest.param(chain, gate, id=f"{chain}: {gate.name}")
           for chain, (_args, gates) in CHAINS.items() for gate in gates]


@pytest.fixture(autouse=True)
def _a_mac_with_a_sandbox(monkeypatch, _database):  # noqa: F811
    """Whichever way the settings read, the gates under test are reached the same way."""
    async def no():
        return False

    async def yes():
        return True

    async def nothing(*_args, **_own):
        return {}

    async def no_grant(*_args, **_own):
        return None
    monkeypatch.setattr(tool_loop, "_writing_in_own_folder", no)
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
    tool_loop.reset_hermetic_fetch_budget()


def _env(chain, monkeypatch):
    args, _gates = CHAINS[chain]
    return _Env(chain.split("#")[0], args, monkeypatch)


async def _outcome(env):
    """What answered the call: the result as text, or the exception's class."""
    try:
        return str(await env.run())
    except BudgetExceeded as exc:
        return type(exc)
    finally:
        tokens = getattr(env, "tokens", None)
        if tokens:
            tokens[0].reset(tokens[1])


def _answered_by(gate, env, outcome):
    assert (outcome is gate.answer) if isinstance(gate.answer, type) else (gate.answer in str(outcome)), (
        f"{gate.name} did not answer: {str(outcome)[:300]}")
    assert env.ran == [], f"the executor ran past {gate.name}"
    assert env.cards == ([gate.card] if gate.card else []), f"cards past {gate.name}: {env.cards}"
    framed = any(frame.get("type") == "tool_call" for frame in env.frames)
    assert framed is not gate.before_frame, f"the tool_call frame around {gate.name}"


@pytest.mark.parametrize("chain,gate", SINGLES)
async def test_each_gate_answers_on_its_own(chain, gate, monkeypatch):
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
    if env.tool in ("mac_applescript", "run_python", "mcp_1__lookup"):
        env.conversation_id = "c1"
    outcome = await _outcome(env)
    if env.tool == "enroll_node":
        assert "asked the user to enrol" in outcome and env.ran == []     # a card, never the executor
    else:
        assert env.ran == [env.tool], outcome


async def test_enrolling_answers_before_the_eval_backstop(monkeypatch):
    env = _env("enroll_node", monkeypatch)
    _hermetic(env)
    assert "asked the user to enrol" in await _outcome(env)


@pytest.mark.parametrize("gate,recorded_args,counted", [
    (CREDENTIALS, {}, 1), (WORKER, {}, 0), (UNAVAILABLE, {"q": 1}, 1), (HERMETIC_GATE, {"q": 1}, 1)])
async def test_what_a_refusal_records(gate, recorded_args, counted, monkeypatch):
    """Two refusals record no arguments, in the trace and in the call's own text, and one of them doesn't count
    against an MCP tool's streak. The rest record the call as it came."""
    env = _Env("mcp_1__lookup", {"q": 1}, monkeypatch)
    gate.trip(env)
    await _outcome(env)
    assert env.trace[-1]["args"] == recorded_args
    assert env.convo[-1]["_legacy_call"] == ("{}" if recorded_args else json.dumps({"tool": env.tool, "args": {}}))
    assert env.mcp_fail_counts.get("mcp_1__lookup", 0) == counted


async def test_what_each_gate_answers_word_for_word(monkeypatch):
    """The model reads these words. A gate that moves says the same thing from its new place."""
    answers = {"_": "DELETE-BY: v0.1.64, with LOOP1's slice z (docs/plans/0164/LOOP1-agent-loop.md)"}
    for chain, (_args, gates) in CHAINS.items():
        for gate in gates:
            with monkeypatch.context() as patch:
                env = _env(chain, patch)
                gate.trip(env)
                answers[f"{chain}: {gate.name}"] = str(await _outcome(env))
            tool_loop.reset_hermetic_fetch_budget()
    for name, failure in AFTER_THE_GATES.items():
        env = _env(name.split(":")[0], monkeypatch)
        env.fails = failure
        answers[name] = str(await _outcome(env))
    text = json.dumps(answers, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if os.environ.get("ARSLAN_UPDATE_GOLDEN") == "1":
        ANSWERS.write_text(text, encoding="utf-8")
    assert text == ANSWERS.read_text(encoding="utf-8"), (
        f"what a gate says changed. If you meant it, commit the new JSON, so the diff shows the change: {REGENERATE}")


# ── #761's review: the words of a card that says no, the stored grant and the sandbox setting, read for real ──────────
# The fixture above stubs `_outside_grant` and `_sandbox_enabled`, and its cards leave no decision behind, so these were
# held only by other tests. Here a card says no the way a real one does, and the grant and the setting are read.

REAL_OUTSIDE_GRANT = command_gate._outside_grant
REAL_SANDBOX_ENABLED = command_gate._sandbox_enabled
NOTE = "Not in this folder, please."
# The tool, its arguments, the card's callback, the card, and what `_declined` names
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

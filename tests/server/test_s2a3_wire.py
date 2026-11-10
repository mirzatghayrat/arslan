"""S2a-3 step 3, the wire: a command whose only rule is `unreadable` runs in the sandbox, offline, with no card.

All of these must hold, or the call gets today's card: the sandbox is on and can start; no "ask for every command";
the working folder is neither home nor holds it (read on every call); the call has no `network: true`; and the
conversation has no grant to leave the sandbox (⓪Plan's ruling 2). The note says why it ran offline and how to ask
for the network; the run step carries a mark SBX-8 counts. And `assess` folds "the reader does not understand it, no
named rule" into `unreadable`, so the card, the approvals, the Island and the risk grade read one table.

No real command text: the reader (`shell_grammar.read`) is replaced so that a placeholder is "not understood"."""
from __future__ import annotations

import contextlib
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from server.orchestrator import command_gate, run_trace, tool_loop, untrusted
from server.orchestrator.turn_state import ToolTurn
from server.services import (approvals, command_sandbox, permissions, run_recorder, shell_grammar, terminal_exec,
                             terminal_policy as tp)

STAND_IN = "zz-stand-in"
WHY = "stand-in reason"


def _clear_reading():
    """The policy keeps the reader's answer per text; a test that replaces the reader starts from none."""
    getattr(getattr(tp, "_not_understood", None), "cache_clear", lambda: None)()


@pytest.fixture
def unread(monkeypatch):
    """The reader does not understand the placeholder; anything else reads as it does on main."""
    real = shell_grammar.read

    def read(text, *, fold_partial=True, fold_guard=None):
        if isinstance(text, str) and text.startswith(STAND_IN):
            return shell_grammar.Reading(understood=False, why=WHY)
        return real(text, fold_partial=fold_partial, fold_guard=fold_guard)
    _clear_reading()
    monkeypatch.setattr(shell_grammar, "read", read)
    yield
    _clear_reading()


# ── point 4: one table ───────────────────────────────────────────────────────

def test_a_placeholder_the_reader_understands_runs():
    _clear_reading()
    assert tp.assess(STAND_IN) == tp.Assessment("run") and tp.ask_rules(STAND_IN) == set()


def test_not_understood_with_no_named_rule_is_unreadable_everywhere(unread):
    assert tp.assess(STAND_IN) == tp.Assessment("ask", tp.UNREADABLE, WHY)
    assert tp.ask_rules(STAND_IN) == {tp.UNREADABLE}
    assert tp.risk_grade(STAND_IN) == "MEDIUM"
    assert approvals.island_may_answer({"type": "propose_run_command", "pretty": STAND_IN,
                                        "perm_kind": "command"}) is False


def test_a_named_rule_still_comes_first_and_alone(unread, monkeypatch):
    real = tp._layer_two
    monkeypatch.setattr(tp, "_layer_two", lambda texts, commands=(), *, text, cwd=None, **_: [("stand-in-rule", "stand-in")]
                        if any(t.startswith(STAND_IN) for t in texts) else real(texts, commands, text=text, cwd=cwd))
    assert tp.assess(STAND_IN) == tp.Assessment("ask", "stand-in-rule", "stand-in")
    assert tp.ask_rules(STAND_IN) == {"stand-in-rule"}


# ── the gate ─────────────────────────────────────────────────────────────────

class _Exec:
    key = "run_command"

    def __init__(self):
        self.ran: list[dict] = []

    async def execute(self, args):
        self.ran.append({"offline": terminal_exec.OFFLINE.get(), "outside": terminal_exec.OUTSIDE_SANDBOX.get()})
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "sandbox": "workspace"}


def _cards(asked: list, answer: bool = False):
    async def cards(command, argv, **kw):
        asked.append(kw)
        return answer
    return cards


async def _gate(monkeypatch, args, cards, *, sandbox_on=True, available=True, ask_all=False, home=False, grant=None,
                asker=None):
    ex = _Exec()
    monkeypatch.setitem(tool_loop.EXECUTORS, "run_command", ex)

    async def answer(value):
        return value
    monkeypatch.setattr(command_gate, "_sandbox_enabled", lambda: answer(sandbox_on))
    monkeypatch.setattr(command_gate, "_asks_for_everything", lambda: answer(ask_all))
    if home is not None:              # None: the real check, on the working folder the test set
        monkeypatch.setattr(command_gate, "_work_folder_holds_home", lambda: answer(home), raising=False)
    monkeypatch.setattr(command_gate, "_outside_grant", lambda conversation_id, command: answer(grant))
    monkeypatch.setattr(command_sandbox, "available", lambda: available)

    async def resolve():
        return [{"key": "run_command", "description": "run"}]
    trace: list = []
    turn = untrusted.track_turn()                          # a turn that has read nothing from outside
    try:
        with run_trace.collecting() as steps, (permissions.asking_with(asker) if asker is not None
                                               else contextlib.nullcontext()):
            await tool_loop._run_tool("run_command", args, "{}", ToolTurn(resolve_tools=resolve, emit=lambda e: None,
                                      tool_timeout_s=5, tool_trace=trace, convo=[], confirm_command=cards,
                                      conversation_id="c1"))
    finally:
        untrusted.end_turn(turn)
    return ex, trace[-1]["result"], steps


async def test_an_unread_command_runs_offline_in_the_sandbox_with_no_card(unread, monkeypatch):
    asked: list = []
    ex, result, steps = await _gate(monkeypatch, {"command": STAND_IN}, _cards(asked, True))
    assert asked == [] and ex.ran == [{"offline": True, "outside": False}]
    assert result["offline_reason"] == tp.UNREADABLE
    note = result["network_note"]
    assert WHY in note and "network: true" in note and "offline" in note
    assert steps[-1]["offline"] == tp.UNREADABLE                     # SBX-8's count, on the run step's entry


async def test_an_understood_command_has_no_offline_mark(monkeypatch):
    _clear_reading()
    ex, result, steps = await _gate(monkeypatch, {"command": STAND_IN}, _cards([], True))
    assert ex.ran == [{"offline": False, "outside": False}]
    assert "offline_reason" not in result and "network_note" not in result and "offline" not in steps[-1]


@pytest.mark.parametrize("why_not", [
    {"sandbox_on": False}, {"available": False}, {"ask_all": True}, {"home": True}, {"grant": object()},
    {"network": True},
])
async def test_each_condition_false_gives_todays_card(unread, monkeypatch, why_not):
    """The sandbox off or unable to start, "ask for every command", home as the working folder, an outside grant, or
    the model's `network: true`: the ordinary command card, and on a no nothing runs."""
    asked: list = []
    args = {"command": STAND_IN, **({"network": True} if why_not.pop("network", False) else {})}
    ex, result, steps = await _gate(monkeypatch, args, _cards(asked, False), **why_not)
    assert len(asked) == 1 and asked[0].get("sandbox") != "outside"
    assert ex.ran == [] and result["ok"] is False
    assert "offline" not in steps[-1]


async def test_network_true_approved_runs_with_the_network(unread, monkeypatch):
    asked: list = []
    ex, result, steps = await _gate(monkeypatch, {"command": STAND_IN, "network": True}, _cards(asked, True))
    assert len(asked) == 1 and ex.ran == [{"offline": False, "outside": False}]
    assert "offline_reason" not in result and "offline" not in steps[-1]


async def test_after_outside_content_it_stays_offline_with_no_network_card(unread, monkeypatch):
    monkeypatch.setattr(command_gate, "_network_after_outside_content",
                        AsyncMock(side_effect=AssertionError("a network card for an offline command")))
    monkeypatch.setattr(untrusted, "external_seen", lambda: True)
    asked: list = []
    ex, result, _ = await _gate(monkeypatch, {"command": STAND_IN}, _cards(asked, True))
    assert asked == [] and ex.ran == [{"offline": True, "outside": False}]


async def test_a_background_job_with_no_card_callback_takes_the_offline_branch(unread, monkeypatch):
    ex, result, steps = await _gate(monkeypatch, {"command": STAND_IN}, None, asker=object())
    assert ex.ran == [{"offline": True, "outside": False}] and steps[-1]["offline"] == tp.UNREADABLE


async def test_with_no_card_callback_and_home_it_is_refused_not_run(unread, monkeypatch):
    monkeypatch.setattr(command_gate, "_unattended", AsyncMock(return_value="refused (stand-in)"))
    ex, result, _ = await _gate(monkeypatch, {"command": STAND_IN}, None, asker=object(), home=True)
    assert ex.ran == [] and result == {"ok": False, "error": "refused (stand-in)"}


async def test_forbid_is_unchanged(monkeypatch):
    monkeypatch.setattr(tp, "assess", lambda command, *, cwd=None, **_: tp.Assessment("forbid", "stand-in-rule", "stand-in"))
    asked: list = []
    ex, result, _ = await _gate(monkeypatch, {"command": STAND_IN}, _cards(asked, True))
    assert asked == [] and ex.ran == [] and "never runs" in result["error"]


async def test_a_named_rule_with_an_unread_command_still_gets_its_card(unread, monkeypatch):
    real = tp._layer_two
    monkeypatch.setattr(tp, "_layer_two", lambda texts, commands=(), *, text, cwd=None, **_: [("stand-in-rule", "stand-in")]
                        if any(t.startswith(STAND_IN) for t in texts) else real(texts, commands, text=text, cwd=cwd))
    asked: list = []
    ex, result, steps = await _gate(monkeypatch, {"command": STAND_IN}, _cards(asked, False))
    assert len(asked) == 1 and ex.ran == [] and "offline" not in steps[-1]


@pytest.mark.parametrize("rules, offline", [({tp.UNREADABLE, "stand-in-rule"}, False), ({tp.UNREADABLE}, True)])
async def test_only_unreadable_alone_takes_the_offline_branch(monkeypatch, rules, offline):
    """`unreadable` with another named rule gets the ordinary card, which lists both; `unreadable` alone runs offline.
    The card is the real one (command_confirm), its decision replaced, with every other offline condition true."""
    from server.services import command_confirm, settings_service
    first = "stand-in-rule" if len(rules) > 1 else tp.UNREADABLE
    monkeypatch.setattr(tp, "assess", lambda command, *, cwd=None, **_: tp.Assessment("ask", first, "stand-in"))
    monkeypatch.setattr(tp, "ask_rules", lambda command, **_: set(rules))

    async def risky(db):
        return "ask_risky"
    monkeypatch.setattr(settings_service, "shell_confirm_policy", risky)
    shown: list = []

    async def decide(request, context):
        shown.append(request)
        return permissions.Decision(False, "user", "once")
    monkeypatch.setattr(permissions, "decide", decide)
    ex, result, steps = await _gate(monkeypatch, {"command": STAND_IN}, command_confirm.Confirmations("c1").command)
    if offline:
        assert shown == [] and ex.ran == [{"offline": True, "outside": False}] and steps[-1]["offline"] == tp.UNREADABLE
    else:
        assert ex.ran == [] and result["ok"] is False and "offline" not in steps[-1]
        [card] = shown
        assert card.target == "rules:stand-in-rule|unreadable"
        assert card.frame["rules"] == ["stand-in-rule", tp.UNREADABLE]


# ── the home check, read on every call ───────────────────────────────────────

@pytest.mark.parametrize("folder, card", [(lambda: Path.home(), True), (lambda: Path.home() / STAND_IN, False)])
async def test_the_gate_reads_the_working_folder_on_every_call(unread, monkeypatch, folder, card):
    from server.services import settings_service
    reads: list = []

    async def workspace_dir(db):
        reads.append(1)
        return folder()
    monkeypatch.setattr(settings_service, "workspace_dir", workspace_dir)
    for _ in range(2):
        asked: list = []
        ex, _result, _steps = await _gate(monkeypatch, {"command": STAND_IN}, _cards(asked, False), home=None)
        assert (len(asked), len(ex.ran)) == ((1, 0) if card else (0, 1))
    assert len(reads) == 2

@pytest.mark.parametrize("folder, holds", [
    (lambda: Path.home(), True), (lambda: Path.home().parent, True), (lambda: Path("/"), True),
    (lambda: Path(str(Path.home()).upper()), True), (lambda: None, True),
    (lambda: Path.home() / STAND_IN, False), (lambda: Path("/") / STAND_IN, False),
])
async def test_the_working_folder_holds_home(monkeypatch, folder, holds):
    from server.db import session as db_session
    from server.services import settings_service

    @contextlib.asynccontextmanager
    async def session():
        yield None
    monkeypatch.setattr(db_session, "AsyncSessionLocal", session)
    reads: list = []

    async def workspace_dir(db):
        reads.append(1)
        return folder()
    monkeypatch.setattr(settings_service, "workspace_dir", workspace_dir)
    assert await command_gate._work_folder_holds_home() is holds
    assert await command_gate._work_folder_holds_home() is holds and len(reads) == 2      # read every call


async def test_a_working_folder_that_cannot_be_read_counts_as_home(monkeypatch):
    from server.db import session as db_session

    def broken():
        raise RuntimeError("stand-in")
    monkeypatch.setattr(db_session, "AsyncSessionLocal", broken)
    assert await command_gate._work_folder_holds_home() is True


# ── SBX-8's count ────────────────────────────────────────────────────────────

def test_the_offline_mark_reaches_the_run_step_of_its_own_tool():
    with run_trace.collecting():
        run_trace.note_offline(tp.UNREADABLE)
        run_trace.record(tool="run_command", args={}, ok=True, error=None, ms=5, result={"ok": True})
        run_trace.record(tool="run_command", args={}, ok=True, error=None, ms=5, result={"ok": True})
        steps = [{"kind": "tool_call", "ref": {"tool": "run_command"}, "detail": {}} for _ in range(2)]
        run_recorder.RunRecorder._merge_tool_trace(None, steps)
    assert steps[0]["ref"] == {"tool": "run_command", "ok": True, "offline": tp.UNREADABLE}
    assert steps[1]["ref"] == {"tool": "run_command", "ok": True}                 # one call's mark, not the next's


def test_the_plan_keeps_its_shape_with_a_default():
    assert command_gate.NOT_A_COMMAND.offline_reason == "" and command_gate.CommandPlan().network == {}

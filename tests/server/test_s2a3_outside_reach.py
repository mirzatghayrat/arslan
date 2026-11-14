"""S2a-3 step 5: `outside-reach`, for a command that runs outside the sandbox.

Outside the sandbox (a conversation's grant to leave it, the sandbox switched off or unable to start, an
`outside_sandbox` call) a program that hands its work to a macOS service acts past the command, so it asks, this time
only, where no named rule matched: open past open-app, at and batch, launchctl, shortcuts, networksetup and tccutil past
their read-only forms, security create- and unlock-. Inside the sandbox nothing changes: its profile refuses those
services. Benign forms only; the adversarial command shapes are Codex's (strict-xfail, its own file)."""
from __future__ import annotations

import pytest

from server.orchestrator import command_gate, tool_loop, untrusted
from server.orchestrator.turn_state import ToolTurn
from server.services import (approvals, command_confirm, command_sandbox, permission_store, permissions,
                             settings_service, terminal_exec, terminal_policy as tp)

STAND_IN = "zz-stand-in-word"
REACH = tp.OUTSIDE_REACH[0]

GAPS = [
    "open notes.txt",
    "at now",
    "batch",
    f"launchctl kickstart {STAND_IN}",
    f"shortcuts view {STAND_IN}",
    "networksetup -detectnewhardware",
    f"tccutil {STAND_IN}",
    f"security create-keychain {STAND_IN}",
    f"security unlock-keychain {STAND_IN}",
    # a later command of a chain, and an option no table knows (`_fully_accounted` sends that to the text matcher)
    f"echo {STAND_IN}; at now",
    f"ls && open {STAND_IN}.txt",
    f"at --{STAND_IN} now",
    f"open --{STAND_IN} notes.txt",
    # #798 review 2: the program word in upper and mixed case (the default macOS disk ignores case)
    "OPEN notes.txt", "Open notes.txt", "AT now", "At now", "BATCH", "Batch",
    f"LAUNCHCTL kickstart {STAND_IN}", f"LaunchCtl kickstart {STAND_IN}", f"SHORTCUTS view {STAND_IN}",
    f"Shortcuts view {STAND_IN}", "NETWORKSETUP -detectnewhardware", "NetworkSetup -detectnewhardware",
    f"TCCUTIL {STAND_IN}", f"TccUtil {STAND_IN}", f"SECURITY create-keychain {STAND_IN}",
    f"Security unlock-keychain {STAND_IN}",
    # #798 review: a help or version word with more after it, and a second networksetup option that is not a query
    f"launchctl help kickstart {STAND_IN}", f"shortcuts --help view {STAND_IN}", f"tccutil --help {STAND_IN}",
    "networksetup -getinfo -detectnewhardware",
]
READ_ONLY = ["launchctl list", "launchctl print system", "shortcuts list", "networksetup -listallnetworkservices",
             "networksetup -getinfo Wi-Fi", "at -l", "crontab -l", "tccutil --help", "security list-keychains",
             "launchctl", "shortcuts", "networksetup", "launchctl help", "networksetup -getinfo Wi-Fi -help",
             "LAUNCHCTL list", "Shortcuts list"]
NAMED = [(f"launchctl load {STAND_IN}.plist", "login-items"), (f"crontab {STAND_IN}", "login-items"),
         (f"shortcuts run {STAND_IN}", "shortcuts"), ("tccutil reset All", "system-settings"),
         ("networksetup -setairportpower en0 on", "system-settings"), ("open -a Terminal", "open-app"),
         (f"security add-generic-password -s {STAND_IN}", "keychain-write"), (f"killall {STAND_IN}", "force-kill")]
NOT_PROGRAMS = [STAND_IN, f"{STAND_IN} --{STAND_IN}", "cat at", "ls open", "cat batch", f"grep {STAND_IN} launchctl",
                f"echo security create-keychain {STAND_IN}"]


@pytest.mark.parametrize("command", GAPS)
def test_a_gap_asks_once_outside_and_runs_inside(command):
    assert tp.assess(command, outside=True) == tp.Assessment("ask", REACH, tp.OUTSIDE_REACH[1])
    assert tp.ask_rules(command, outside=True) == {REACH} and tp.risk_grade(command, outside=True) == "MEDIUM"
    assert tp.assess(command) == tp.Assessment("run") and tp.ask_rules(command) == set()
    assert tp.risk_grade(command) == "LOW"


def test_it_is_once_only_the_island_refuses_it_and_describe_gives_its_reason():
    assert REACH in tp.ONCE_ONLY_RULES and tp.describe(REACH) == tp.OUTSIDE_REACH[1]
    frame = {"type": "propose_run_command", "pretty": "open notes.txt", "perm_kind": "command"}
    assert approvals.island_may_answer(frame) is True                   # inside: no rule, the island may answer
    assert approvals.island_may_answer({**frame, "rules": [REACH]}) is False


@pytest.mark.parametrize("command", READ_ONLY)
def test_the_read_only_forms_run_even_outside(command):
    assert tp.assess(command, outside=True) == tp.Assessment("run")


@pytest.mark.parametrize("command, rule", NAMED)
def test_a_named_rule_keeps_its_name_outside(command, rule):
    assert tp.assess(command, outside=True) == tp.assess(command) and tp.assess(command).rule == rule
    assert tp.ask_rules(command, outside=True) == tp.ask_rules(command) and REACH not in tp.ask_rules(command, outside=True)


@pytest.mark.parametrize("command", NOT_PROGRAMS)
def test_a_stand_in_or_a_file_named_after_a_gap_runs_outside(command):
    assert tp.assess(command, outside=True) == tp.Assessment("run")


# ── the gate ─────────────────────────────────────────────────────────────────

class _Exec:
    key = "run_command"

    def __init__(self):
        self.ran: list[bool] = []

    async def execute(self, args):
        self.ran.append(terminal_exec.OUTSIDE_SANDBOX.get())
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "sandbox": "workspace"}


@pytest.fixture
def gate(monkeypatch):
    """The gate with its settings replaced, the real card ladder, and decide() recording the request and saying no."""
    shown: list = []

    def setup(*, enabled=True, available=True, grant=None, ask_all=False):
        async def answer(value):
            return value
        monkeypatch.setattr(command_gate, "_sandbox_enabled", lambda: answer(enabled))
        monkeypatch.setattr(command_gate, "_asks_for_everything", lambda: answer(ask_all))
        monkeypatch.setattr(command_gate, "_work_folder_holds_home", lambda: answer(False))
        monkeypatch.setattr(command_gate, "_outside_grant", lambda conversation_id, command: answer(grant))
        monkeypatch.setattr(command_sandbox, "available", lambda: available)
        monkeypatch.setattr(settings_service, "default_permission_mode",
                            lambda db: answer("ask" if ask_all else "ask_risky"))
        # As the real one: the setting off or seatbelt unable to start, or a grant (#798 review)
        monkeypatch.setattr(approvals, "runs_unsandboxed", lambda conversation_id=None: answer(
            not (enabled and available) or grant is not None))

        async def decide(request, context):
            shown.append(request)
            return permissions.Decision(False, "user", "once")
        monkeypatch.setattr(permissions, "decide", decide)
    return setup, shown


async def _dispatch(monkeypatch, args, cards):
    ex = _Exec()
    monkeypatch.setitem(tool_loop.EXECUTORS, "run_command", ex)

    async def resolve():
        return [{"key": "run_command", "description": "run"}]
    trace: list = []
    turn = untrusted.track_turn()
    try:
        await tool_loop._run_tool("run_command", args, "{}", ToolTurn(resolve_tools=resolve, emit=lambda e: None,
                                  tool_timeout_s=5, tool_trace=trace, convo=[], confirm_command=cards,
                                  conversation_id="c1"))
    finally:
        untrusted.end_turn(turn)
    return ex, trace[-1]["result"]


@pytest.mark.parametrize("ask_all", [False, True])
async def test_an_outside_grant_gives_a_once_only_card(gate, monkeypatch, ask_all):
    """ask_risky with a grant ran it with no card (layer ③ outside); "ask for every command" offered this conversation."""
    setup, shown = gate
    setup(grant=object(), ask_all=ask_all)
    ex, result = await _dispatch(monkeypatch, {"command": "open notes.txt"}, command_confirm.Confirmations("c1").command)
    [card] = shown
    assert ex.ran == [] and result["ok"] is False
    assert card.target == f"rules:{REACH}" and card.once_only and not card.conversation_ok
    assert card.frame["rules"] == [REACH] and approvals.island_may_answer(card.frame) is False
    # #798 review 1: it says where it runs, as main's outside card for the same command did
    assert card.title == "No sandbox · Open notes.txt" and card.frame["unsandboxed"] is True
    assert "outside the sandbox" in card.title_for_model


async def test_the_outside_sandbox_card_lists_it(gate, monkeypatch):
    setup, shown = gate
    setup()
    await _dispatch(monkeypatch, {"command": "open notes.txt", "outside_sandbox": True, "why": STAND_IN},
                    command_confirm.Confirmations("c1").command)
    [card] = shown
    assert card.kind == "outside" and card.frame["rules"] == [REACH]
    # its own mark, as on main: the frame says outside, and the title says so first
    assert card.title == f"Outside the sandbox · Open notes.txt · {STAND_IN}" and card.frame["sandbox"] == "outside"
    assert approvals.island_may_answer(card.frame) is False


@pytest.mark.parametrize("ask_all", [False, True])
@pytest.mark.parametrize("enabled, available", [(False, True), (True, False)], ids=["switched-off", "cannot-start"])
async def test_with_no_sandbox_to_run_in_the_card_reads_it_outside(gate, monkeypatch, enabled, available, ask_all):
    setup, shown = gate
    setup(enabled=enabled, available=available, ask_all=ask_all)
    ex, _result = await _dispatch(monkeypatch, {"command": "open notes.txt"}, command_confirm.Confirmations("c1").command)
    [card] = shown
    assert ex.ran == [] and card.target == f"rules:{REACH}" and card.once_only and not card.conversation_ok
    assert card.title == "No sandbox · Open notes.txt" and card.frame["unsandboxed"] is True
    assert approvals.island_may_answer(card.frame) is False


async def test_a_rules_card_inside_the_sandbox_has_no_outside_mark(gate, monkeypatch):
    """The mark comes from where it runs, not from the rule list: a named rule inside the sandbox stays unmarked."""
    setup, shown = gate
    setup()
    await _dispatch(monkeypatch, {"command": "open -a Terminal"}, command_confirm.Confirmations("c1").command)
    [card] = shown
    assert card.target == "rules:open-app" and "unsandboxed" not in card.frame
    assert not card.title.startswith("No sandbox")


async def test_inside_the_sandbox_no_card(gate, monkeypatch):
    setup, shown = gate
    setup()
    asked: list = []

    async def cards(command, argv, **kw):
        asked.append(kw)
        return True
    ex, result = await _dispatch(monkeypatch, {"command": "open notes.txt"}, cards)
    assert asked == [] and shown == [] and ex.ran == [False] and result["ok"] is True


async def test_unattended_it_is_refused_and_listed_in_the_inbox(execution_db, gate, monkeypatch):
    """No card callback and nobody to ask, with no sandbox to run in: refused, and the Inbox row is the card it
    would have been (the gate's own branch; a scheduled run is refused earlier, test_scheduled_run_no_command)."""
    permission_store._reset_for_tests()
    setup, _shown = gate
    setup(available=False)
    turn = ToolTurn(resolve_tools=None, emit=lambda e: None, tool_timeout_s=5, tool_trace=[], convo=[],
                    conversation_id="c1")
    result = await command_gate.check("run_command", {"command": "open notes.txt"}, turn)
    assert result["ok"] is False
    from server.db import session as db_session
    async with db_session.AsyncSessionLocal() as db:
        [row] = await permission_store.recent(db)
    assert (row.kind, row.target, row.decided_by, row.decision) == ("command", f"rules:{REACH}", "policy", "deny")


async def test_unattended_the_listed_card_says_where_it_runs(gate, monkeypatch):
    """#798 review 1: the card the Inbox lists is titled as the one a window would have shown."""
    setup, _shown = gate
    setup(enabled=False)
    listed: list = []

    async def refuse(request, context):
        listed.append(request)
        return "refused"
    monkeypatch.setattr(permissions, "refuse_unattended", refuse)
    turn = ToolTurn(resolve_tools=None, emit=lambda e: None, tool_timeout_s=5, tool_trace=[], convo=[],
                    conversation_id="c1")
    await command_gate.check("run_command", {"command": "open notes.txt"}, turn)
    [request] = listed
    assert request.target == f"rules:{REACH}" and request.title == "No sandbox · Open notes.txt"

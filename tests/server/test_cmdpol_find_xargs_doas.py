"""Command policy (v0.1.64): what a find -exec family or an xargs starts, and three readers (#376's leftovers).

- `find … -exec rm -rf /` and `xargs … rm -rf ~` are forbidden, as `rm -rf /` and `rm -rf ~` are: the wipe rules
  (wipe-root, wipe-home) read the command those two start. Before, the find forms read as `unreadable` and so ran
  offline in the sandbox with no card, and the xargs forms got a card; either wipes the writable work folder, sandbox
  or not. Refused through the gate in every context: the sandbox with no grant, no sandbox, and an outside grant.
- doas is read through like sudo, expect is a launcher, and git's `--exec-path=` names where git runs its programs
  from: under a grant to leave the sandbox each now gets a card that shows the whole command, where before it ran
  outside with no card.
"""
import pytest

from server.orchestrator import command_gate, untrusted
from server.orchestrator.turn_state import ToolTurn
from server.services import command_sandbox, shell_grammar
from server.services import terminal_policy as tp

WIPES = [
    pytest.param("find . -exec rm -rf / \\;", "wipe-root", id="find-exec-root"),
    pytest.param("find . -name x -exec rm -rf ~ \\;", "wipe-home", id="find-exec-home"),
    pytest.param("find . -execdir rm -rf / \\;", "wipe-root", id="find-execdir-root"),
    pytest.param("find . -type f -execdir rm -rf ~ \\;", "wipe-home", id="find-execdir-home"),
    pytest.param("find . -exec rm -rf / {} +", "wipe-root", id="find-exec-plus-root"),
    pytest.param("find . -exec rm -rf ~ {} +", "wipe-home", id="find-exec-plus-home"),
    pytest.param("find . -ok rm -rf / \\;", "wipe-root", id="find-ok-root"),
    pytest.param("find . -okdir rm -rf ~ \\;", "wipe-home", id="find-okdir-home"),
    pytest.param("find src -exec rm -r -f / \\;", "wipe-root", id="find-exec-split-flags"),
    pytest.param("find . -exec 'rm' -rf / \\;", "wipe-root", id="find-exec-quoted-rm"),
    pytest.param("find . -exec rm -rf \"$HOME\" \\;", "wipe-home", id="find-exec-quoted-home"),
    pytest.param("find . -exec echo {} \\; -exec rm -rf ~ \\;", "wipe-home", id="find-second-exec"),
    pytest.param("ls && find . -exec rm -rf $HOME \\;", "wipe-home", id="find-after-and"),
    pytest.param("echo a | xargs rm -rf /", "wipe-root", id="xargs-root"),
    pytest.param("echo a | xargs rm -rf ~", "wipe-home", id="xargs-home"),
    pytest.param("echo a | xargs -I{} rm -rf /", "wipe-root", id="xargs-I-root"),
    pytest.param("echo a | xargs -I{} rm -rf ~", "wipe-home", id="xargs-I-home"),
    pytest.param("echo a | xargs -I {} rm -rf ~", "wipe-home", id="xargs-I-spaced-home"),
    pytest.param("find . -print0 | xargs -0 -n1 rm -rf /", "wipe-root", id="xargs-options-root"),
    pytest.param("echo a | xargs \"rm\" -rf ~", "wipe-home", id="xargs-quoted-rm"),
    pytest.param("sh -c 'echo a | xargs rm -rf ~'", "wipe-home", id="xargs-in-sh-c"),
]

# Main's verdict for each, which this change keeps: none is a wipe of / or ~.
KEPT = [
    pytest.param("find . -exec rm -rf ~/x \\;", "ask", id="find-a-folder-in-home"),
    pytest.param("find . -name '*.pyc' -exec rm {} \\;", "ask", id="find-placeholder"),
    pytest.param("find . -exec echo rm -rf / \\;", "ask", id="find-echo-payload"),
    pytest.param("find / -name x", "run", id="find-reads-root"),
    pytest.param("find . -exec /bin/rm -rf / \\;", "ask", id="find-rm-by-path"),     # as `/bin/rm -rf /` on main
    pytest.param("echo a | xargs rm -rf build", "ask", id="xargs-a-folder"),
    pytest.param("echo a | xargs -I{} rm -rf /{}", "ask", id="xargs-placeholder"),
    pytest.param("echo a | xargs echo rm -rf /", "ask", id="xargs-echo-payload"),
    pytest.param("echo 'find . -exec rm -rf / ;'", "run", id="quoted-prose"),
    pytest.param("grep -n 'xargs rm -rf ~' notes.md", "run", id="grep-prose"),
]


@pytest.mark.parametrize("outside", [False, True], ids=["inside", "outside"])
@pytest.mark.parametrize("command,rule", WIPES)
def test_a_wipe_that_find_or_xargs_starts_is_forbidden(command, rule, outside):
    assert tp.assess(command, outside=outside) == tp.assess("rm -rf " + ("/" if rule == "wipe-root" else "~"))


@pytest.mark.parametrize("outside", [False, True], ids=["inside", "outside"])
@pytest.mark.parametrize("command,level", KEPT)
def test_what_find_or_xargs_starts_is_forbidden_only_when_it_wipes(command, level, outside):
    assert tp.assess(command, outside=outside).level == level


# ── through the gate ─────────────────────────────────────────────────────────

CONTEXTS = {
    "sandbox-no-grant": {"sandbox": True, "grant": False},
    "no-sandbox-no-grant": {"sandbox": False, "grant": False},
    "outside-grant": {"sandbox": True, "grant": True},
}


def _gate(monkeypatch, *, sandbox: bool, grant: bool):
    async def answer(value):
        return value

    async def outside_grant(*_args):
        return object() if grant else None
    monkeypatch.setattr(command_gate, "_sandbox_enabled", lambda: answer(sandbox))
    monkeypatch.setattr(command_gate, "_asks_for_everything", lambda: answer(False))
    monkeypatch.setattr(command_gate, "_work_folder_holds_home", lambda: answer(False))
    monkeypatch.setattr(command_gate, "_outside_grant", outside_grant)
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    monkeypatch.setattr(untrusted, "external_seen", lambda: False)


async def _check(command):
    cards = []

    async def card(command, argv, **kw):
        cards.append((command, kw))
        return False                      # declined: nothing runs
    turn = ToolTurn(resolve_tools=None, emit=lambda _f: None, tool_timeout_s=5, tool_trace=[], convo=[],
                    confirm_command=card, conversation_id="c1")
    return await command_gate.check("run_command", {"command": command}, turn), cards


@pytest.mark.parametrize("context", list(CONTEXTS))
@pytest.mark.parametrize("command,rule", WIPES)
async def test_the_gate_refuses_it_before_any_card_in_every_context(command, rule, context, monkeypatch):
    _gate(monkeypatch, **CONTEXTS[context])
    result, cards = await _check(command)
    assert isinstance(result, dict) and result["error"].startswith("Arslan never runs this"), result
    assert cards == []


# ── doas, expect and git --exec-path ─────────────────────────────────────────

def test_doas_is_read_through_like_sudo():
    assert shell_grammar.read("doas ls -la").commands == (("doas", "ls", "-la"), ("ls", "-la"))
    assert shell_grammar.read("sudo ls -la").commands == (("sudo", "ls", "-la"), ("ls", "-la"))


@pytest.mark.parametrize("outside", [False, True], ids=["inside", "outside"])
@pytest.mark.parametrize("wrapper", ["doas", "sudo"])
def test_doas_rm_rf_root_is_forbidden_like_sudo(wrapper, outside):
    assert tp.assess(f"{wrapper} rm -rf /", outside=outside).level == "forbid"


@pytest.mark.parametrize("context", list(CONTEXTS))
async def test_the_gate_refuses_doas_rm_rf_root(context, monkeypatch):
    _gate(monkeypatch, **CONTEXTS[context])
    result, cards = await _check("doas rm -rf /")
    assert isinstance(result, dict) and result["error"].startswith("Arslan never runs this"), result
    assert cards == []


# #376's forms that hid the command doas or expect starts: not understood now, so a card under a grant.
UNREAD = [
    pytest.param("doas -s", "a wrapper's option", id="doas-shell"),
    pytest.param("doas -u build python3 -c 'print(1)'", "a wrapper's option", id="doas-user-interpreter"),
    pytest.param("doas -u build $TOOL", "a wrapper's option", id="doas-user-expansion"),
    pytest.param("expect -c 'spawn ls'", "`expect` takes a program of its own", id="expect-c"),
    pytest.param("echo x | expect", "`expect` takes a program of its own", id="expect-stdin"),
]


@pytest.mark.parametrize("command,why", UNREAD)
def test_doas_options_and_expect_are_not_understood(command, why):
    reading = shell_grammar.read(command)
    assert not reading.understood and why in reading.why, reading
    assert tp.ask_rules(command, outside=True) == {tp.UNREADABLE}


def test_git_exec_path_names_where_git_runs_its_programs_from():
    exec_path = tp.RUN_LATER_SETTING + "--exec-path"
    assert tp.run_later_targets("git --exec-path=./bin status") == [exec_path]
    assert tp.run_later_targets("git --exec-path=/tmp/x -c core.pager=less log") == [
        exec_path, tp.RUN_LATER_SETTING + "core.pager"]
    assert tp.run_later_targets("git --exec-path") == []          # with no value it prints the path and stops
    assert tp.run_later_targets("git status") == []


CARDED = [*UNREAD, pytest.param("git --exec-path=./bin status", "", id="git-exec-path")]


@pytest.mark.parametrize("command,_why", CARDED)
async def test_under_an_outside_grant_the_card_shows_the_whole_command(command, _why, monkeypatch):
    """Before, each ran outside the sandbox with no card under the grant (`outside-no-card`)."""
    _gate(monkeypatch, **CONTEXTS["outside-grant"])
    result, cards = await _check(command)
    assert [c for c, _ in cards] == [command], (result, cards)
    if command.startswith("git"):
        assert cards[0][1]["run_later"] == (tp.RUN_LATER_SETTING + "--exec-path",)

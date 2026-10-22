"""S2a-3 b (the user's decision, 2026-10-22): two tiers for programs the sandbox cannot contain.

They ask macOS to act for them outside the sandbox (launchd runs a job, LaunchServices opens an app, Shortcuts
runs a shortcut, the at daemon runs a command later), which the sandbox does not stop. The distinctive names ask
wherever they appear in the text, and wherever the reader found them as a command; the common words (open, at,
batch) ask only where the reader found a command, since anything it cannot read asks already. A command that
matches a named rule keeps that name.
"""
from __future__ import annotations

import pytest

from server.db import session as db_session
from server.orchestrator import tool_loop
from server.services import approvals, permission_store, terminal_policy as tp

RULE = tp.OUTSIDE_REACH[0]


@pytest.fixture(autouse=True)
def _fresh_cache():
    with tp._cache_lock:
        tp._cache.clear()
    yield


@pytest.mark.parametrize("name", sorted(tp._OUTSIDE_NAMES))
@pytest.mark.parametrize("form", ["{name} --help", "/usr/bin/{name} --help", "echo {name}", "grep -r {name} .",
                                  "ls && {name} --help", "nohup {name} --help"])
def test_a_distinctive_name_asks_wherever_it_appears(name, form):
    verdict = tp.assess(form.format(name=name))
    assert verdict.level == "ask", verdict
    assert RULE in tp.ask_rules(form.format(name=name)) or verdict.rule in tp.ONCE_ONLY_RULES


@pytest.mark.parametrize("command", ["l'aunch'ctl list", 'l"aunch"ctl list', "launch\\ctl list"])
def test_quoting_a_name_does_not_hide_it(command):
    assert tp.assess(command) == tp.Assessment("ask", RULE, tp.OUTSIDE_REACH[1])


@pytest.mark.parametrize("command", ["security add-generic-password -a x -s y", "security delete-certificate -c x",
                                     "security import cert.p12", "security set-keychain-settings",
                                     "security create-keychain k", "security unlock-keychain"])
def test_security_s_write_subcommands_ask(command):
    assert tp.assess(command).level == "ask"


@pytest.mark.parametrize("command", ["cat shortcuts.txt", "tail -n 5 osascript.log", "ls launchctl.plist.bak",
                                     "security find-certificate -a", "security list-keychains"])
def test_a_file_named_after_one_or_a_read_of_security_does_not(command):
    assert tp.assess(command).level == "run"


@pytest.mark.parametrize("command", ["open report.pdf", "open -a Preview x.pdf", "open .", "at now", "batch",
                                     "nohup open x.pdf", "ls && open x.pdf", "command open x.pdf",
                                     "find . -name '*.pdf' -exec open {} \\;", "/usr/bin/open x.pdf"])
def test_a_common_word_asks_where_the_reader_found_a_command(command):
    verdict = tp.assess(command)
    assert verdict.level == "ask" and RULE in tp.ask_rules(command) | {verdict.rule}


@pytest.mark.parametrize("command", ["echo open the door", "ls open", "cat at.txt", "grep batch log.txt",
                                     "git log --format=open", "echo 'meet at noon'", "python3 open.py"])
def test_the_same_words_as_arguments_run(command):
    assert tp.assess(command).level == "run"


@pytest.mark.parametrize("command,rule", [
    ("osascript -e 'display notification \"x\"'", "apple-events"),
    ("shortcuts run Morning", "shortcuts"),
    ("killall Finder", "force-kill"),
    ("launchctl load ~/Library/LaunchAgents/x.plist", "login-items"),
    ("crontab jobs.txt", "login-items"),
    ("security add-generic-password -a x -s y", "keychain-write"),
    ("tccutil reset All", "system-settings"),
    ("open https://example.org", "open-app"),
])
def test_a_command_with_a_named_rule_keeps_its_name(command, rule):
    """U11 runs an approved plain osascript or Shortcut by its rule's name; the Inbox lists by name."""
    assert tp.assess(command).rule == rule


def test_it_asks_this_time_only_and_the_island_does_not_answer_it():
    assert RULE in tp.ONCE_ONLY_RULES
    assert RULE in approvals._island_risky_rules()
    assert tp.describe(RULE) == tp.OUTSIDE_REACH[1]
    frame = {"type": "propose_run_command", "call_id": "c", "pretty": "open report.pdf"}
    assert approvals.island_may_answer(frame) is False


async def test_with_nobody_to_ask_it_is_refused_and_listed_in_the_inbox(execution_db, monkeypatch, tmp_path):
    permission_store._reset_for_tests()
    monkeypatch.setenv("ARSLAN_DEFAULT_WORKSPACE", str(tmp_path / "Arslan"))

    async def tools():
        return [{"key": "run_command", "description": "run_command"}]
    out = await tool_loop._dispatch_tool("run_command", {"command": "open report.pdf"}, "", resolve_tools=tools,
                                         emit=lambda e: None, tool_timeout_s=5, tool_trace=[], convo=[],
                                         conversation_id="conv-u")
    async with db_session.AsyncSessionLocal() as db:
        [row] = await permission_store.recent(db)
    assert out["ok"] is False and "nobody to ask" in out["error"]
    assert row.target == f"rules:{RULE}" and permission_store.could_not_ask(row)

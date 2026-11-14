"""S2a-3 c (the user's decision, 2026-10-22): "run" has to be earned by reading the whole command.

server/services/shell_grammar.py models one grammar, a subset of bash 3.2, and a command is understood only
when all of it is in that grammar. terminal_policy asks before running anything else (`unreadable`, this
time only); with nobody to ask it is refused and listed in the Inbox. Reading happens off the event loop,
within a time limit, and a reading that takes too long counts as not understood. The cases here are grammar
features, written with harmless commands; how far the reader agrees with the real shell is S2a-3 d's test.
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from server.db import session as db_session
from server.orchestrator import tool_loop
from server.services import permission_store, shell_grammar, task_service, terminal_policy as tp


@pytest.fixture(autouse=True)
def _fresh_cache():
    with tp._cache_lock:
        tp._cache.clear()
    yield
    with tp._cache_lock:
        tp._cache.clear()


# ── the grammar ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("command,programs", [
    ("ls -la", ["ls"]),
    ("git status && git log -1 || echo none", ["git", "git", "echo"]),
    ("cd src; make -j4 & wait", ["cd", "make", "wait"]),
    ("! grep -q x f", ["grep"]),
    ("grep -r 'a b' src | sort | uniq -c > out.txt 2>&1", ["grep", "sort", "uniq"]),
    ('echo "$HOME/x ${USER} $1 $?" \'$not_expanded\'', ["echo"]),
    ("echo $(git rev-parse HEAD)", ["git", "echo"]),
    ("A=1 B='two words' make test", ["make"]),
    ("x=1", []),
    ("(cd build && cmake ..)", ["cd", "cmake"]),
    ("{ ls; pwd; } > list.txt", ["ls", "pwd"]),
    ("if [ -d out ]; then rm -r out/tmp; elif [ -f x ]; then :; else mkdir out; fi", ["[", "rm", "[", ":", "mkdir"]),
    ("for f in *.md docs/*.md; do wc -l \"$f\"; done", ["wc"]),
    ("while read -r line; do echo \"$line\"; done < list.txt", ["read", "echo"]),
    ("case \"$1\" in start|run) npm start;; *) echo usage;; esac", ["npm", "echo"]),
    ("cat > notes.md <<'EOF'\nquoted $body is data `here`\nEOF", ["cat"]),
    ("cat <<EOF\nhello $USER from $(hostname)\nEOF", ["hostname", "cat"]),
    ("tr a-z A-Z <<< \"$name\"", ["tr"]),
    ("ls \\\n  -la # a comment ; with words", ["ls"]),
    ("find . -name '*.pyc' -exec rm {} \\;", ["find", "rm"]),
    ("ls | xargs -n1 -I{} cp {} out/", ["ls", "xargs", "cp"]),
    ("sudo -u build make install", ["sudo", "make"]),
    ("env -i FOO=1 npm test", ["env", "npm"]),
    ("timeout 30 python3 run.py", ["timeout", "python3"]),
    ("nohup nice -n 5 make &", ["nohup", "nice", "make"]),
    ("npx -y prettier --check .", ["npx", "prettier"]),
    ("bash -lc 'make && make test'", ["bash", "make", "make"]),
    ("bash -euo pipefail -c 'ls'", ["bash", "ls"]),
    ("python3 tool.py --flag", ["python3"]),
    ("python3 -m pytest -q", ["python3"]),
    ("curl -s https://example.org/a.json | python3 -m json.tool", ["curl", "python3"]),
    ("zsh setup.zsh", ["zsh"]),
    ("set -euo pipefail; export NAME=x; unset NAME", ["set", "export", "unset"]),
    ("osascript -e 'display notification \"done\"'", ["osascript"]),
])
def test_what_the_grammar_models_is_understood_with_every_program_it_starts(command, programs):
    reading = shell_grammar.read(command)
    assert reading.understood, reading.why
    assert [c[0] for c in reading.commands] == programs


@pytest.mark.parametrize("command,why", [
    ("echo $'a'", "$'…'"),
    ('echo $"a"', "$'…'"),
    ("echo `date`", "backquotes"),
    ("echo $((1 + 2))", "arithmetic"),
    ("echo $[1 + 2]", "arithmetic"),
    ("((n++))", "arithmetic"),
    ("echo {a,b}", "brace expansion"),
    ("echo ${name:-x}", "operator"),
    ("diff <(ls a) <(ls b)", "process substitution"),
    ("greet() { echo hi; }", "function"),
    ("function greet { echo hi; }", "function"),
    ("[[ -f x ]] && cat x", "[["),
    ("eval ls", "eval"),
    ("source env.sh", "source"),
    (". env.sh", "`.`"),
    ("alias l=ls", "alias"),
    ("trap 'echo bye' EXIT", "trap"),
    ("shopt -s extglob", "shopt"),
    ("set -k", "set option"),
    ("$TOOL --version", "variable"),
    ("$(which python3) x.py", "variable"),
    ("/usr/bin/l? -la", "pattern"),
    ("PATH=/tmp/bin ls", "PATH"),
    ("export PAGER=less", "PAGER"),
    ("env -S 'ls -la'", "splits"),
    ("echo 'open", "quoting"),
    ("echo \"open", "quoting"),
    ("echo end\\", "backslash"),
    ("if true; then ls", "does not close"),
    ("cat <<EOF\nno end", "here-document"),
    ("echo a |& cat", "bash 4"),
    ("echo a &>> log", "bash 4"),
    ("x=$(case a in a) ls;; esac)", "case inside"),
    ("python3 -c 'print(1)'", "inline python3"),
    ("python3 - <<'PY'\nprint(1)\nPY", "inline python3"),
    ("echo 'print(1)' | python3", "inline python3"),
    ("node -e 'console.log(1)'", "inline node"),
    ("perl -ne 'print' f", "inline perl"),
    ("awk '{print $1}' f", "awk program"),
    ("zsh -c 'ls'", "zsh's own"),
    ("sh -c \"$CMD\"", "not written out"),
    ("echo ls | bash", "shell code"),
    ("bash -s < /dev/stdin", "input"),
    ("watch ls", "watch"),
    ("tmux new 'ls'", "tmux"),
    ("ls\x07", "control"),
    ("ls​ -la", "invisible"),
])
def test_anything_outside_it_is_not_understood_and_says_why(command, why):
    reading = shell_grammar.read(command)
    assert not reading.understood
    assert why in reading.why


def test_a_quoted_name_before_the_equals_sign_is_not_an_assignment():
    # bash runs a program called A=1; a program name with = in it is not one this reader reads (PR1b)
    reading = shell_grammar.read("'A'=1")
    assert not reading.understood and "program name" in reading.why
    assert shell_grammar.read("A=1").understood and shell_grammar.read("A=1").commands == ()


def test_the_reader_stops_at_its_caps():
    many = shell_grammar.read("ls\n" * (shell_grammar.MAX_COMMANDS + 1))
    assert not many.understood and many.capped
    assert shell_grammar.read("ls\n" * shell_grammar.MAX_COMMANDS).understood
    deep = "echo " + "$(echo " * (shell_grammar.MAX_DEPTH + 1) + "x" + ")" * (shell_grammar.MAX_DEPTH + 1)
    reading = shell_grammar.read(deep)
    assert not reading.understood and reading.capped


def test_reading_is_linear_in_the_text():
    def cost(n):
        text = "ls -la src | grep x && echo ok\n" * n
        best = float("inf")
        for _ in range(5):
            start = time.thread_time()
            shell_grammar.read(text)
            best = min(best, time.thread_time() - start)
        return best
    small, large = cost(60), cost(240)            # under MAX_COMMANDS: 3 commands a line
    assert large < 10 * max(small, 1e-9)          # linear reads ~4×; quadratic would read ~16×


# ── the policy ──────────────────────────────────────────────────────────────

def test_not_understood_asks_this_time_only():
    verdict = tp.assess("echo `date`")
    assert (verdict.level, verdict.rule) == ("ask", tp.UNREADABLE) and "backquotes" in verdict.reason
    assert tp.UNREADABLE in tp.ONCE_ONLY_RULES and tp.ask_rules("echo `date`") == {tp.UNREADABLE}


def test_a_named_rule_keeps_its_name_and_unreadable_joins_it():
    """The card says what it is (U11 runs an approved plain osascript by its rule's name); the target lists both."""
    command = "git push; echo `date`"
    assert tp.assess(command).rule == "git-push"
    assert tp.ask_rules(command) == {"git-push", tp.UNREADABLE}


def test_forbidden_stays_forbidden_however_it_is_written():
    assert tp.assess("rm -rf / `date`").level == "forbid"


def test_past_the_command_cap_the_detection_variants_are_not_built(monkeypatch):
    """②Main (#356): building them is quadratic in the number of commands; past the cap only the text as written
    and normalized is matched, and the command asks."""
    def never(_text):
        raise AssertionError("built the detection variants past the cap")
    monkeypatch.setattr(tp, "_detection_texts", never)
    verdict = tp.assess("ls\n" * (shell_grammar.MAX_COMMANDS + 1))
    assert (verdict.level, verdict.rule) == ("ask", tp.UNREADABLE)
    assert tp.assess("rm -rf /\n" + "ls\n" * shell_grammar.MAX_COMMANDS).level == "forbid"


def test_one_analysis_per_text(monkeypatch):
    calls = []
    real = tp._analyse
    monkeypatch.setattr(tp, "_analyse", lambda text: calls.append(text) or real(text))
    for _ in range(3):
        tp.assess("git push")
        tp.ask_rules("git push")
    assert calls == ["git push"]


async def test_reading_runs_off_the_event_loop():
    seen = []
    real = tp._analyse
    loop_thread = threading.get_ident()

    def recording(text):
        seen.append(threading.get_ident())
        return real(text)
    tp._analyse, saved = recording, tp._analyse
    try:
        assert (await tp.assess_async("ls")).level == "run"
    finally:
        tp._analyse = saved
    assert seen and seen[0] != loop_thread


async def test_a_reading_that_takes_too_long_asks_and_every_later_caller_agrees(monkeypatch):
    release = threading.Event()

    def slow(text):
        release.wait(5)
        return tp._Analysis(tp.Assessment("run"))
    monkeypatch.setattr(tp, "_analyse", slow)
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.005)
            ticks += 1
    task = asyncio.create_task(ticker())
    try:
        verdict = await tp.assess_async("ls -la", timeout_s=0.2)
    finally:
        task.cancel()
        release.set()
    assert verdict == tp.TIMED_OUT and verdict.rule == tp.UNREADABLE
    assert ticks >= 10                                       # the loop kept running while it was read
    await asyncio.sleep(0.05)                                # the reading finishes late: it changes nothing
    assert tp.assess("ls -la") == tp.TIMED_OUT and tp.ask_rules("ls -la") == {tp.UNREADABLE}


# ── unattended, and running with no sandbox at all ──────────────────────────

async def test_with_nobody_to_ask_it_is_refused_and_listed_in_the_inbox(execution_db, monkeypatch, tmp_path):
    permission_store._reset_for_tests()
    monkeypatch.setenv("ARSLAN_DEFAULT_WORKSPACE", str(tmp_path / "Arslan"))

    async def tools():
        return [{"key": "run_command", "description": "run_command"}]
    out = await tool_loop._dispatch_tool("run_command", {"command": "echo `date`"}, "", resolve_tools=tools,
                                         emit=lambda e: None, tool_timeout_s=5, tool_trace=[], convo=[],
                                         conversation_id="conv-u")
    async with db_session.AsyncSessionLocal() as db:
        [row] = await permission_store.recent(db)
    assert out["ok"] is False and "nobody to ask" in out["error"]
    assert row.kind == "command" and row.target == "rules:unreadable" and permission_store.could_not_ask(row)


def test_only_text_that_is_read_whole_may_run_with_no_sandbox(monkeypatch):
    command = "osascript -e 'tell application \"Reminders\" to count windows'"
    assert task_service.unwrapped_once(command) is True
    monkeypatch.setattr(shell_grammar, "read", lambda text: shell_grammar.Reading(understood=False, why="x"))
    assert task_service.unwrapped_once(command) is False

"""S2a-3 c: what the reader understands of a command's text. server/services/shell_grammar.py models one grammar, a
subset of bash 3.2, and a command is understood only when all of it is in that grammar. The cases here are grammar
features, written with harmless commands; how far the reader agrees with the real shell is S2a-3 d's test.
"""
from __future__ import annotations

import inspect
import sys
import time

import pytest

from server.services import shell_grammar


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


def test_a_quoted_name_before_the_equals_sign_is_a_program_not_an_assignment():
    assert shell_grammar.read("'A'=1").commands == (("A=1",),)       # bash runs a program called A=1
    assert shell_grammar.read("A=1").commands == ()


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


def test_nesting_past_the_cap_is_not_understood():
    reading = shell_grammar.read("$(x " * 1000)
    assert not reading.understood and reading.capped


def test_running_out_of_stack_is_not_understood():
    """A turn's dispatch is already some frames deep when it reads a command, so even a nesting under the cap can run out."""
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(len(inspect.stack()) + 12)
    try:
        reading = shell_grammar.read("echo $(echo $(echo $(echo x)))")
    finally:
        sys.setrecursionlimit(limit)
    assert not reading.understood and reading.capped


@pytest.mark.parametrize("command", ["echo a )", "echo a ) ; ls", "echo a }", "echo a ; fi", "echo a ; done"])
def test_text_left_over_after_the_commands_is_not_understood(command):
    assert not shell_grammar.read(command).understood

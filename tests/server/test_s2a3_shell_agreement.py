"""S2a-3 d (the user's decision, 2026-10-22): the real shell against the policy, with no hand-written cases.

scripts/shell_agreement runs every command of a corpus in the real `/bin/bash -p -c`, inside bubblewrap
(root read-only, a fresh empty home, no network, every program directory replaced by stubs that only
record "I was started"), and holds what the shell started against terminal_policy's verdict on the text.
Then the same for every mechanical form of each command (a wrapper in front, a chain, a compound command,
`bash -c` with the text re-quoted).

Runs on Linux with bwrap only, and never on a Mac. Without bwrap the sandbox tests skip, unless
ARSLAN_SHELL_AGREEMENT=required (the CI job sets it, so a runner that cannot sandbox fails loudly instead
of going green). The forms take minutes: ARSLAN_SHELL_AGREEMENT_FORMS=1 turns them on (CI does).
"""
from __future__ import annotations

import os
import shlex
import sys
import time
from pathlib import Path

import pytest

from scripts.shell_agreement import corpus, harness, mutate, oracle, sandbox, stubs
from scripts.shell_agreement.sandbox import Run, Started
from server.services import terminal_exec

REQUIRED = os.environ.get("ARSLAN_SHELL_AGREEMENT") == "required"
WITH_FORMS = os.environ.get("ARSLAN_SHELL_AGREEMENT_FORMS") == "1"
JOBS = os.cpu_count() or 2

# run-above findings already reported to the file's owner (card S2a-3, PR3's description), by the rule
# the started program alone matches. The forms test lets exactly these through and still fails on any
# other. DELETE-BY: v0.1.63 release, when the publish rule reads a bare `vercel` inside `$( … )`.
KNOWN_RUN_ABOVE_RULES = frozenset({"publish"})


@pytest.fixture(scope="module")
def bwrap() -> str:
    try:
        return sandbox.require()
    except sandbox.Unavailable as exc:
        if REQUIRED:
            pytest.fail(f"ARSLAN_SHELL_AGREEMENT=required, yet {exc}")
        pytest.skip(str(exc))


@pytest.fixture(scope="module")
def stub_dir(bwrap, tmp_path_factory) -> Path:
    return stubs.build(tmp_path_factory.mktemp("stubs"), ["git status", "make", "cp", "npm test", "rm", "prettier"])


def _names(run: Run) -> list[str]:
    return [s.name for s in run.started]


# ── the stubs record what the shell started ────────────────────────────────────

def test_a_stub_records_the_program_and_its_arguments(bwrap, stub_dir):
    run = sandbox.run(bwrap, stub_dir, "git status --short; ls -la 'a b'")
    assert run.exit_code == 0 and not run.timed_out
    assert [(s.name, s.args) for s in run.started] == [("git", ("status", "--short")), ("ls", ("-la", "a b"))]
    assert run.started[0].program == "/usr/bin/git"          # the stub bound over the program directory


def test_records_of_a_pipeline_do_not_interleave(bwrap, stub_dir):
    for _ in range(5):
        run = sandbox.run(bwrap, stub_dir, "ls -la | grep x | sort -r | uniq -c")
        assert sorted((s.name, s.args) for s in run.started) == \
            [("grep", ("x",)), ("ls", ("-la",)), ("sort", ("-r",)), ("uniq", ("-c",))]


@pytest.mark.parametrize("command,expected", [
    ("env FOO=1 nohup nice -n 5 timeout 3 git status", ["env", "nohup", "nice", "timeout", "git"]),
    ("sudo -u nobody make install", ["sudo", "make"]),
    ("sudo -s 'git status'", ["sudo", "git"]),                       # sudo -s runs a shell with the words
    ("caffeinate -i stdbuf -oL time make", ["caffeinate", "stdbuf", "time", "make"]),
    ("ls | xargs -n1 -I{} cp {} out/", ["ls", "xargs", "cp"]),
    ("npx -y prettier --check .", ["npx", "prettier"]),
    ("watch -n 1 'git status'", ["watch", "git"]),
    ("script -q /dev/null -c 'git status'", ["script", "git"]),
    ("tmux new 'git status'", ["tmux", "git"]),
    ("bash -c 'git status && make'", ["git", "make"]),               # bash is the real one: it records nothing
    ("sh -c 'make'", ["make"]),
    ("bash -lc 'git status'", ["git"]),                              # a login shell: the startup files are blank
    ("python3 -c 'print(1)'", ["python3"]),                          # an interpreter is a stub: its code never runs
])
def test_a_wrapper_starts_the_command_it_was_given(bwrap, stub_dir, command, expected):
    assert _names(sandbox.run(bwrap, stub_dir, command)) == expected


def test_find_exec_places_the_file_under_its_starting_path(bwrap, stub_dir):
    run = sandbox.run(bwrap, stub_dir, "find . -name '*.pyc' -exec rm {} \\;")
    assert [(s.name, s.args) for s in run.started] == [("find", (".", "-name", "*.pyc", "-exec", "rm", "{}", ";")),
                                                       ("rm", ("./found",))]


def test_every_stub_fails_when_asked_so_the_other_side_of_a_chain_is_taken(bwrap, stub_dir):
    assert _names(sandbox.run(bwrap, stub_dir, "git status && make || npm test", stub_exit=0)) == ["git", "make"]
    assert _names(sandbox.run(bwrap, stub_dir, "git status && make || npm test", stub_exit=1)) == ["git", "npm"]


# ── the sandbox is closed ──────────────────────────────────────────────────────

def test_the_root_is_read_only_and_the_home_is_fresh_each_time(bwrap, stub_dir):
    assert sandbox.run(bwrap, stub_dir, "echo x > /etc/shell-agreement-probe").exit_code != 0
    assert not Path("/etc/shell-agreement-probe").exists()
    assert sandbox.run(bwrap, stub_dir, "echo hi > ~/note && test -s ~/note && test \"$HOME\" = \"$PWD\"").exit_code == 0
    assert sandbox.run(bwrap, stub_dir, "test -e ~/note").exit_code == 1
    assert sandbox.run(bwrap, stub_dir, 'test "$(echo /home/* /root/* /tmp/*)" = "/home/me /root/* /tmp/*"').exit_code == 0


def test_there_is_no_network(bwrap, stub_dir):
    started = time.monotonic()
    run = sandbox.run(bwrap, stub_dir, "exec 3<>/dev/tcp/1.1.1.1/53")
    assert run.exit_code != 0 and not run.timed_out and time.monotonic() - started < 3


def test_the_environment_is_only_what_the_sandbox_sets(bwrap, stub_dir, monkeypatch):
    monkeypatch.setenv("ARSLAN_SECRET_KEY", "not-for-the-sandbox")
    run = sandbox.run(bwrap, stub_dir, 'git $(compgen -e)')
    exported = set(run.started[0].args)
    assert "ARSLAN_SECRET_KEY" not in exported
    assert exported <= {"PATH", "HOME", "TMPDIR", "TERM", "ARSLAN_TRACE", "ARSLAN_STUB_EXIT", "PWD", "SHLVL", "OLDPWD", "_"}


def test_a_command_that_never_ends_is_stopped(bwrap, stub_dir):
    started = time.monotonic()
    run = sandbox.run(bwrap, stub_dir, "while true; do :; done", timeout_s=0.5)
    assert run.timed_out and time.monotonic() - started < 5


def test_it_is_the_product_s_shell_and_never_runs_on_a_mac(monkeypatch, tmp_path):
    argv = sandbox.bwrap_argv("bwrap", tmp_path, tmp_path, tmp_path, stub_exit=0, command="ls")
    assert argv[-4:] == [*terminal_exec._shell(), "-c", "ls"]
    assert "--unshare-all" in argv and "--clearenv" in argv and ["--ro-bind", "/", "/"] == argv[1:4]
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(sandbox.Unavailable, match="never runs on a Mac"):
        sandbox.require()


def test_the_stub_directory_covers_the_corpus_and_the_host(tmp_path):
    folder = stubs.build(tmp_path / "stubs", ["my-tool --flag", "/usr/local/bin/other.sh x", "a/b"])
    assert (folder / "my-tool").is_symlink() and os.readlink(folder / "my-tool") == ".record"
    assert (folder / "other.sh").is_symlink() and not (folder / "a/b").exists()      # words, never paths
    assert os.readlink(folder / "xargs") == ".wrap" and os.readlink(folder / "osascript") == ".record"
    assert (folder / "bash").is_file() and not (folder / "bash").is_symlink() and (folder / "sh").is_file()
    assert {"ls", "env", "find"} <= {p.name for p in folder.iterdir()}


# ── the oracle ─────────────────────────────────────────────────────────────────

def test_the_oracle_flags_a_run_text_that_started_something_above_run():
    run = Run("ls", 0, [Started("/usr/bin/curl", ("-d", "@f", "https://x"))])
    kinds = {d.kind for d in oracle.judge(run)}
    assert kinds == {oracle.RUN_ABOVE, oracle.UNLISTED}


def test_the_oracle_flags_an_ask_text_that_started_something_forbidden():
    run = Run("eval 'ls'", 0, [Started("/usr/bin/rm", ("-rf", "/"))])
    [found] = oracle.judge(run)
    assert found.kind == oracle.ASK_ABOVE and found.verdict == "ask:unreadable" and found.started == "rm -rf /"


def test_the_oracle_flags_a_program_the_reader_did_not_list():
    [found] = oracle.judge(Run("ls -la", 0, [Started("/usr/bin/ls", ("-la",)), Started("/usr/bin/rm", ("x",))]))
    assert found.kind == oracle.UNLISTED and found.started == "rm x"


def test_the_oracle_agrees_when_the_shell_started_what_the_reader_listed():
    assert oracle.judge(Run("ls -la && git status", 1, [Started("/usr/bin/ls", ("-la",))])) == []
    assert oracle.judge(Run("rm -rf /", 0, [Started("/usr/bin/rm", ("-rf", "/"))])) == []      # forbidden: not judged
    # the shell resolved the argv, so shell_text's grep-pattern heuristic on a bare `grep -e` is not held against it
    assert oracle.own_level("grep -e") == ("run", "") and oracle.own_level("python3 -c x")[0] == "ask"
    assert oracle.judge(Run("grep -e 2>&1", 0, [Started("/usr/bin/grep", ("-e",))])) == []


# ── the forms and the corpus ───────────────────────────────────────────────────

def test_every_form_keeps_the_command_and_a_shell_carrier_round_trips():
    forms = dict(mutate.forms("ls -la 'a b'"))
    assert len(forms) == len(mutate.PREFIXES) + len(mutate.STRUCTURES) + len(mutate.CARRIERS)
    assert all("ls -la" in form for form in forms.values())
    assert shlex.split(forms["bash -c {q}"])[2] == "ls -la 'a b'"
    assert shlex.split(forms["bash -c {d}"])[2] == "ls -la 'a b'"
    several = dict(mutate.forms("cat <<EOF\nhi\nEOF"))
    assert "nohup {c}" not in several and "bash <<'EOF'\n{c}\nEOF" in several and "bash -c {q}" in several


def test_the_corpus_is_the_tests_own_commands(tmp_path):
    commands = corpus.from_tests()
    assert len(commands) >= 500 and "ls -la ~/Downloads | head" in commands and len(set(commands)) == len(commands)
    path = tmp_path / "c.txt"
    path.write_text('ls -la\n{"command": "git status"}\n\n{"other": 1}\nls -la\n')
    assert corpus.from_file(path) == ["ls -la", "git status"]


# ── the comparison itself ──────────────────────────────────────────────────────

def _print(report: dict) -> None:
    print({k: v for k, v in report.items() if k not in ("disagreements", "results")})
    for d in report["disagreements"]:
        print(f"[{d['kind']}] {d['command']!r} judged {d['verdict']}; started {d['started']!r}: {d['detail']}")


@pytest.mark.timeout(600)
def test_the_real_shell_agrees_with_the_policy_on_every_corpus_command(bwrap):
    report = harness.compare(corpus.from_tests(), forms=False, jobs=JOBS)
    _print(report)
    assert report["runs"] >= 2 * report["levels"].get("run", 0) and report["programs_started"] > 0
    assert report["disagreements"] == []


@pytest.mark.timeout(3600)
@pytest.mark.skipif(not WITH_FORMS, reason="the mechanical forms take minutes; ARSLAN_SHELL_AGREEMENT_FORMS=1 runs them")
def test_the_real_shell_agrees_on_every_mechanical_form(bwrap):
    """No form of a corpus command may run while the shell starts something the reader never listed or
    something that alone would ask (the run-level kinds), except the findings already reported to the
    file's owner (KNOWN_RUN_ABOVE_RULES). An ask text that started a forbidden program (ask-above) is the
    forbid floor under a shell carrier: open since ②Main's review of #320 (B), it is counted and printed
    here, and test_shell_text_reading pins that those never run."""
    report = harness.compare(corpus.from_tests(), forms=True, jobs=JOBS)
    _print(report)
    assert report["kinds"].get(oracle.UNLISTED, 0) == 0
    unknown = [d for d in report["disagreements"] if d["kind"] == oracle.RUN_ABOVE
               and oracle.own_level(d["started"])[1] not in KNOWN_RUN_ABOVE_RULES]
    assert unknown == []
    assert all(d["verdict"].startswith("ask:") for d in report["disagreements"] if d["kind"] == oracle.ASK_ABOVE)

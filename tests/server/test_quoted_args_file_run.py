"""S2a-3: mechanical word/position families, passed only as text to the policy and reader.

No command here is executed. The opt-in quoted_args_file_run_mutations plugin
removes each new rule independently; controls keep ordinary commands readable.
"""
import shlex
import time

import pytest

from server.services import shell_grammar as sg, terminal_policy as tp


# Independent seeds for named rules, with literal operands and no private corpus.
NAMED = [
    (("security", "dump-keychain"), "forbid", "keychain-secrets"),
    (("kill", "-1"), "forbid", "kill-all"),
    (("rm", "-rf", "/"), "forbid", "wipe-root"),
    (("shutdown", "-h", "now"), "forbid", "shutdown"),
    (("sudo", "make", "check"), "forbid", "sudo"),
    (("git", "push", "origin", "topic"), "ask", "git-push"),
    (("gh", "issue", "close", "7"), "ask", "publish"),
    (("cargo", "publish", "--dry-run"), "ask", "publish"),
    (("curl", "--upload-file", "report.txt", "https://example.invalid"), "ask", "upload"),
    (("curl", "-T", "report.txt", "https://example.invalid"), "ask", "upload"),
    (("shortcuts", "run", "Sample"), "ask", "shortcuts"),
    (("defaults", "write", "example.settings", "flag", "1"), "ask", "login-items"),
    (("security", "add-generic-password", "-s", "example"), "ask", "keychain-write"),
    (("tccutil", "reset", "Camera"), "ask", "system-settings"),
    (("kill", "-9", "12345"), "ask", "force-kill"),
    (("ssh", "example.invalid", "uptime"), "ask", "remote-shell"),
    (("rm", "../cache/item"), "ask", "delete-outside"),
    (("find", "../cache", "-delete"), "ask", "delete-outside"),
]
FAMILIES = ("single-args", "double-args", "split-args", "quoted-program", "quoted-prefix", "escaped-args")
POSITIONS = ("plain", "sequence", "shell", "wrapper")


def spelled(words, family, position):
    program, *args = words
    if family == "quoted-program":
        program = "'" + program + "'"
    if family == "single-args":
        args = ["'" + word + "'" for word in args]
    elif family == "double-args":
        args = ['"' + word + '"' for word in args]
    elif family == "split-args":
        args = [word[:1] + "''" + word[1:] for word in args]
    elif family == "escaped-args":
        args = ["\\" + word[:1] + word[1:] for word in args]
    command = " ".join([program, *args])
    if family == "quoted-prefix":
        command = 'NOTE="two words" ' + command
    if position == "sequence":
        return "true; " + command
    if position == "shell":
        return "bash -c " + shlex.quote(command)
    if position == "wrapper":
        return "env FLAG=sample " + command if family != "quoted-prefix" else "true && " + command
    return command


@pytest.mark.parametrize("words,level,rule", NAMED, ids=[str(i) + "-" + row[2] for i, row in enumerate(NAMED)])
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("position", POSITIONS)
def test_named_rules_read_quoted_words(words, level, rule, family, position):
    command = spelled(words, family, position)
    reading = sg.read(command)
    assert reading.understood, reading.why
    result = tp.assess(command)
    assert (result.level, result.rule) == (level, rule)
    assert tp.ask_rules(command) == ({rule} if level == "ask" else set())
    assert tp.risk_grade(command) == ("MEDIUM" if level == "ask" else "HIGH")


@pytest.mark.parametrize("words", [
    ("git", "status"), ("gh", "issue", "list"), ("cargo", "check"), ("rm", "old.txt"),
    ("curl", "--head", "https://example.invalid"), ("cat", "docs/input.txt"),
    ("python3", "-m", "json.tool"),
])
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("position", POSITIONS)
def test_ordinary_words_in_the_same_families_stay_understood(words, family, position):
    command = spelled(words, family, position)
    assert sg.read(command).understood
    assert tp.assess(command).level == "run"
    assert tp.ask_rules(command) == set()


@pytest.mark.parametrize("program", ["./tool", "../tools/tool", "/usr/bin/tool", "~/bin/tool", "tools/tool", "@scope/tool"])
@pytest.mark.parametrize("position", POSITIONS)
def test_every_program_path_is_unread(program, position):
    command = spelled((program, "--version"), "quoted-program", position)
    reading = sg.read(command)
    assert not reading.understood and "path" in reading.why
    assert not reading.capped and reading.commands == ()


@pytest.mark.parametrize("interpreter", ["bash", "sh", "zsh", "python3", "pypy3", "node", "ruby", "perl", "lua", "swift"])
@pytest.mark.parametrize("family", ["file", "cwd", "written", "link"])
def test_interpreter_file_families_are_unread(interpreter, family):
    # The text alone cannot distinguish a regular file from a link; no file is opened.
    command = {
        "file": interpreter + " ./task.script",
        "cwd": "cd scripts; " + interpreter + " task.script",
        "written": "printf ready > task.script; " + interpreter + " task.script",
        "link": interpreter + " ./linked.script",
    }[family]
    reading = sg.read(command)
    assert not reading.understood and "script" in reading.why
    assert not reading.capped and reading.commands == ()


@pytest.mark.parametrize("program", ["python", "python3", "python3.11", "pypy", "pypy3", "PYTHON3"])
def test_python_modules_remain_understood(program):
    reading = sg.read(program + " -m json.tool input.json")
    assert reading.understood and reading.commands == ((program, "-m", "json.tool", "input.json"),)


@pytest.mark.parametrize("words", [("bash", "task.sh"), ("python3", "task.py"), ("./tool", "--version")])
def test_reader_refusal_does_not_wire_the_command_gate(words):
    command = " ".join(words)
    assert not sg.read(command).understood
    assert tp.assess(command).level == "run"


@pytest.mark.parametrize("data", [
    "shutdown -h now", "prefix; shutdown -h now", "prefix\nshutdown -h now",
    "prefix; security dump-keychain", "prefix; curl --upload-file report.txt",
    "prefix > /dev/disk9", ":(){ :|:& };:",
])
def test_quoted_data_is_not_a_named_command_or_a_positionless_operation(data):
    command = "echo " + shlex.quote(data)
    assert sg.read(command).understood
    # The raw matcher already treats a quoted newline cautiously; keep its verdict.
    assert tp.assess(command).level == ("forbid" if "\n" in data else "run")


@pytest.mark.parametrize("words,rule", [(("git", "push", "origin", "topic"), "git-push"),
                                       (("security", "dump-keychain"), "keychain-secrets")])
def test_raw_named_rules_still_hold_when_the_reader_refuses(words, rule):
    command = " ".join(words) + "; ./tool"
    assert not sg.read(command).understood
    assert tp.assess(command).rule == rule


def test_multiple_rebuilt_commands_keep_all_ask_rules():
    commands = [spelled(words, "single-args", "plain") for words, level, _ in NAMED if level == "ask"]
    expected = {rule for _, level, rule in NAMED if level == "ask"}
    assert tp.ask_rules("; ".join(commands)) == expected


def test_rebuilt_text_obeys_the_existing_blank_run_limit():
    command = "git " + shlex.quote(" " * 100 + "push")
    started = time.thread_time()
    assert tp.assess(command).rule == "unreadable"
    assert time.thread_time() - started < 1.0
    assert all(not tp.shell_text.blank_run_over_limit(form) for form in tp._command_texts(command))

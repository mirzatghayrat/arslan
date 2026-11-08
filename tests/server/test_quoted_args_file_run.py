"""S2a-3: mechanical word/position families, passed only as text to the policy and reader.

No command here is executed. The opt-in quoted_args_file_run_mutations plugin
removes each new rule independently; controls keep ordinary commands readable.
"""
import shlex
import time

import pytest

from server.services import shell_grammar as sg, terminal_policy as tp
from tests.server.test_quoted_command_word import SEPARATORS


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


# Fourteen seeds at six spellings and four positions reconstruct the 336-case
# option matrix. The first ten ids are the review's operation classes. The
# other four independently exercise the previously surviving tuple mutations.
OPTION_OPERATIONS = [
    ("security/global-verbose-dump", ("security", "-v", "dump-keychain"), "forbid", "keychain-secrets"),
    ("security/global-quiet-export", ("security", "-q", "export"), "forbid", "keychain-secrets"),
    ("security/global-verbose-password", ("security", "-v", "find-generic-password", "-w"), "forbid", "keychain-secrets"),
    ("curl/remote-name-upload", ("curl", "-O", "-T", "report.txt", "https://example.invalid"), "ask", "upload"),
    ("curl/remote-name-post", ("curl", "-O", "-X", "POST", "https://example.invalid"), "ask", "upload"),
    ("wget/span-hosts-post-file", ("wget", "-H", "--post-file", "report.txt", "https://example.invalid"), "ask", "upload"),
    ("gsutil/parallel-copy", ("gsutil", "-m", "cp", "report.txt", "gs://example-bucket/report.txt"), "ask", "upload"),
    ("gh/attached-method", ("gh", "api", "-XPOST", "repos/example/project/issues"), "ask", "publish"),
    ("gh/attached-field", ("gh", "api", "-ftitle=sample", "repos/example/project/issues"), "ask", "publish"),
    ("http/attached-raw", ("http", "--raw=sample", "https://example.invalid"), "ask", "upload"),
    ("tuple/security-password", ("security", "find-generic-password", "-s", "example", "-w"), "forbid", "keychain-secrets"),
    ("tuple/gsutil-upload", ("gsutil", "cp", "report.txt", "gs://example-bucket/report.txt"), "ask", "upload"),
    ("tuple/gh-api-method", ("gh", "api", "-X", "POST", "repos/example/project/issues"), "ask", "publish"),
    ("tuple/gh-api-field", ("gh", "api", "-F", "title=sample", "repos/example/project/issues"), "ask", "publish"),
]

# Nine independent shapes at seven separators: quoted option-looking data,
# revisions/messages with spaces, literal apostrophes and end-of-options data.
OPTION_NEGATIVES = [
    ("security/global-help", ("security", "-v", "help", "dump-keychain")),
    ("security/global-prompt", ("security", "-p", "dump-keychain", "help")),
    ("security/password-value", ("security", "-v", "find-generic-password", "-s", "-w")),
    ("curl/header-value", ("curl", "-H", "--upload-file", "https://example.invalid")),
    ("gh/header-value", ("gh", "api", "-H", "-XPOST", "repos/example/project")),
    ("http/output-value", ("http", "--output", "--raw=sample", "https://example.invalid")),
    ("git/spaced-revision", ("git", "show", "push notes.txt")),
    ("git/quoted-message", ("git", "commit", "-m", "publish sample's notes")),
    ("curl/end-options", ("curl", "--", "-Treport.txt")),
]


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


@pytest.mark.parametrize("name,words,level,rule", OPTION_OPERATIONS, ids=[row[0] for row in OPTION_OPERATIONS])
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("position", POSITIONS)
def test_valid_options_preserve_operations(name, words, level, rule, family, position):
    command = spelled(words, family, position)
    assert sg.read(command).understood
    assert (tp.assess(command).level, tp.assess(command).rule) == (level, rule)


@pytest.mark.parametrize("name,words", OPTION_NEGATIVES, ids=[row[0] for row in OPTION_NEGATIVES])
@pytest.mark.parametrize("position", SEPARATORS)
def test_option_values_remain_data(name, words, position):
    command = SEPARATORS[position] + operand_text(words)
    assert sg.read(command).understood
    # Main already asks for the HTTP client after a pipe or an or-list.
    expected = "ask" if name == "http/output-value" and position in {"pipe", "or"} else "run"
    assert tp.assess(command).level == expected


@pytest.mark.parametrize("words,level,rule", [
    (("curl", "-sSOTreport.txt", "https://example.invalid"), "ask", "upload"),
    (("curl", "-oreport.txt", "-XPOST", "https://example.invalid"), "ask", "upload"),
    (("wget", "-Oreport.txt", "--method=POST", "https://example.invalid"), "ask", "upload"),
    (("wget", "--header=sample", "-H", "--post-file=report.txt"), "ask", "upload"),
    (("security", "-vphello", "dump-keychain"), "forbid", "keychain-secrets"),
    (("security", "-p", "sample", "-q", "export"), "forbid", "keychain-secrets"),
    (("gsutil", "-o", "sample=value", "-m", "cp", "report.txt", "gs://example-bucket/report.txt"), "ask", "upload"),
    (("gcloud", "--project", "sample", "storage", "cp", "report.txt", "gs://example-bucket/report.txt"), "ask", "upload"),
    (("aws", "--profile=sample", "s3", "cp", "report.txt", "s3://example-bucket/report.txt"), "ask", "upload"),
    (("az", "--subscription", "sample", "storage", "blob", "upload"), "ask", "upload"),
    (("azcopy", "--output-type", "json", "copy", "report.txt", "https://example.invalid"), "ask", "upload"),
    (("rclone", "--config", "sample.conf", "copy", "report.txt", "remote:report.txt"), "ask", "upload"),
    (("s3cmd", "-c", "sample.conf", "put", "report.txt", "s3://example-bucket/report.txt"), "ask", "upload"),
    (("gh", "api", "-Ftitle=sample", "repos/example/project/issues"), "ask", "publish"),
    (("gh", "api", "--method=POST", "repos/example/project/issues"), "ask", "publish"),
    (("https", "--raw=sample", "https://example.invalid"), "ask", "upload"),
    (("xh", "--raw=sample", "https://example.invalid"), "ask", "upload"),
    (("xhs", "--raw", "sample", "https://example.invalid"), "ask", "upload"),
    (("curl", "-H--upload-file", "https://example.invalid"), "run", ""),
    # The independent raw matcher already asks for this quoted wget value.
    (("wget", "-O", "--post-file", "https://example.invalid"), "ask", "upload"),
    (("gsutil", "-o", "cp", "ls"), "run", ""),
    (("gh", "api", "-XGET", "repos/example/project"), "run", ""),
    (("gh", "api", "-H-ftitle=sample", "repos/example/project"), "run", ""),
    (("http", "--output=--raw=sample", "https://example.invalid"), "run", ""),
    (("security", "-h", "dump-keychain"), "run", ""),
])
def test_program_specific_option_arities(words, level, rule):
    command = operand_text(words)
    assert sg.read(command).understood
    result = tp.assess(command)
    assert result.level == level
    if rule:
        assert result.rule == rule


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
    assert tp._command_words(command) == (("git", " " * 100 + "push"),)


# Same-program operands, not echo-only controls. The first eight cover the
# review's changed operand classes; the remainder distinguish roles and words.
OPERANDS = [
    ("keychain-help", ("security", "help", "dump-keychain"), "run"),
    ("wipe-root-option-looking-file", ("rm", "-rf /", "local.txt"), "run"),
    ("wipe-root-local-file", ("rm", "/ local-file"), "ask"),
    ("wipe-home-local-file", ("rm", "~ local-file"), "ask"),
    ("macos-root-local-file", ("rm", "/System local-file"), "ask"),
    ("git-file-data", ("git", "show", "push notes.txt"), "run"),
    ("delete-local-file", ("rm", "local /file"), "run"),
    ("delete-quote-file", ("rm", "local'file"), "run"),
    ("keychain-option-value", ("security", "find-generic-password", "-s", "-w"), "run"),
    ("keychain-help-password", ("security", "help", "find-generic-password -w"), "run"),
    ("git-help", ("git", "help", "push"), "run"),
    ("git-revision", ("git", "show", "push"), "run"),
    ("git-option-value", ("git", "-c", "alias.note=push", "status"), "run"),
    ("delete-empty-file", ("rm", ""), "ask"),
    ("delete-spaced-file", ("rm", "two words"), "run"),
    ("delete-after-options", ("rm", "--", "-rf /"), "ask"),
    ("publish-help", ("cargo", "help", "publish"), "run"),
    ("upload-option-value", ("curl", "-H", "X-Note: --upload-file report.txt", "https://example.invalid"), "ask"),
    ("disk-revision-data", ("diskutil", "info", "eraseDisk"), "run"),
]


def operand_text(words):
    # Quote every argument, including simple words, to exercise the new pass.
    return words[0] + " " + " ".join("'" + w.replace("'", "'\"'\"'") + "'" for w in words[1:])


@pytest.mark.parametrize("name,words,level", OPERANDS, ids=["operand/" + row[0] for row in OPERANDS])
@pytest.mark.parametrize("position", SEPARATORS)
def test_same_program_operands_keep_their_roles(name, words, level, position):
    command = SEPARATORS[position] + operand_text(words)
    assert sg.read(command).understood
    assert tp.assess(command).level == level


REFUSED_TAILS = {"path": "./tool", "file": "python3 task.py",
                 "launcher": "watch status", "builtin": "alias sample=value"}
RANK = {"run": 0, "ask": 1, "forbid": 2}


@pytest.mark.parametrize("words,level,rule", NAMED, ids=[str(i) + "-" + row[2] for i, row in enumerate(NAMED)])
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("tail", REFUSED_TAILS)
def test_quoted_rules_hold_before_every_refused_tail(words, level, rule, family, position, tail):
    standalone = spelled(words, family, position)
    command = standalone + "; " + REFUSED_TAILS[tail]
    reading = sg.read(command)
    assert not reading.understood and reading.commands == () and reading.why
    assert RANK[tp.assess(command).level] >= RANK[tp.assess(standalone).level]
    assert RANK[tp.assess(command).level] >= RANK[level]


@pytest.mark.parametrize("words", [("swift", "build"), ("bun", "install"), ("deno", "info")])
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("position", POSITIONS)
def test_non_script_subcommands_stay_understood(words, family, position):
    command = spelled(words, family, position)
    assert sg.read(command).understood
    assert tp.assess(command).level == "run"


@pytest.mark.parametrize("command", ["swift build.swift", "bun install.js", "deno info.ts",
                                     "swift run task.swift", "bun run task.js", "deno run task.ts"])
def test_subcommand_exceptions_do_not_admit_script_files(command):
    reading = sg.read(command)
    assert not reading.understood and "script" in reading.why and reading.commands == ()


@pytest.mark.parametrize("tail", REFUSED_TAILS.values())
def test_prefix_reading_is_separate_from_complete_reading(tail):
    command = "git 'push'; " + tail
    prefix = sg.read_prefix(command)
    assert prefix.refused and prefix.why and ("git", "push") in prefix.commands
    assert not sg.read(command).understood and sg.read(command).commands == ()


def test_prefix_caps_still_bound_the_extra_policy_pass():
    command = "git 'push'; " + "true; " * sg.MAX_COMMANDS
    prefix = sg.read_prefix(command)
    assert prefix.refused and prefix.capped and len(prefix.commands) == sg.MAX_COMMANDS
    assert sg.read(command).commands == ()
    assert tp.assess(command).level == "ask"

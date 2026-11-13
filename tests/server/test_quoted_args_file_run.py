"""S2a-3: mechanical word/position families, passed only as text to the policy and reader.

No command here is executed. The opt-in quoted_args_file_run_mutations plugin
removes each new rule independently; controls keep ordinary commands readable.
"""
import shlex
import time

import pytest

from server.services import shell_grammar as sg, terminal_policy as tp
from tests.server.test_quoted_command_word import SEPARATORS
from tests.server.quoted_args_baseline_data import levels
from tests.server.quoted_args_option_profiles import (
    CORRECTIONS, SEEDS, program_controls, unknowns, render,
    vercel_directories, implicit_controls, implicit_negative_controls, cluster_controls, GLOBAL_DISPATCH_PROGRAMS, IMPLICIT_OPERATIONS,
    DEPLOY_PROGRAMS,
)


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
    if tp._dry_run(words[0], words[1:]):
        level, rule = "run", ""         # the seed is a dry run, which publishes nothing (#897 review, item 3)
    result = tp.assess(command)
    assert (result.level, result.rule) == (level, rule)
    assert tp.ask_rules(command) == ({rule} if level == "ask" else set())
    assert tp.risk_grade(command) == {"ask": "MEDIUM", "run": "LOW"}.get(level, "HIGH")


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
def test_reader_refusal_asks_as_unreadable(words):
    """S2a-3 step 3 wires the reader into the policy: a script run it refuses asks as `unreadable`, which runs
    offline in the sandbox with no card."""
    command = " ".join(words)
    assert not sg.read(command).understood
    verdict = tp.assess(command)
    assert (verdict.level, verdict.rule) == ("ask", tp.UNREADABLE)


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
    # Accepted cautious forbids at all seven positions: this dash-leading
    # cluster cannot be split, so it keeps 9be27b5f's verdict. Whitespace does
    # not make an option an operand: --exclude=a b and -d"foo bar" are real
    # attached-value options, protected by test_spaced_attached_options below.
    ("wipe-root-option-looking-file", ("rm", "-rf /", "local.txt"), "forbid"),
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


@pytest.mark.parametrize("words,option,value", [
    (("rsync", "--exclude=a b", "report.txt", "remote:report.txt"), "--exclude", "a b"),
    (("curl", "-dfoo bar", "https://example.invalid"), "-d", "foo bar"),
], ids=["rsync/spaced-exclude-assignment", "curl/spaced-attached-post-data"])
@pytest.mark.parametrize("position", SEPARATORS)
def test_spaced_attached_options(words, option, value, position):
    # Treating a dash-leading word as an operand merely because it contains
    # whitespace would discard these options, including curl's posting data.
    command = SEPARATORS[position] + operand_text(words)
    assert sg.read(command).understood
    assert tp._fully_accounted(words[0], words[1:])
    assert (option, value) in list(tp._options(words[1:], tp._OPTION_VALUES[words[0]]))
    assert tp.assess(command).level == "ask"


REFUSED_TAILS = {"path": "./tool", "file": "python3 task.py",
                 "launcher": "watch status", "builtin": "alias sample=value"}
RANK = {"run": 0, "ask": 1, "forbid": 2}


@pytest.mark.parametrize("case,words", list(program_controls()), ids=lambda value: value if isinstance(value, str) else None)
def test_every_program_option_controls(case, words):
    command = render(words, "single", "plain")
    sg.read(command)
    assert tp._fully_accounted(words[0], words[1:]), case
    main, original = levels("controls", case, command)
    assert RANK[tp.assess(command).level] >= max(RANK[main], RANK[original]), case


@pytest.mark.parametrize("case,words", list(unknowns()), ids=lambda value: value if isinstance(value, str) else None)
def test_unknown_options_use_original_verdict(case, words):
    command = render(words, "single", "plain")
    sg.read(command)
    assert not tp._fully_accounted(words[0], words[1:]), case
    # #821: on a deploy CLI, an unknown option before the verb leaves the verb unplaceable, which asks as `publish`;
    # heroku's seed, `config:set`, is read past the option as the secret write it is (#897 review, item 1)
    unplaceable = ({"secret-write" if words[0] == "heroku" else "publish"}
                   if words[0] in DEPLOY_PROGRAMS and case.endswith("/before") else set())
    assert tp._named_rules(words) == tp._legacy_named_rules(words) | unplaceable, case
    main, original = levels("unknown", case, command)
    assert RANK[tp.assess(command).level] >= max(RANK[main], RANK[original]), case


@pytest.mark.parametrize("case,words", CORRECTIONS, ids=[row[0] for row in CORRECTIONS])
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("position", POSITIONS)
def test_round_three_option_operations(case, words, family, position):
    command = spelled(words, family, position)
    assert sg.read(command).understood
    assert tp._fully_accounted(words[0], words[1:]), case
    assert tp.assess(command).level == ("forbid" if words[0] == "security" else "ask")


def test_program_inventory_includes_every_tuple_table():
    # A new program table must bring controls and an unknown-option sweep.
    assert set(tp._OPTION_VALUES) | set(tp._OPTION_FLAGS) <= set(SEEDS)


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


@pytest.mark.parametrize("case,command", list(vercel_directories()), ids=lambda value: value)
def test_vercel_production_directory_retains_publish(case, command):
    assert sg.read(command).understood, case
    assert tp.assess(command).level == "ask", case


@pytest.mark.parametrize("case,words,accounted,command", list(cluster_controls()), ids=lambda value: value if isinstance(value, str) else None)
def test_cluster_value_does_not_absorb_following_unknown(case, words, accounted, command):
    assert sg.read(command).understood, case
    assert tp._fully_accounted(words[0], words[1:]) == accounted, case
    main, original = levels("cluster", case, command)
    actual = tp.assess(command).level
    assert RANK[actual] >= RANK[main], case
    if not accounted:
        assert actual == original, case
        assert tp._named_rules(words) == tp._legacy_named_rules(words), case
    elif case.endswith("/single/plain"):
        assert (original, actual) == ("ask", "run"), case


@pytest.mark.parametrize("case,words,flag,rule", list(implicit_controls()), ids=lambda value: value if isinstance(value, str) else None)
def test_implicit_operation_survives_global_stripping(case, words, flag, rule):
    command = render(words, "single", "plain")
    assert sg.read(command).understood, case
    assert tp._fully_accounted(words[0], words[1:]), case
    assert flag in tp._dispatch_args(words[0], words[1:])[1], case
    assert rule in tp._named_rules(words), case
    assert tp.assess(command).level == "ask", case


def test_global_dispatch_audit_inventory():
    assert set(tp._GLOBAL_OPTIONS) - {"git", "security"} == GLOBAL_DISPATCH_PROGRAMS
    assert {program for program, flags in tp._OPERATION_FLAGS.items() if flags} == set(IMPLICIT_OPERATIONS)


@pytest.mark.parametrize("change", ["membership", "order", "count", "command", "verdict", "matrix", "version"])
def test_baseline_vectors_reject_stale_corpora(change):
    from tests.server.quoted_args_baseline_data import encode, decode, fingerprint, SOURCE_SHA256
    rows = [("first", "echo one"), ("second", "echo two")]
    cases = {"sample/" + case: (fingerprint(text), "run", "ask") for case, text in rows}
    text = encode({"sample": rows}, cases, SOURCE_SHA256)
    assert len(decode(text, {"sample": lambda: rows})) == 2
    if change == "membership":
        rows[0] = ("other", rows[0][1])
    elif change == "order":
        rows.reverse()
    elif change == "count":
        rows.pop()
    elif change == "command":
        rows[0] = (rows[0][0], "echo changed")
    elif change == "verdict":
        text = text.replace("ra ra", "rf ra")
    elif change == "matrix":
        text = text.replace("[sample]", "[other]")
    else:
        text = text.replace('"generator_version":2', '"generator_version":0')
    with pytest.raises(AssertionError):
        decode(text, {"sample": lambda: rows})


@pytest.mark.parametrize("case,words", list(implicit_negative_controls()), ids=lambda value: value if isinstance(value, str) else None)
def test_operation_looking_data_does_not_select_publish(case, words):
    command = render(words, "single", "plain")
    assert sg.read(command).understood, case
    assert tp._fully_accounted(words[0], words[1:]), case
    assert tp._dispatch_args(words[0], words[1:])[1] == frozenset(), case
    assert tp.assess(command).level == "run", case  # Main and original also run.


@pytest.mark.parametrize("change", ["hash", "provenance", "header", "missing-file", "extra-file", "missing-source", "extra-source", "unknown-file-sentinel"])
def test_baseline_vectors_reject_corrupt_provenance(change):
    import json
    from pathlib import Path
    from tests.server.quoted_args_baseline_data import decode, SOURCE_SHA256
    lines = Path(__file__).with_name("quoted_args_baselines.txt").read_text().splitlines()
    header = json.loads(lines[1][2:])
    source, name = "main", "shell_grammar.py"
    expected, recorded = SOURCE_SHA256[source][name], "<missing>"
    if change == "hash":
        recorded = "0" * 64
        header["source_sha256"][source][name] = recorded
    elif change in {"provenance", "header"}:
        del header["source_sha256"]
    elif change == "missing-file":
        del header["source_sha256"][source][name]
    elif change in {"extra-file", "unknown-file-sentinel"}:
        name, expected = "unknown.py", "<absent>"
        recorded = "<absent>" if change == "unknown-file-sentinel" else "0" * 64
        header["source_sha256"][source][name] = recorded
    elif change == "missing-source":
        del header["source_sha256"][source]
    else:
        source, name, expected, recorded = "unknown", "<mapping>", "{}", "{}"
        header["source_sha256"][source] = {}
    lines[1] = "# " + json.dumps(header)
    if change == "header":
        del lines[1]
    with pytest.raises(AssertionError) as failure:
        decode("\n".join(lines), {})
    message = str(failure.value)
    assert f"{source}/{name}" in message
    assert f"expected {expected}" in message
    assert f"recorded {recorded}" in message


@pytest.mark.parametrize("change", [
    "clean", "fixture-hash", "current-source", "source-commits-original", "source-commits-main",
    "duplicate-bad-first", "duplicate-null-first", "duplicate-same", "duplicate-source-bad-first",
])
def test_baseline_fresh_import_validates_independent_trust(tmp_path, change):
    import importlib.util
    import json
    from pathlib import Path
    from tests.server.quoted_args_file_run_evidence import GENERATORS

    # Copy inputs before importing: a fixture-derived import-time table must not
    # authenticate its own corrupted header. No process, shell or Git is used.
    root = Path(__file__).resolve().parents[2]
    directory = tmp_path / "tests/server"
    directory.mkdir(parents=True)
    loader = directory / "quoted_args_baseline_data.py"
    loader.write_bytes(Path(__file__).with_name(loader.name).read_bytes())
    fixture = directory / "quoted_args_baselines.txt"
    lines = Path(__file__).with_name(fixture.name).read_text().splitlines()
    header = json.loads(lines[1][2:])
    source = tmp_path / "server/services/shell_text.py"
    source.parent.mkdir(parents=True)
    source.write_bytes((root / "server/services/shell_text.py").read_bytes())
    expected_message = None
    if change == "fixture-hash":
        header["source_sha256"]["original"]["terminal_policy.py"] = "0" * 64
        # This trust anchor is literal, independent of the fixture and module.
        expected_message = (
            "original/terminal_policy.py: expected "
            "0aa7e22f5faefc3c132c02f8c8fe77561b0acb7214a9d4ba43112f42ecf5b82d, recorded " + "0" * 64)
    elif change == "current-source":
        source.write_bytes(source.read_bytes() + b"\n# Changed source bytes.\n")
        expected_message = "current/shell_text.py: expected 83d99db09fb9805726dfc58b679426f0ba8f599eddeeac7ab6f8b1bbbc0f4571, recorded "
    elif change.startswith("source-commits-"):
        header["source_commits"][change.removeprefix("source-commits-")] = "0" * 40
        expected_message = "Unexpected baseline sources"
    lines[1] = "# " + json.dumps(header)
    if change.startswith("duplicate-"):
        if change == "duplicate-source-bad-first":
            key = "main"
            first = {"unknown.py": "0" * 64}
            repeated = header["source_sha256"][key]
            path = "$/source_sha256/main"
        else:
            key = "shell_grammar.py"
            repeated = header["source_sha256"]["main"][key]
            first = {"duplicate-bad-first": "0" * 64,
                     "duplicate-null-first": None, "duplicate-same": repeated}[change]
            path = "$/source_sha256/main/shell_grammar.py"
        entry = json.dumps(key) + ": " + json.dumps(repeated)
        assert lines[1].count(entry) == 1
        lines[1] = lines[1].replace(entry, json.dumps(key) + ": " + json.dumps(first) + ", " + entry)
        expected_message = f"Duplicate baseline header key: {path}: first {first!r}, repeated {repeated!r}"
    fixture.write_text("\n".join(lines) + "\n")
    spec = importlib.util.spec_from_file_location("scratch_baseline", loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if expected_message is None:
        # 37672, plus 64 controls and 96 unknown-option rows for the eight deploy CLIs on the publish rule
        assert len(module.decode(fixture.read_text(), GENERATORS)) == 37832
    else:
        with pytest.raises(AssertionError) as failure:
            module.decode(fixture.read_text(), GENERATORS)
        assert expected_message in str(failure.value)

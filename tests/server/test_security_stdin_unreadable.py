"""Text-only stdin and transport regressions. Generated commands are never executed."""
from itertools import product
import shlex

import pytest

from server.services import shell_grammar as sg, terminal_policy as tp

# The operation is generated independently of its transport and tool spelling.
OPERATIONS = (
    ("secret", "find-generic-password -w"),
    ("write", "add-generic-password -s sample"),
    ("create", "create-keychain sample"),
    ("unlock", "unlock-keychain sample"),
    ("list", "list-keychains"),
)
SPELLINGS = (
    ("plain", "security -i", "security"),
    ("quiet", "security -q -i", "security -q"),
    ("cluster", "security -iv", "security -v"),
    ("prompt", "security -p sample -i", "security -p sample"),
    ("absolute", "/usr/bin/security -i", "/usr/bin/security"),
    ("uppercase", "SECURITY -i", "SECURITY"),
    ("quoted", "'security' -i", "'security'"),
    ("command", "command security -i", "command security"),
    ("env", "env NOTE=sample security -i", "env NOTE=sample security"),
)
FORMS = ("echo", "printf", "cat", "heredoc", "here-string", "redirect")


def feed(tool, operation, form):
    quoted = shlex.quote(operation)
    return {
        "echo": f"echo {quoted} | {tool}",
        "printf": f"printf '%s\\n' {quoted} | {tool}",
        "cat": f"cat operations.txt | {tool}",
        "heredoc": f"{tool} <<'OPS'\n{operation}\nOPS",
        "here-string": f"{tool} <<< {quoted}",
        "redirect": f"{tool} < operations.txt",
    }[form]


def stdin_cases():
    for (spelling, tool, _), (kind, operation), form in product(SPELLINGS, OPERATIONS, FORMS):
        yield f"{spelling}/{kind}/{form}", feed(tool, operation, form)
    for form in FORMS:
        yield f"bare/{form}", feed("security", "list-keychains", form)
    yield "bare/inherited", "security"


def nested_cases():
    seeds = {
        "wipe-home": "rm -rf ~", "wipe-root": "rm -rf /", "shutdown": "shutdown -h now",
        "sudo": "sudo id", "raw-disk": "dd if=input of=/dev/disk2",
    }
    def quote(text, style):
        if style == "single":
            return shlex.quote(text)
        if style == "double":
            return '"' + ''.join('\\' + c if c in '\\"$`' else c for c in text) + '"'
        return ''.join('\\' + c if c in ' \\' + "'\"$`;|&()<>" else c for c in text)
    for (kind, seed), depth, style, tail in product(seeds.items(), range(1, 4),
                                                  ("single", "double", "escaped"), (False, True)):
        # The trailing command belongs to the outer text, keeping unquoted transport valid.
        text = seed
        for level in range(depth):
            text = ("bash" if level % 2 == 0 else "sh") + " -c " + quote(text, style)
        if tail:
            text += "\ntrue"
        yield f"{kind}/{depth}/{style}/{int(tail)}", text, kind


@pytest.mark.parametrize("case,text", list(stdin_cases()), ids=lambda v: v if '/' in v and ' ' not in v else None)
def test_stdin_is_unreadable(case, text):
    reading = sg.read(text)
    assert not reading.understood, case
    result = tp.assess(text)
    assert result.level in {"ask", "forbid"}, case
    if result.level == "ask":
        assert result.rule == tp.UNREADABLE, case
        assert tp.ask_rules(text) == {tp.UNREADABLE}, case
        if "path" not in result.reason:
            assert "stdin" in result.reason


@pytest.mark.parametrize("spelling,tool,control", SPELLINGS)
@pytest.mark.parametrize("kind,operation", OPERATIONS)
def test_argv_controls(spelling, tool, control, kind, operation):
    text = control + " " + operation
    result = tp.assess(text)
    expected = "ask" if spelling == "absolute" else "forbid" if kind == "secret" else "ask" if kind == "write" else "run"
    assert result.level == expected
    if kind in {"create", "unlock"}:
        assert tp.assess(text, outside=True).level == "ask"
        assert tp.ask_rules(text, outside=True)
        assert tp.risk_grade(text, outside=True) == "MEDIUM"


@pytest.mark.parametrize("case,text", list(stdin_cases()))
def test_outside_stdin_agrees(case, text):
    result = tp.assess(text, outside=True)
    assert result.level in {"ask", "forbid"}, case
    assert tp.risk_grade(text, outside=True) == {"ask": "MEDIUM", "forbid": "HIGH"}[result.level]
    assert bool(tp.ask_rules(text, outside=True)) == (result.level == "ask")


@pytest.mark.parametrize("spelling,tool,control", SPELLINGS)
@pytest.mark.parametrize("transport", ("argv", "quoted", "heredoc"))
def test_interactive_keeps_forbid_floor(spelling, tool, control, transport):
    operation = "dump-keychain"
    if transport == "argv":
        text = tool + " " + operation
    elif transport == "quoted":
        text = tool + " '" + operation + "'"
    else:
        text = feed(tool, "security " + operation, "heredoc")
    expected = "ask" if spelling == "absolute" and transport != "heredoc" else "forbid"
    assert tp.assess(text).level == expected
    assert tp.assess(text, outside=True).level == expected
    assert tp.ask_rules(text) == ({tp.UNREADABLE} if expected == "ask" else set())


@pytest.mark.parametrize("case,text,rule", list(nested_cases()))
def test_nested_transport_forbid(case, text, rule):
    assert tp.assess(text).level == "forbid", case
    assert tp.assess(text).rule == rule, case
    assert tp.risk_grade(text, outside=True) == "HIGH"


@pytest.mark.parametrize("args", ("list-keychains", "find-identity", "-p i list-keychains",
                                   "-pi list-keychains", "-- list-keychains", "--help", "-h"))
def test_readonly_argv_stays_run(args):
    text = "security " + args
    assert sg.read(text).understood
    assert tp.assess(text).level == "run"
    assert tp.ask_rules(text) == set()


@pytest.mark.parametrize("args", ("-i", "-qi", "-iv", "-p sample -i", "-ip sample", "-qiprompt"))
def test_interactive_letter(args):
    text = "security " + args + " list-keychains"
    assert not sg.read(text).understood
    assert tp.assess(text).rule == tp.UNREADABLE
    assert tp.ask_rules(text) == {tp.UNREADABLE}


@pytest.mark.parametrize("spelling,tool,control", [row for row in SPELLINGS if row[0] != "absolute"])
@pytest.mark.parametrize("endpoint", (("rm", "-rf", "/"), ("security", "dump-keychain")))
@pytest.mark.parametrize("separator", ("; ", " && ", "\n"))
def test_interactive_keeps_later_argv_floor(spelling, tool, control, endpoint, separator):
    text = tool + separator + " ".join("'" + word + "'" for word in endpoint)
    assert not sg.read(text).understood
    assert not sg.read_prefix(text).refused
    assert tp.assess(text).level == "forbid"
    assert tp.assess(text, outside=True).level == "forbid"
    assert tp.ask_rules(text) == set()


@pytest.mark.parametrize("args", ("-p", "-qp", "-q", "--"))
def test_missing_operation(args):
    text = "security " + args
    assert not sg.read(text).understood
    assert tp.assess(text).rule == tp.UNREADABLE
    assert tp.ask_rules(text, outside=True) == {tp.UNREADABLE}

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


B1_CASES = (
    ("B1/assigned-interactive-here-string", "REVIEW_MODE=-i; security $REVIEW_MODE <<< 'list-keychains'"),
    ("B1/assigned-empty-file", "REVIEW_MODE=; security $REVIEW_MODE < review.ops"),
    ("B1/assigned-interactive-quoted", 'REVIEW_MODE=-i; security "$REVIEW_MODE" <<< \'list-keychains\''),
    ("B1/assigned-interactive-pipe", "REVIEW_MODE=-i; printf '%s\\n' 'list-keychains' | command security $REVIEW_MODE"),
    ("B1/assigned-interactive-heredoc", "REVIEW_MODE=-i; security $REVIEW_MODE <<REVIEW_STOP\nlist-keychains\nREVIEW_STOP"),
    ("B1/assigned-create-outside", "REVIEW_MODE=-i; security $REVIEW_MODE create-keychain review.keychain <<< 'list-keychains'"),
    ("B1/assigned-unlock-outside", "REVIEW_MODE=-i; security $REVIEW_MODE unlock-keychain review.keychain <<< 'list-keychains'"),
    ("B1/prompt-expansion", "unset REVIEW_PROMPT; security -p $REVIEW_PROMPT list-keychains < review.ops"),
)


def assert_unreadable(text, outside):
    reading = sg.read(text)
    assert not reading.understood
    assert reading.why == "its security reads operations from stdin"
    assert not sg.read_prefix(text).refused
    result = tp.assess(text, outside=outside)
    assert (result.level, result.rule, result.reason) == ("ask", tp.UNREADABLE, reading.why)
    assert tp.ask_rules(text, outside=outside) == {tp.UNREADABLE}
    assert tp.risk_grade(text, outside=outside) == "MEDIUM"


@pytest.mark.parametrize("outside", (False, True), ids=("inside", "outside"))
@pytest.mark.parametrize("case,text", B1_CASES, ids=[case for case, _ in B1_CASES])
def test_b1_leading_expansion_is_unreadable(case, text, outside):
    assert_unreadable(text, outside)


@pytest.mark.parametrize("outside", (False, True))
@pytest.mark.parametrize("args", (
    "-$MODE", "${MODE}", '"$(printf list-keychains)"', "-- $MODE",
    "-q $MODE", "-qp $PROMPT list-keychains", "-p$PROMPT list-keychains",
))
def test_ambiguous_operation_selection(args, outside):
    assert_unreadable("security " + args, outside)


@pytest.mark.parametrize("outside", (False, True))
def test_ambiguous_operation_precedes_named_ask(outside):
    assert_unreadable("git push; security $MODE", outside)


@pytest.mark.parametrize("outside", (False, True))
@pytest.mark.parametrize("tail", ("; 'security' 'dump-keychain'", "; 'rm' '-rf' '/'"))
def test_ambiguous_operation_keeps_forbid_floor(tail, outside):
    text = "security $MODE" + tail
    assert not sg.read(text).understood
    assert not sg.read_prefix(text).refused
    assert tp.assess(text, outside=outside).level == "forbid"
    assert tp.ask_rules(text, outside=outside) == set()
    assert tp.risk_grade(text, outside=outside) == "HIGH"


@pytest.mark.parametrize("outside", (False, True))
@pytest.mark.parametrize("text", (
    "security list-keychains", "security 'list-keychains'", 'security "list-keychains"',
    "security -- list-keychains", "security -p sample list-keychains",
    "security -psample list-keychains", "security -qv list-keychains", "security --help",
    "security '$MODE'", r"security \$MODE", "security -p '$PROMPT' list-keychains",
    "security list-keychains $OPERAND", 'security list-keychains "$(printf sample)"',
    "printf '%s' $MODE", "git status $OPERAND",
))
def test_literal_selection_and_operand_controls(text, outside):
    assert sg.read(text).understood
    assert not sg.read_prefix(text).refused
    assert tp.assess(text, outside=outside).level == "run"
    assert tp.ask_rules(text, outside=outside) == set()
    assert tp.risk_grade(text, outside=outside) == "LOW"


@pytest.mark.parametrize("outside", (False, True))
@pytest.mark.parametrize("operation", ("create-keychain", "unlock-keychain"))
def test_literal_service_operation_controls(operation, outside):
    text = "security " + operation + " review.keychain"
    assert sg.read(text).understood
    result = tp.assess(text, outside=outside)
    assert result.level == ("ask" if outside else "run")
    assert tp.ask_rules(text, outside=outside) == ({"outside-reach"} if outside else set())
    assert tp.risk_grade(text, outside=outside) == ("MEDIUM" if outside else "LOW")


@pytest.mark.parametrize("case,text", B1_CASES, ids=[case for case, _ in B1_CASES])
def test_shared_reading_keeps_literalness_in_one_pass(case, text, monkeypatch):
    passes = []
    original = sg._read_commands

    def counted(command, out):
        result = original(command, out)
        passes.append((command, result))
        return result

    monkeypatch.setattr(sg, "_read_commands", counted)
    tp._parsed.cache_clear()
    for outside in (False, True):
        result = tp.assess(text, outside=outside)
        assert (result.level, result.rule, result.reason) == (
            "ask", tp.UNREADABLE, "its security reads operations from stdin")
        assert tp.ask_rules(text, outside=outside) == {tp.UNREADABLE}
        assert tp.risk_grade(text, outside=outside) == "MEDIUM"
    assert len(passes) == 1
    command, prefix = passes[0]
    assert command == text
    assert not prefix.refused
    assert prefix.named_unreadable == "its security reads operations from stdin"


@pytest.mark.parametrize("tail", ("; 'rm' '-rf' '/'", "; echo `date`", "; 'rm' '-rf' '/'; echo `date`"))
def test_shared_marker_survives_later_argv_and_grammar_refusal(tail):
    text = "security $MODE" + tail
    prefix = sg.read_prefix(text)
    assert prefix.named_unreadable == "its security reads operations from stdin"
    assert prefix.refused == ("`" in tail)
    if "'rm'" in tail:
        assert ("rm", "-rf", "/") in prefix.commands
    for outside in (False, True):
        result = tp.assess(text, outside=outside)
        assert result.level == ("forbid" if "'rm'" in tail else "ask")
        assert result.rule == ("wipe-root" if "'rm'" in tail else tp.UNREADABLE)


@pytest.mark.parametrize("case,text", list(stdin_cases()))
def test_shared_prefix_marks_every_stdin_form(case, text):
    prefix = sg.read_prefix(text)
    if case.startswith("absolute/"):
        assert prefix.refused and "path" in prefix.why
    else:
        assert not prefix.refused
        assert prefix.named_unreadable == "its security reads operations from stdin"

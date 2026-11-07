"""Past a parser limit, the forbid rules read a separator scan (`shell_text._separated`, #766).

Every check here uses a stand-in forbid rule that matches a made-up word, so no test spells a real forbidden command:
the stand-in is a command word like any other, and what the scan does to it, it does to every rule's command word. The
real rules are checked by name: each one reads the scan. The adversarial cases are written separately."""
import re

import pytest

from server.services import shell_text, terminal_policy as tp

WORD = "zz-stand-in-word"
CALL = WORD + " x"
STAND_IN = "stand-in"

NESTED = shell_text._MAX_NESTED_SUBSTITUTIONS
BACKTICKS = shell_text._MAX_BACKTICKS
BLANKS = shell_text._MAX_BLANK_RUN
NEWLINES = shell_text._MAX_NEWLINES_IN_BLANK_RUN
SUBSTITUTIONS = shell_text._MAX_DETECTION_SUBSTITUTIONS
SEPARATOR_FREE = shell_text._MAX_SEPARATOR_FREE_COMMAND_CHARS

# A piece of its own past each limit, and one under it, from harmless text only.
OVER = {
    "nested": "$(" * NESTED + ")" * NESTED,
    "backticks": "`" * BACKTICKS,
    "blanks": "x" + " " * BLANKS + "x",
    "newlines": "x" + "\n" * NEWLINES + "x",
    "substitutions": "$(a)" * SUBSTITUTIONS,
}
UNDER = {
    "nested": "$(" * (NESTED - 1) + ")" * (NESTED - 1),
    "backticks": "`" * (BACKTICKS // 2),
    "blanks": "x" + " " * (BLANKS // 2) + "x",
    "newlines": "x" + "\n" * (NEWLINES // 2) + "x",
    "substitutions": "$(a)" * (SUBSTITUTIONS // 2),
}

# Where a command starts that only a structural reading sees. `{w}` is the stand-in call.
POSITIONS = {
    # after each separator
    "semicolon": "ls; {w}", "and": "ls && {w}", "or": "ls || {w}", "pipe": "ls | {w}", "pipe-both": "ls |& {w}",
    "background": "ls & {w}", "newline": "ls\n{w}",
    # inside each bracket
    "subshell": "({w})", "group": "{{ {w}; }}", "substitution": "echo $({w})", "backticks": "echo `{w}`",
    "process-in": "cat <({w})", "process-out": "ls > >({w})", "nested-group": "( {{ ({w}); }} )",
    # after each keyword that starts a command
    "if": "if {w}; then :; fi", "then": "if :; then {w}; fi", "else": "if :; then :; else {w}; fi",
    "elif": "if false; then :; elif {w}; then :; fi", "while": "while {w}; do :; done",
    "until": "until {w}; do :; done", "do": "for i in 1; do {w}; done", "not": "! {w}",
    # a quoted argument that a shell or a launcher runs
    "sh-c": "sh -c '{w}'", "bash-c-double": 'bash -c "{w}"', "zsh-c-separator": "zsh -c 'ls; {w}'",
    "sh-c-group": "sh -c '(ls; {w})'", "sh-c-keyword": "sh -c 'if :; then {w}; fi'",
    "watch": "watch '{w}'", "watch-separator": "watch 'ls && {w}'", "tmux": "tmux new 'ls; {w}'",
    "script": "script -q /dev/null -c 'ls; {w}'", "concurrently": "concurrently 'ls' 'ls; {w}'",
    # a separator inside a double-quoted substitution
    "quoted-substitution": 'echo "$({w})"', "quoted-substitution-separator": 'echo "$(ls; {w})"',
    "quoted-substitution-assigned": 'x="$(ls && {w})"',
}


@pytest.fixture
def stand_in(monkeypatch):
    """A forbid rule for the stand-in word in command position, first in the table like any rule. Registering another
    replaces it, so a test of a rule's shape isn't answered by the plain word."""
    real = list(tp._FORBID_C)

    def register(pattern: str = tp._POS + re.escape(WORD) + r"\b", masked: bool = False):
        rule = (STAND_IN, re.compile(pattern, re.I | re.DOTALL), "a stand-in", masked)
        monkeypatch.setattr(tp, "_FORBID_C", [rule, *real])
    register()
    return register


def _verdict(command: str) -> tuple[str, str]:
    found = tp.assess(command)
    return found.level, found.rule


def test_the_limits_are_pinned():
    assert shell_text._MAX_NESTED_SUBSTITUTIONS == 6
    assert shell_text._MAX_BACKTICKS == 32


@pytest.mark.parametrize("limit", OVER, ids=OVER.keys())
@pytest.mark.parametrize("position", POSITIONS.values(), ids=POSITIONS.keys())
@pytest.mark.parametrize("before", [True, False], ids=["limit-first", "limit-last"])
def test_past_each_limit_the_stand_in_is_forbidden_in_every_structural_position(stand_in, limit, position, before):
    reached = position.format(w=CALL)
    command = f"{OVER[limit]}; {reached}" if before else f"{reached}; {OVER[limit]}"
    assert tp._over_limit(tp._forms(command))
    assert _verdict(command) == ("forbid", STAND_IN), command


@pytest.mark.parametrize("limit", OVER, ids=OVER.keys())
@pytest.mark.parametrize("carrier", ["sh -c '{over}; {w}'", "watch '{over} && {w}'", 'bash -c "({over}) | {w}"'],
                         ids=["sh-c", "watch", "bash-c-double"])
def test_past_each_limit_inside_the_argument_that_runs_the_stand_in_is_forbidden(stand_in, limit, carrier):
    command = carrier.format(over=OVER[limit], w=CALL)
    assert tp._over_limit(tp._forms(command))
    assert _verdict(command) == ("forbid", STAND_IN), command


@pytest.mark.parametrize("position", [p for p in POSITIONS.values() if not any(c in p for c in ";&|\n")],
                         ids=[k for k, p in POSITIONS.items() if not any(c in p for c in ";&|\n")])
def test_past_the_separator_free_length_the_stand_in_is_forbidden(stand_in, position):
    command = "x" * (SEPARATOR_FREE + 1) + " " + position.format(w=CALL)
    assert tp._over_limit(tp._forms(command))
    assert _verdict(command) == ("forbid", STAND_IN), command


# Every character the scan takes as a separator, each alone before the stand-in inside a `-c` argument: no other form
# past the limit reads a command start there. A single quote goes in a double-quoted argument.
SEPARATOR_CHARACTERS = "'\"`()[]{};&|"


@pytest.mark.parametrize("limit", OVER, ids=OVER.keys())
@pytest.mark.parametrize("character", SEPARATOR_CHARACTERS, ids=[f"char-{ord(c):x}" for c in SEPARATOR_CHARACTERS])
def test_past_each_limit_each_separator_character_starts_a_command(stand_in, limit, character):
    argument = f'"ls{character}{CALL}"' if character == "'" else f"'ls{character}{CALL}'"
    command = f"{OVER[limit]}; sh -c {argument}"
    assert _verdict(command) == ("forbid", STAND_IN), command


@pytest.mark.parametrize("keyword", sorted(shell_text._SHELL_COMMAND_TRANSITIONS))
def test_past_a_limit_each_command_keyword_starts_a_command(stand_in, keyword):
    command = f"{OVER['nested']}; sh -c 'ls {keyword} {CALL}'"
    assert _verdict(command) == ("forbid", STAND_IN), command


def test_past_a_limit_a_keyword_inside_a_longer_word_does_not(stand_in):
    for word in ("thenx", "xdo", "if-x", "!x"):
        command = f"{OVER['nested']}; sh -c 'ls {word} {CALL}'"
        assert _verdict(command) == ("ask", tp.UNREADABLE), command


def test_past_a_limit_a_parameter_brace_is_not_a_group(stand_in):
    """`${NAME}` stays one word, so a rule that reads a parameter by name (`${HOME}`) reads it inside a `-c`."""
    stand_in(tp._POS + re.escape(WORD) + r"\s+\$\{?ZZ\}?(?:\s|$)")
    command = f"{OVER['nested']}; sh -c '{WORD} ${{ZZ}}'"
    assert _verdict(command) == ("forbid", STAND_IN)


def test_past_a_limit_the_unquoted_form_reads_a_word_spelled_with_quotes_and_arguments_across_quotes(stand_in):
    """What the separator scan splits: a quote inside the word, and a rule reading its command's line to an option."""
    assert _verdict(f"{OVER['nested']}; ls; z'z'-stand-in-word x") == ("forbid", STAND_IN)
    stand_in(tp._POS + r"zz-reader\b[^\n]*\s-zz\b")
    assert _verdict(f"{OVER['nested']}; ls; zz-reader -s 'a b' -zz") == ("forbid", STAND_IN)


def test_past_a_limit_the_text_as_written_reads_a_rule_made_of_separators(stand_in):
    """A rule that reads the metacharacters themselves, as the fork-bomb rule does: no other form keeps them."""
    stand_in(r"zz-a\|zz-b", masked=True)
    assert _verdict(f"{OVER['nested']}; zz-a|zz-b") == ("forbid", STAND_IN)


@pytest.mark.parametrize("limit", UNDER, ids=UNDER.keys())
@pytest.mark.parametrize("position", POSITIONS.values(), ids=POSITIONS.keys())
def test_under_the_limits_the_scan_is_never_read(stand_in, monkeypatch, limit, position):
    command = f"{UNDER[limit]}; {position.format(w=CALL)}"
    assert not tp._over_limit(tp._forms(command)), command
    assert tp._detection_texts(command) == tp._forms(command)

    def unread(_command):
        raise AssertionError("the scan was read under the limits")
    monkeypatch.setattr(shell_text, "over_limit_forms", unread)
    tp.assess(command)


@pytest.mark.parametrize("quote", ["'", '"'], ids=["single", "double"])
def test_quoted_prose_is_data_under_the_limits_and_a_command_past_them(stand_in, quote):
    """The one reading the scan changes, and only past a limit."""
    prose = f"echo {quote}ls; {CALL}{quote}"
    assert _verdict(f"{UNDER['nested']}; {prose}") == ("run", "")
    assert _verdict(f"{OVER['nested']}; {prose}") == ("forbid", STAND_IN)


def test_every_forbid_rule_reads_the_separator_scan(monkeypatch):
    """By name: each real rule, the positionless ones in their masked reading, is matched against the scan."""
    command = f"{OVER['nested']}; ls"
    separated = shell_text._squeeze_blank_runs(shell_text._separated(shell_text.normalize(command)))
    assert separated in tp._detection_texts(command)
    read: set[int] = set()
    real = tp._matches

    def recording(pattern, texts):
        if separated in texts:
            read.add(id(pattern))
        return real(pattern, texts)
    monkeypatch.setattr(tp, "_matches", recording)
    assert _verdict(command) == ("ask", tp.UNREADABLE)
    unread = [key for key, pattern, _why, _masked in tp._FORBID_C if id(pattern) not in read]
    assert unread == []
    assert {key for key, *_ in tp._FORBID_C} == {key for key, *_ in tp._FORBID}


def test_every_anchored_forbid_rule_takes_a_line_start_as_a_command_start():
    """The scan puts each command at a line start, so a rule anchored any other way would not read it. The positionless
    rules (masked, and the key-file names) need no start."""
    anchors = (tp._POS, "(?:" + tp._CMD, r"(?:^|[\n;&|`(]|\$\()")
    for anchor in (tp._POS, tp._CMD, anchors[2]):
        assert re.fullmatch(anchor, "\n"), anchor
    for key, pattern, _why, masked in tp._FORBID:
        if masked or key == "arslan-keys":
            continue
        assert pattern.startswith(anchors), key

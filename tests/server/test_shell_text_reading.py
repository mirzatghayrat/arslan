"""How Arslan reads a shell command (server/services/shell_text.py), pinned by what each spelling runs.

Permanent (②Main's review of #320, A2): the parity test against the vendored Hermes code goes in S2b-2,
so these hold the anti-obfuscation readings on their own. Every expected verdict is what the shell would
run, written out, not computed. Known gaps that are still open (B1-B4 in that review: ANSI-C quoting, zsh
precommand modifiers, `command rm` below the floor) are not pinned here."""
import os

import pytest

from server.services import shell_text, terminal_policy as tp

WIPE_HOME = [
    # one command word spelled in pieces
    "r''m -rf ~", "r\\m -rf ~", "$(echo rm) -rf ~", "`echo rm` -rf ~", "${x:-rm} -rf ~", "'rm' -rf ~", '"rm" -rf ~',
    "\uff52m -rf ~",                                      # fullwidth r (NFKC)
    "\x1b[31mrm -rf ~\x1b[0m", "rm -rf ~\x00",            # ANSI escapes, NUL
    # the spaces
    "rm${IFS}-rf${IFS}~", "rm$IFS-rf ~", "rm -rf \\\n~",
    # a shell that runs its argument, every one of them
    "sh -c 'rm -rf ~'", 'bash -c "rm -rf ~"', "zsh -c 'rm -rf ~'", "dash -c 'rm -rf ~'", "ksh -c 'rm -rf ~'",
    # a real command start after a separator, a group, a keyword or a wrapper
    "ls; rm -rf ~", "ls && rm -rf ~", "false || rm -rf ~", "ls | rm -rf ~", "(rm -rf ~)", "{ rm -rf ~; }",
    "if true; then rm -rf ~; fi", "while true; do rm -rf ~; done", "for i in 1; do rm -rf ~; done", "! rm -rf ~",
    "env FOO=1 rm -rf ~", "nohup rm -rf ~", "time rm -rf ~", "exec rm -rf ~",
    # substitutions run
    "echo $(rm -rf ~)", "x=$(rm -rf ~)", 'echo "$(ls\nrm -rf ~)"',
    # program options of read tools
    "man -P 'rm -rf ~' ls", "sort --compress-program='rm -rf ~' f",
    # the home path spelled out
    f"rm -rf {os.path.expanduser('~')}/",
]


@pytest.mark.parametrize("command", WIPE_HOME)
def test_every_spelling_of_wiping_home_is_the_floor(command):
    assert (tp.assess(command).level, tp.assess(command).rule) == ("forbid", "wipe-home")


@pytest.mark.parametrize("command,rule", [
    ('cat "f\\"n"; rm -rf /', "wipe-root"),               # an escaped quote does not hide the next command
    ("echo C:\\x\nrm -rf \\etc", "macos-roots"),         # a backslash path is also read with `/`
    ("dd if=x of=\\dev\\disk2 # C:\\", "raw-disk"),
    ('bash -c "cat x > /dev/disk2"', "raw-disk"),         # a carrier's quoted argument is code
])
def test_what_the_shell_runs_through_quotes_and_escapes_is_read(command, rule):
    assert (tp.assess(command).level, tp.assess(command).rule) == ("forbid", rule)


@pytest.mark.parametrize("command", [
    "g''it push", "$(echo git) push", "git${IFS}push", "x; g\\it push", "bash -c 'git push'", "dash -c 'git push'",
    "!${IFS}git${IFS}push",                               # a start marked on the normalized text (after `!`)
])
def test_a_layer_two_command_spelled_in_pieces_still_asks(command):
    assert "git-push" in tp.ask_rules(command) and tp.assess(command).level == "ask"


@pytest.mark.parametrize("command", [
    "echo 'rm -rf ~'", 'echo "rm -rf ~"', "grep -P 'rm -rf ~' f", 'echo "cat x > /dev/disk2"',
    "r''m old.txt", "echo " + "a" * 4000,
])
def test_quoted_data_and_ordinary_commands_run(command):
    assert tp.assess(command).level == "run", tp.assess(command)


@pytest.mark.parametrize("command", [
    "echo " + "a" * 4100,                                 # past the separator-free limit (4096)
    "grep -e", "grep -P", "grep \"a", "grep -P 'x' 'y",   # a grep that cannot be read
])
def test_what_cannot_be_read_asks(command):
    assert (tp.assess(command).level, tp.assess(command).rule) == ("ask", tp.UNREADABLE)


@pytest.mark.parametrize("command", ["eval 'rm -rf ~'", "command rm -rf ~"])
def test_known_weaker_readings_still_never_run(command):
    # Open (②Main's review of #320, B): these should be the floor; today they ask. They must never run.
    assert tp.assess(command).level != "run"


# ── the readings themselves, where no single verdict shows them ──────────────

def test_a_quoted_newline_is_data_and_an_unquoted_one_a_command_start():
    assert shell_text.mask_quoted_newlines('echo "a\nb"\nls') == 'echo "a b"\nls'
    assert shell_text.mask_quoted_newlines("echo 'x\ny'") == "echo 'x y'"
    assert shell_text.mask_quoted_newlines('echo "$(ls\nrm x)"') == 'echo "$(ls\nrm x)"'    # it runs


def test_quoted_prose_is_masked_but_a_substitution_in_double_quotes_is_kept():
    assert shell_text.mask_quoted_prose("echo 'rm -rf /' x") == "echo '" + " " * 8 + "' x"
    assert shell_text.mask_quoted_prose('echo "a $(rm -rf /) b"') == 'echo "  $(rm -rf /)  "'


@pytest.mark.parametrize("command,carrier", [
    ("sh -c x", True), ("dash -c x", True), ("eval x", True), ("source f", True), (". f", True),
    ("nohup bash -c x", True), ("echo sh", False), ("ls", False),
])
def test_a_shell_carrier_is_a_command_word_that_runs_its_argument(command, carrier):
    assert shell_text.has_shell_carrier(command) is carrier


def test_the_parser_limits():
    assert not shell_text.too_complex("a" * 4096) and shell_text.too_complex("a" * 4097)
    assert not shell_text.too_complex("a;" * 2000) and shell_text.too_complex("a;" * 25_000)
    assert shell_text.too_complex("a" * 128_001)


@pytest.mark.parametrize("command,unreadable", [
    ("grep -e", True), ("grep -P", True), ("grep 'a", True), ("grep -P 'x' f", False), ("grep x f", False),
    ("ls", False),
])
def test_a_grep_is_unreadable_only_when_its_arguments_cannot_be_read(command, unreadable):
    assert shell_text.grep_unreadable(command) is unreadable


def test_normalizing_takes_out_what_the_shell_never_runs():
    home = os.path.expanduser("~")
    assert shell_text.normalize("r''m -rf \\\n~") == "rm -rf ~"
    assert shell_text.normalize("rm${IFS}-rf$IFS/") == "rm -rf /"
    assert shell_text.normalize("\uff52m\x00 \x1b[1mx") == "rm x"
    assert shell_text.normalize(f"cat {home}/.zshrc") == "cat ~/.zshrc"


def test_variants_mark_real_command_starts_and_spell_out_command_words():
    found = list(shell_text.variants("ls && $(echo rm) -rf ~"))
    assert any("\nrm -rf ~" in v or v.startswith("rm -rf ~") for v in found) or any(
        "rm -rf ~" in v and "$(echo" not in v for v in found)
    assert any("\n" in v and "&&" in v for v in found)               # a start marked after &&
    assert "rm -rf /" in list(shell_text.variants("bash -c 'rm -rf /'"))   # a -c payload on its own


def test_a_command_inside_a_substitution_starts_a_line_of_its_own():
    assert list(shell_text.variants("echo $(git push)"))[1] == "echo $(\ngit push)"
    assert list(shell_text.variants("echo `git push`"))[1] == "echo `\ngit push`"
    assert list(shell_text.variants("x=$(ls; git push)"))[1] == "x=$(\nls; \ngit push)"


# ── what can't be read cheaply can't be read ──────────────────────────────────

NESTED = shell_text._MAX_NESTED_SUBSTITUTIONS
BACKTICKS = shell_text._MAX_BACKTICKS
BLANKS = shell_text._MAX_BLANK_RUN
NEWLINES = shell_text._MAX_NEWLINES_IN_BLANK_RUN


@pytest.mark.parametrize("build,limit", [
    (lambda n: "$(" * n + ")" * n, NESTED),
    (lambda n: "`" * n, BACKTICKS),
    (lambda n: "a" + " " * n + "b", BLANKS),
    (lambda n: "a" + "\n" * n + "b", NEWLINES),
    (lambda n: "a" + "\n " * n + "b", NEWLINES),
], ids=["nested", "backticks", "blanks", "newlines", "newlines-apart"])
def test_too_complex_at_each_limit_and_not_just_under_it(build, limit):
    assert shell_text.too_complex(build(limit))
    assert not shell_text.too_complex(build(limit - 1))


@pytest.mark.parametrize("opener", [
    '$(")"', "$(')'", "$(\\)", "$(`)", '"$(")"', "'$(", "\\$(", '$(")" ', '$(";"', '"$(\'")\'',
], ids=["double", "single", "backslash", "backtick", "inside-double", "single-quoted", "escaped", "spaced", "no-closer",
        "both"])
def test_a_closer_that_may_be_data_doesnt_lower_the_nesting(opener):
    """Whether a `)` closes depends on a quote before it, here or in a later reading of a quoted argument, so a `$(` that
    met a quote stays counted. Quoted and escaped openers count too: a `-c` argument reads them."""
    assert shell_text.too_complex(opener * NESTED)
    assert not shell_text.too_complex(opener * (NESTED - 1))


@pytest.mark.parametrize("command", [
    "$(a) " * 200, "$(a)" * 200, "echo $(a) $(b); " * 100, "x=$(a)\n" * 200, "$($(a)) " * 100,
    '"$(a)" ' * 200,
], ids=["apart", "together", "chained", "lines", "pairs", "quoted-around"])
def test_substitutions_that_close_are_not_nesting(command):
    assert not shell_text.too_complex(command)


@pytest.mark.parametrize("build,limit", [
    (lambda n: "\n''" * n, NEWLINES), (lambda n: '\n""' * n, NEWLINES), (lambda n: "\n$IFS" * n, NEWLINES),
    (lambda n: "$''(" * n, NESTED), (lambda n: "\n\x00" * n, NEWLINES),
], ids=["single", "double", "ifs", "opener", "nul"])
def test_the_limits_count_the_normalized_text_too(build, limit):
    """Normalizing is what the rules read, and it can make a run or an opener out of text that has neither."""
    assert shell_text.too_complex(build(limit))
    assert not shell_text.too_complex(build(limit - 1))


def test_too_many_substitutions_in_all_is_still_past_the_limit():
    assert shell_text.too_complex("$(a)" * shell_text._MAX_DETECTION_SUBSTITUTIONS)
    assert not shell_text.too_complex("$(a)" * (shell_text._MAX_DETECTION_SUBSTITUTIONS - 1))


@pytest.mark.parametrize("over", [
    "$(" * NESTED + ")" * NESTED, '$(")"' * NESTED, "`" * BACKTICKS, "a" + "\n" * NEWLINES + "b",
    "a" + " " * BLANKS + "b", "$(echo g)" * shell_text._MAX_DETECTION_SUBSTITUTIONS,
], ids=["nested", "quoted-closer", "backticks", "newlines", "blanks", "many-in-one-word"])
@pytest.mark.parametrize("wrap", [
    "{}; git push", "git push; {}", "echo {}", "sh -c 'x; {}'", "bash -c \"{}\"", "watch '{} x'",
], ids=["before", "after", "argument", "c-single", "c-double", "launcher"])
def test_past_a_limit_a_command_asks_as_unreadable_however_it_hides_there(over, wrap):
    """An argument that runs is read on its own, so being past a limit there is the command being past it."""
    command = wrap.format(over)
    assert (tp.assess(command).level, tp.assess(command).rule) == ("ask", tp.UNREADABLE), command
    assert tp.ask_rules(command) == {tp.UNREADABLE}


@pytest.mark.parametrize("carrier", ["bash -c", "watch"])
def test_a_substitution_only_a_later_reading_makes_counts_in_that_reading(carrier):
    """Quotes can split an opener so the command as written has none; the `-c` argument, read on its own, has them all."""
    command = f"{carrier} '" + "$'\"(\"'" * NESTED + " '"
    assert not shell_text.too_complex(command)
    assert (tp.assess(command).level, tp.assess(command).rule) == ("ask", tp.UNREADABLE)
    assert tp.ask_rules(command) == {tp.UNREADABLE}


def test_a_later_reading_under_the_limits_is_read():
    command = "bash -c '" + "$'\"(\"'" * (NESTED - 1) + " git push'"
    assert (tp.assess(command).level, tp.assess(command).rule) == ("ask", "git-push")


def test_nothing_is_scanned_past_a_limit():
    """A hidden argument gets as far as the reader before `too_complex` is asked about it."""
    assert shell_text._iter_shell_command_starts("x; " + "$(" * NESTED) == ()
    assert shell_text._iter_shell_command_word_spans("x; " + "`" * BACKTICKS) == ()
    assert shell_text._iter_shell_command_starts("x; " + "$(" * (NESTED - 1)) != ()


def test_no_regex_reads_a_form_past_a_limit():
    """Only the linear forms, each with its blank runs squeezed, so each is back under the blank limits."""
    for command in ("a" + "\n" * NEWLINES + "b", "bash -c 'a" + "\n" * NEWLINES + "b'", "$(" * NESTED + "\n" * NEWLINES,
                    "a;" + "\n" * NEWLINES + "r''m" + " " * BLANKS + "'x'"):
        assert tp._detection_texts(command) == shell_text.over_limit_forms(command)
        assert not any(shell_text._blank_run_over_limit(text) for text in tp._detection_texts(command))
        assert len(tp._detection_texts(command)) <= 3


def test_past_a_limit_the_forms_are_as_written_each_top_level_command_unquoted_and_separated():
    """In the unquoted form a quoted `;` is not split, and a blank before each new line keeps an escaped `\\` from
    joining it to the next. In the separated one every quote and separator is a line start."""
    assert shell_text.over_limit_forms("ls; r''m x && 'rm' y 'a; b' \\\\| z") == (
        "ls; r''m x && 'rm' y 'a; b' \\\\| z", "ls\nrm x\nrm y a; b \\\nz", "ls\nrm x\nrm\ny\na\nb\n\\\nz")


def test_past_a_limit_a_run_of_backticks_is_read_as_one_in_the_new_forms():
    """Every start in a run would read the rest of it; the last one reads all a rule could match at any of them."""
    command = "`" * BACKTICKS + "x; `'`" + "`" * BACKTICKS + "ls -l"
    written, unquoted, separated = shell_text.over_limit_forms(command)
    assert written == command
    assert unquoted == "`x\n`ls -l"         # joined again once the quote is out
    assert separated == "\nx\nls -l"


# Past each limit, as a piece of its own the command chains to.
OVER_LIMIT = {
    "nested": "$(" * NESTED + ")" * NESTED,
    "backticks": "`" * BACKTICKS,
    "blanks": "x" + " " * BLANKS + "x",
    "newlines": "x" + "\n" * NEWLINES + "x",
    "all-substitutions": "$(a)" * shell_text._MAX_DETECTION_SUBSTITUTIONS,
}
FORBIDDEN = {"wipe-home": "rm -rf ~", "wipe-root": "rm -rf /", "shutdown": "shutdown -h now", "sudo": "sudo ls",
             "raw-disk": "dd if=x of=/dev/disk2"}


def _spelled(command: str, inside: str) -> str:
    """The command word with `inside` after its first letter (`r''m`): the shell runs the same word."""
    return command[0] + inside + command[1:]


# How the forbidden command is reached: each one only a reading past the text as written sees.
REACHED = {
    "semicolon": lambda c: "ls; " + c, "and": lambda c: "ls && " + c, "or": lambda c: "false || " + c,
    "pipe": lambda c: "ls | " + c, "background": lambda c: "ls & " + c, "newline-after-blanks": lambda c: "ls \n" + c,
    "escaped-backslash-then-separator": lambda c: "ls \\\\; " + c, "after-backticks": lambda c: "``" + c,
    "in-a-substitution": lambda c: "echo $(ls; " + c + ")",
    "empty-quotes": lambda c: _spelled(c, "''"), "backslash": lambda c: _spelled(c, "\\"),
    "ifs": lambda c: c.replace(" ", "${IFS}", 1), "continuation": lambda c: c.replace(" ", " \\\n", 1),
    "quoted-word": lambda c: "'" + c.replace(" ", "' ", 1), "double-quoted-word": lambda c: '"' + c.replace(" ", '" ', 1),
    "quote-in-a-substitution": lambda c: 'echo "$("' + c + ')"',
    "separator-and-spelled": lambda c: "ls; " + _spelled(c, "''"),
    "separator-and-quoted": lambda c: "ls && '" + c.replace(" ", "' ", 1),
}


@pytest.mark.parametrize("over", OVER_LIMIT.values(), ids=OVER_LIMIT.keys())
@pytest.mark.parametrize("reached", REACHED.values(), ids=REACHED.keys())
@pytest.mark.parametrize("rule,command", FORBIDDEN.items(), ids=FORBIDDEN.keys())
@pytest.mark.parametrize("before", [True, False], ids=["limit-first", "limit-last"])
def test_past_every_limit_a_forbidden_command_is_still_forbidden_however_it_is_reached(over, reached, rule, command,
                                                                                         before):
    """Asking can't let a forbidden command run: past a limit, `unreadable` may run in the sandbox with no card."""
    command = f"{over}; {reached(command)}" if before else f"{reached(command)}; {over}"
    assert tp._over_limit(tp._forms(command))
    assert (tp.assess(command).level, tp.assess(command).rule) == ("forbid", rule), command


@pytest.mark.parametrize("over", OVER_LIMIT.values(), ids=OVER_LIMIT.keys())
@pytest.mark.parametrize("rule,command", FORBIDDEN.items(), ids=FORBIDDEN.keys())
@pytest.mark.parametrize("quote", ["'", '"'], ids=["single", "double"])
def test_past_a_limit_a_separator_in_quotes_is_a_separator(over, rule, command, quote):
    """Past a limit what a quote holds may be a `-c` argument read later, so a separator there starts a command too.
    Prose is forbidden with it, which fails closed."""
    command = f"{over}; echo {quote}ls; {command}{quote}"
    assert tp._over_limit(tp._forms(command))
    assert (tp.assess(command).level, tp.assess(command).rule) == ("forbid", rule), command


@pytest.mark.parametrize("blanks", ["\n" * NEWLINES, " " * BLANKS, "\n \t" * NEWLINES], ids=["newlines", "spaces", "mixed"])
@pytest.mark.parametrize("command,rule", [
    ("{}rm -rf /", "wipe-root"), ("rm{}-rf /", "wipe-root"), ("rm -rf{}/", "wipe-root"), ("rm -rf /{}", "wipe-root"),
    ("echo a\nrm -rf ~{}", "wipe-home"), ("{}shutdown", "shutdown"), ("cat ~/.arslan/secret_key{}", "arslan-keys"),
], ids=["before", "after-word", "before-path", "after", "second-line", "shutdown", "keys"])
def test_the_forbid_rules_still_read_a_command_with_too_long_a_blank_run(blanks, command, rule):
    command = command.format(blanks)
    assert shell_text.too_complex(command)
    assert (tp.assess(command).level, tp.assess(command).rule) == ("forbid", rule)


@pytest.mark.parametrize("command,rule", [
    ("$(echo g)$(echo i)$(echo t) push", "git-push"),
    ("".join(f"$(echo {c})" for c in "/usr/bin/open") + " -a Terminal", "open-app"),
    ("".join(f"$(echo {c})" for c in "/usr/bin/osascript") + " -e x", "apple-events"),
    ("".join(f"`echo {c}`" for c in "/usr/bin/ssh") + " host", "remote-shell"),
    ("".join(f"$(echo {c})" for c in "./././.") + "/rm -rf /tmp/x", "delete-outside"),
    ("x=$(a); y=$(b); " * 10 + "git push", "git-push"),
    ('echo "$(a "b")" "$(c)"; git push', "git-push"),
    ("$(" * (NESTED - 1) + "git push", "git-push"),
    ("echo a" + "\n" * (NEWLINES - 2) + "git push", "git-push"),      # marking a start adds a newline to the run
    ("echo a" + " " * (BLANKS - 1) + "b; git push", "git-push"),
], ids=["spelled", "spelled-open", "spelled-osascript", "spelled-backticks", "spelled-rm", "flat", "quoted", "nested",
        "blank-lines", "spaces"])
def test_under_the_limits_a_command_is_read_and_its_rule_names_it(command, rule):
    """A word spelled with many substitutions is read, never handed back raw: raw, it'd match no rule at all."""
    assert not shell_text.too_complex(command)
    assert (tp.assess(command).level, tp.assess(command).rule) == ("ask", rule)


def test_a_word_is_spelled_out_however_many_substitutions_it_takes():
    word = "".join(f"$(echo {c})" for c in "/usr/bin/ssh" * 20)
    assert shell_text._deobfuscate_shell_word_for_detection(word) == "/usr/bin/ssh" * 20


@pytest.mark.parametrize("body", ["echo $x", "echo `a`", "printf %s $(a)", "echo $", 'echo "$"', "e$(a)cho x", "echo `"])
def test_a_body_with_a_substitution_is_never_literal_and_isnt_tokenized(body, monkeypatch):
    def tokenizing(*_args, **_kwargs):
        raise AssertionError("tokenized")
    monkeypatch.setattr(shell_text.shlex, "split", tokenizing)
    assert shell_text._literal_command_substitution_output(body) is None


def test_a_body_with_no_substitution_is_still_read_as_a_literal():
    assert shell_text._literal_command_substitution_output("echo rm") == "rm"
    assert shell_text._literal_command_substitution_output("printf %s rm") == "rm"
    assert shell_text._literal_command_substitution_output("echo -n rm") == "rm"
    assert shell_text._literal_command_substitution_output("echo rm x") is None


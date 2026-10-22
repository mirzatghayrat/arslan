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


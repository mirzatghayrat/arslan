"""The verdict is the most cautious one any form of a command gives (#766).

The policy reads a command in several forms: as written, normalized, with a newline at each command start, its `-c`
payloads and launcher arguments, and past a limit the linear forms. No form is chosen over another, and the text as
written (the form main reads) is always among them, so adding a form can only add caution.

Every rule here is a stand-in on a made-up word: no test spells a real rule's command."""
import re

import pytest

from server.services import shell_text, terminal_policy as tp

WORD = "zz-stand-in-word"
WIDE = "zz-wide-word"
ASK_WORD = "zz-ask-word"
SCRIPT = "zz-script"
REACH = "zz-reach-word"
RANK = {"run": 0, "ask": 1, "forbid": 2}
NESTED = "$(" * shell_text._MAX_NESTED_SUBSTITUTIONS + ")" * shell_text._MAX_NESTED_SUBSTITUTIONS


@pytest.fixture
def stand_ins(monkeypatch):
    """A forbid rule for the stand-in word in command position, one that wants two blanks before its operand (a form
    that squeezes blanks doesn't read it), an ask rule, and an inline script that reaches."""
    forbid = [("stand-in", re.compile(tp._POS + re.escape(WORD) + r"\b", re.I | re.DOTALL), "a stand-in", False),
              ("stand-in-wide", re.compile(tp._POS + re.escape(WIDE) + r" {2}x\b", re.I | re.DOTALL),
               "a stand-in", False)]
    monkeypatch.setattr(tp, "_FORBID_C", [*forbid, *tp._FORBID_C])
    monkeypatch.setattr(tp, "_ASK_C", [("stand-in-ask", re.compile(tp._POS + re.escape(ASK_WORD) + r"\b", re.I),
                                        "a stand-in"), *tp._ASK_C])
    monkeypatch.setattr(tp, "_INLINE_SCRIPT", re.compile(tp._POS + re.escape(SCRIPT) + r"\b[^\n]*\s-c\b"))
    monkeypatch.setattr(tp, "_SCRIPT_REACH", re.compile(re.escape(REACH)))


def _verdict(command: str) -> tuple[str, str]:
    found = tp.assess(command)
    return found.level, found.rule


def _main_forms(command: str) -> tuple[str, ...]:
    """The whole-command forms main reads: as written, normalized, and the variants of the text."""
    return (command, shell_text.normalize(command), *shell_text._command_detection_variants(command))


def _lines(form: str) -> int:
    return form.count("\n")


def _reaches(form: str) -> bool:
    return any(tp._SCRIPT_REACH.search(script) for script in tp._inline_scripts(form))


# Harmless commands in the shapes the forms differ on, some naming a stand-in.
COMMANDS = [
    "ls", "ls -l  x", "echo a; ls", "git status && ls", "(cd x && ls)", "echo $(ls)", "echo `ls`",
    "sh -c 'ls; echo b'", 'bash -c "ls\nls"', "watch 'ls'", "watch 'ls\nls'", "tmux new 'ls; ls'",
    "sh -c 'watch \"ls\"'", "if true; then ls; fi", "for i in 1; do ls; done", "echo 'a; b'",
    f"ls; {WORD} x", f"{WIDE}  x", f"ls\n{WIDE}  x", "z''z-wide-word  x",
    f"ls && {ASK_WORD} x", f"sh -c 'ls; {ASK_WORD} x'", f"echo '{ASK_WORD}'",
    f"{SCRIPT} -c {REACH}", f"ls; {SCRIPT} -c {REACH}", f"{SCRIPT} -c x\nls; {SCRIPT} -c {REACH}",
    f"ls; {SCRIPT} -c {REACH}; bash -c 'ls; ls\nls\nls\nls'", f"{SCRIPT} -c x; watch 'ls; ls\nls\nls\nls'",
    f"{NESTED}; ls", f"{NESTED}\n{WIDE}  x", f"bash -c '{NESTED}'; ls",
]
# Forms added through the seam: harmless, one with more lines than any command above, one past a limit, one naming the
# stand-in, and one with an inline script that doesn't reach.
EXTRAS = ["ls", "a\nb\nc\nd\ne\nf\ng\nh", NESTED, f"{WIDE}  x", f"{SCRIPT} -c x", "ls  -l\n\n  x"]


@pytest.mark.parametrize("extra", EXTRAS, ids=["plain", "many-lines", "past-a-limit", "stand-in", "script", "blanks"])
@pytest.mark.parametrize("command", COMMANDS)
def test_adding_a_form_never_lowers_the_verdict(stand_ins, monkeypatch, command, extra):
    """Through the seam every reading takes its forms from (`_forms`): one more form, never a lower verdict."""
    before = _verdict(command)
    real = tp._forms
    monkeypatch.setattr(tp, "_forms", lambda text: (*real(text), extra))
    after = _verdict(command)
    assert RANK[after[0]] >= RANK[before[0]], (command, extra, before, after)
    if before[0] == "forbid":
        assert after == before, (command, extra)


def test_the_seam_is_what_every_reading_reads(stand_ins, monkeypatch):
    """So the property above is about the policy: a stand-in form added there is read by each kind of rule."""
    real = tp._forms
    for extra, expected in ((f"{WORD} x", ("forbid", "stand-in")), (f"{ASK_WORD} x", ("ask", "stand-in-ask")),
                            (f"{SCRIPT} -c {REACH}", ("ask", tp.UNREADABLE)), (NESTED, ("ask", tp.UNREADABLE))):
        monkeypatch.setattr(tp, "_forms", lambda text, extra=extra: (*real(text), extra))
        assert _verdict("ls") == expected, extra


def test_past_a_limit_the_text_as_written_is_still_read(stand_ins):
    """Main reads the text as written. The linear forms squeeze its blanks, so a rule that reads two of them reads only
    the text itself."""
    command = f"{NESTED}\n{WIDE}  x"
    assert tp._over_limit(tp._forms(command))
    assert command in tp._detection_texts(command)
    assert not any(tp._FORBID_C[1][1].search(form) for form in shell_text.over_limit_forms(command))
    assert _verdict(command) == ("forbid", "stand-in-wide")


def test_past_a_limit_every_form_under_the_limits_is_still_read(stand_ins):
    """Only a payload is past the limit here, so the normalized text is under it: what it reads still counts."""
    over_in_payload = "bash -c '" + "$'\"(\"'" * shell_text._MAX_NESTED_SUBSTITUTIONS + " '"
    command = f"z''z-wide-word  x\n{over_in_payload}"
    assert not shell_text.too_complex(command)
    assert tp._over_limit(tp._forms(command))
    wide = tp._FORBID_C[1][1]
    assert not wide.search(command) and wide.search(shell_text.normalize(command))
    assert not any(wide.search(form) for form in shell_text.over_limit_forms(command))
    assert _verdict(command) == ("forbid", "stand-in-wide")


def test_past_a_blank_limit_as_written_its_text_is_read_squeezed():
    """The one form not read as it is: every rule's command position reads such a run in time far beyond its length."""
    command = "ls" + " " * shell_text._MAX_BLANK_RUN + "x"
    assert command not in tp._detection_texts(command)
    assert shell_text._squeeze_blank_runs(command) in tp._detection_texts(command)


# ── the inline-script check ───────────────────────────────────────────────────
# The script's line is read in every form. Each command has a `-c` payload or launcher argument with more lines than
# the whole command, which holds only part of it: picked as the form with the most lines, it would win.
SPLIT_WINS = [
    f"{SCRIPT} -c {REACH}; bash -c 'ls; ls\nls\nls\nls'",
    f"{SCRIPT} -c {REACH}; watch 'ls; ls\nls\nls\nls'",
    f"{SCRIPT} -c '{REACH}'\nsh -c 'ls; ls; ls\nls\nls'",
    f"ls; {SCRIPT} -c {REACH}; bash -c 'ls; ls\nls\nls\nls\nls\nls'",
    f"(ls; {SCRIPT} -c {REACH}) && bash -c 'ls; ls; ls; ls\nls\nls'",
]


@pytest.mark.parametrize("command", SPLIT_WINS)
def test_an_inline_script_reads_at_least_what_mains_form_reads(stand_ins, command):
    forms = tp._forms(command)
    most_lines = max(forms, key=_lines)
    assert most_lines not in _main_forms(command) and not _reaches(most_lines)     # a split form would win, and miss
    assert any(_reaches(form) for form in _main_forms(command))
    assert _verdict(command) == ("ask", tp.UNREADABLE), command


@pytest.mark.parametrize("command", [
    f"ls; {SCRIPT} -c {REACH}",                         # at a command start only in the marked forms
    f"ls && {SCRIPT} -c '{REACH}'",
    f"({SCRIPT} -c {REACH})",
])
def test_a_script_main_reads_in_its_marked_form_is_read(stand_ins, command):
    assert not _reaches(command)
    assert _verdict(command) == ("ask", tp.UNREADABLE), command


def test_a_script_is_read_in_every_form_not_the_first_one_that_has_one(stand_ins):
    """As written the first line's script doesn't reach, and the second one isn't at a command start; marked, it is."""
    command = f"{SCRIPT} -c x\nls; {SCRIPT} -c {REACH}"
    assert list(tp._inline_scripts(command)) and not _reaches(command)
    assert _verdict(command) == ("ask", tp.UNREADABLE)


def test_a_script_the_form_with_the_most_lines_misses_is_read(stand_ins):
    """Main read the line in its form with the most lines only: here the text as written, where the script isn't at a
    command start. Every form is read now."""
    command = f"ls; {SCRIPT} -c {REACH}; bash -c 'ls; ls\nls\nls'"
    assert not _reaches(max(_main_forms(command), key=_lines))
    assert not _reaches(max(tp._forms(command), key=_lines))
    assert _verdict(command) == ("ask", tp.UNREADABLE)


def test_a_protected_name_in_a_script_is_read_in_every_form(monkeypatch):
    """The protected-name check reads the same scripts."""
    monkeypatch.setattr(tp, "_INLINE_SCRIPT", re.compile(tp._POS + re.escape(SCRIPT) + r"\b[^\n]*\s-c\b"))
    monkeypatch.setattr(tp, "_PROTECTED_NAME_C", re.compile(re.escape(REACH)))
    command = f"ls; {SCRIPT} -c {REACH}"
    assert "protected-write" in tp.ask_rules(command)

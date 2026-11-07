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
# Forms added through the seam, each with the floor it forces on the verdict once it is read. Harmless ones force
# nothing; one past a limit naming no rule likewise; the stand-in forms force forbid or ask, as a form under a limit and
# as one past a limit (its squeezed linear passes must still name the rule). A dropped form shows as a missing floor.
EXTRAS = {
    "plain": ("ls", "run"), "many-lines": ("a\nb\nc\nd\ne\nf\ng\nh", "run"), "past-a-limit-noise": (NESTED, "run"),
    "blanks": ("ls  -l\n\n  x", "run"), "script-no-reach": (f"{SCRIPT} -c x", "run"),
    "stand-in": (f"{WIDE}  x", "forbid"), "stand-in-past-a-limit": (f"{WORD} x; {NESTED}", "forbid"),
    "ask-past-a-limit": (f"{ASK_WORD} x; {NESTED}", "ask"),
}


@pytest.mark.parametrize("extra,floor", EXTRAS.values(), ids=EXTRAS.keys())
@pytest.mark.parametrize("where", ["append", "prepend"])
@pytest.mark.parametrize("command", COMMANDS)
def test_adding_a_form_never_lowers_the_verdict(stand_ins, monkeypatch, command, extra, floor, where):
    """Through the seam every reading takes its forms from (`_forms`): one more form, never a lower verdict, at either
    end. A form past a limit is read too, so one that names a rule raises the verdict even when nothing else does."""
    before = _verdict(command)
    real = tp._forms
    monkeypatch.setattr(tp, "_forms",
                        lambda text: (extra, *real(text)) if where == "prepend" else (*real(text), extra))
    after = _verdict(command)
    # The property is about the level. A form that matches an earlier-ordered forbid rule may change which rule the
    # card names, but never the level: forbid stays forbid.
    assert RANK[after[0]] >= max(RANK[before[0]], RANK[floor]), (command, extra, before, after)


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
    """One of the two forms not read as it is: every rule's command position reads such a run in time far beyond its
    length, so the linear passes read it squeezed."""
    command = "ls" + " " * shell_text._MAX_BLANK_RUN + "x"
    assert command not in tp._detection_texts(command)
    assert shell_text._squeeze_blank_runs(command) in tp._detection_texts(command)


# ── a form that is itself past a limit (blocker 1) ────────────────────────────
# The whole text and its normalized form are under the limits; a `-c` payload or a launcher argument, read on its own,
# is past one: its `$(` openers are split by quotes in the text (counting none there) and whole in the argument. That
# form is the other one not read raw. Main reads it with every rule; this head reads its own squeezed linear passes, so
# a forbid in it still holds instead of dropping to `ask unreadable`.
#
# The stand-in forbid here needs its word and an operand (`zz-target`) on one line, as a real rule reads an operand to
# the end of its line. An inner quote sits between them in the text, so the whole text's own linear passes break the two
# apart (every quote is a line start there) and miss the forbid: only the form read on its own, with that quote gone,
# keeps them together. So the whole-text passes alone are not enough, and the per-form pass is what catches it.
TARGET = "zz-target"
OPERAND_RULE = tp._POS + re.escape(WORD) + r"[^\n]*" + re.escape(TARGET)
SPLIT_SUBST = "$'\"(\"'" * shell_text._MAX_NESTED_SUBSTITUTIONS       # NESTED `$(`, split by quotes in the text
PAST_LIMIT_FORMS = {
    "payload-single": f"sh -c '{WORD} \"q\" {TARGET}; {SPLIT_SUBST} '",
    "payload-bash": f"bash -c '{WORD} \"q\" {TARGET}; {SPLIT_SUBST} '",
    "launcher": f"watch '{WORD} \"q\" {TARGET}; {SPLIT_SUBST} '",
    "launcher-tmux": f"tmux new '{WORD} \"q\" {TARGET}; {SPLIT_SUBST} '",
}


@pytest.fixture
def operand_stand_in(monkeypatch):
    rule = ("stand-in", re.compile(OPERAND_RULE, re.I | re.DOTALL), "a stand-in", False)
    monkeypatch.setattr(tp, "_FORBID_C", [rule, *tp._FORBID_C])
    return rule[1]


@pytest.mark.parametrize("command", PAST_LIMIT_FORMS.values(), ids=PAST_LIMIT_FORMS.keys())
def test_a_forbid_in_a_form_that_is_itself_past_a_limit_still_holds(operand_stand_in, command):
    assert not shell_text.too_complex(command)                              # the whole text is under the limits
    assert any(shell_text.too_complex(form) for form in tp._forms(command))  # but a form of it is past one
    assert not any(operand_stand_in.search(f) for f in shell_text.over_limit_forms(command))  # whole-text passes miss it
    assert _verdict(command) == ("forbid", "stand-in"), command


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


@pytest.mark.parametrize("command", SPLIT_WINS)
def test_a_protected_name_is_read_where_a_split_form_would_win_the_most_lines_pick(monkeypatch, command):
    """The protected-name check reads every form too, not the one with the most lines. Here a split form with more
    lines holds no script, so reading only it (the most-lines pick) would turn `ask protected-write` into `run`. No
    stand-in reach rule is set, so the one reason the command asks is the protected name."""
    monkeypatch.setattr(tp, "_INLINE_SCRIPT", re.compile(tp._POS + re.escape(SCRIPT) + r"\b[^\n]*\s-c\b"))
    monkeypatch.setattr(tp, "_PROTECTED_NAME_C", re.compile(re.escape(REACH)))
    most_lines = max(tp._forms(command), key=_lines)
    assert not any(tp._PROTECTED_NAME_C.search(s) for s in tp._inline_scripts(most_lines))     # a split form would win
    assert any(tp._PROTECTED_NAME_C.search(s) for form in _main_forms(command) for s in tp._inline_scripts(form))
    assert tp.assess(command) == tp.Assessment("ask", "protected-write", tp.describe("protected-write")), command
    assert "protected-write" in tp.ask_rules(command)

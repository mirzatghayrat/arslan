"""S2a-3 step 4: the folder a command runs in, followed through a change of folder within one command.

Stand-ins only (the user's decision, 2026-11-07): the path rules are swapped for a stand-in deleter, writer and finder
and a protected stand-in folder, and chains are built from their structure with stand-in folder names. The differential
runs the real bash in a scratch work folder and a scratch home, with nothing but cd, pushd and echo in it."""
from __future__ import annotations

import os
import posixpath
import re
import subprocess

import pytest

from server.services import shell_grammar, terminal_exec, terminal_policy as tp

A, B, MISSING = "zz-a", "zz-b", "zz-missing"
TOOL = "zz-tool"


def _folders(text: str) -> tuple[str, ...]:
    """The folders of the last command."""
    reading = shell_grammar.read(text)
    assert reading.understood, reading.why
    return reading.folders[-1]


# ── the reader ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, folders", [
    (f"{TOOL}", ("",)),
    (f"cd {A} && {TOOL}", (A,)),
    (f"cd {A} && cd {B} && {TOOL}", (f"{A}/{B}",)),
    (f"pushd {A} && {TOOL}", (A,)),
    (f"cd ~ && {TOOL}", ("~",)),
    (f"cd ~/{A} && {TOOL}", (f"~/{A}",)),
    (f"cd /{A} && cd {B} && {TOOL}", (f"/{A}/{B}",)),
    (f"cd .. && {TOOL}", ("..",)),
])
def test_and_gives_the_new_folder_alone(text, folders):
    assert _folders(text) == folders


@pytest.mark.parametrize("text, folders", [
    pytest.param(f"cd {A} && {TOOL} && cd .. && {TOOL}", ("",), id="fold-work"),
    pytest.param(f"cd {A}/{B} && cd .. && {TOOL}", (A,), id="fold-partial"),
    pytest.param(f"cd {A} && cd ../.. && {TOOL}", ("..",), id="fold-outside"),
    pytest.param(f"cd .. && cd {A} && {TOOL}", (f"../{A}",), id="leading-parent"),
    pytest.param(f"cd ./{A}/. && cd ../. && {TOOL}", ("",), id="fold-dots"),
    pytest.param(f"cd ~/{A} && cd .. && {TOOL}", ("~",), id="fold-home"),
    pytest.param(f"cd ~ && cd .. && {TOOL}", ("~/..",), id="home-parent"),
])
def test_folder_paths_fold_logically(text, folders):
    assert _folders(text) == folders


@pytest.mark.parametrize("join", ["; ", " || ", "\n", " & "])
def test_a_change_that_may_fail_leaves_both_folders(join):
    expected = ("",) if join == " & " else ("", A)        # backgrounded, it never moves this shell
    assert _folders(f"cd {A}{join}{TOOL}") == expected


@pytest.mark.parametrize("text, folders", [
    (f"! cd {A} && {TOOL}", ("", A)),                     # negated: what follows && runs when the change failed
    (f"{TOOL} || cd {A} && {TOOL}", ("", A)),            # after ||, success of the last step says nothing
    (f"cd {A} && {TOOL}; {TOOL}", ("", A)),              # the list after ; runs whether the change worked or not
    (f"cd {A} && {{ {TOOL}; }}; {TOOL}", ("", A)),
    (f"cd {A}; cd {B} && {TOOL}", (f"{A}/{B}", B)),
    (f"{TOOL} || {TOOL} && {TOOL} || cd {A} && {TOOL}", ("", A)),
    (f"if {TOOL}; then cd {A}; fi; {TOOL}", ("", A)),
])
def test_the_folders_after_a_chain(text, folders):
    assert _folders(text) == folders


@pytest.mark.parametrize("text", [
    f"cd {A} | {TOOL}; {TOOL}",
    f"{TOOL} | cd {A}; {TOOL}",
    f"(cd {A}); {TOOL}",
    f"(cd {A}) && {TOOL}",
    f"echo $(cd {A}); {TOOL}",
    f"bash -c 'cd {A}'; {TOOL}",
    f"cd {A} & {TOOL}",
    f"cd {A} && {TOOL} & {TOOL}",
])
def test_a_change_in_a_subshell_stays_there(text):
    assert _folders(text) == ("",)


@pytest.mark.parametrize("text", [
    f"(cd {A} && {TOOL})",
    f"echo $(cd {A} && {TOOL})",
    f"bash -c 'cd {A} && {TOOL}'",
    f"{{ cd {A} && {TOOL}; }} | {TOOL} x",
])
def test_inside_the_subshell_the_change_holds(text):
    reading = shell_grammar.read(text)
    assert reading.understood, reading.why
    assert reading.folders[reading.commands.index((TOOL,))] == (A,)


def test_a_redirection_is_opened_where_its_command_runs():
    reading = shell_grammar.read(f"cd {A} > zz-out-1 && {TOOL} >> zz-out-2 2>&1 <zz-in")
    assert reading.writes == (("zz-out-1", ("",)), ("zz-out-2", (A,)))


@pytest.mark.parametrize("text", [
    "cd",                                   # home
    "cd -",                                 # the last folder
    f"cd -P {A}", f"cd -L {A}", f"cd -- {A}",
    "popd", f"popd; cd {A}",
    "pushd", "pushd +1", "pushd -1",        # a stack index
    "cd ~zz-user",                          # another user's home
    f"cd '~'/{A}", f"cd \"~/{A}\"",          # a folder named ~, or not: quoted, it isn't read
    f"cd ${A.replace('-', '_')}", f"cd \"$(echo {A})\"", "cd zz-*",
    f"cd {A} {B}",
    "cd ''",
    f"CDPATH={A} cd {B}",
    f"command cd {A}", f"time cd {A}", f"exec cd {A}",
    f"for x in 1 2; do cd {A}; done",
    f"while {TOOL}; do cd {A}; done",
    f"until cd {A}; do {TOOL}; done",
])
def test_a_change_the_reader_cannot_follow_is_not_understood(text):
    assert not shell_grammar.read(text).understood


def test_a_change_in_a_subshell_in_a_loop_is_not_followed_either():
    assert not shell_grammar.read(f"for x in 1; do (cd {A}); done").understood


def test_too_many_folders_at_once_is_capped():
    fits = "; ".join([f"cd {A}"] * (shell_grammar.MAX_FOLDERS - 1))
    assert len(_folders(f"{fits}; {TOOL}")) == shell_grammar.MAX_FOLDERS
    reading = shell_grammar.read(f"{fits}; cd {A}; {TOOL}")
    assert not reading.understood and reading.capped


# ── the real bash agrees ─────────────────────────────────────────────────────

_CHAINS = [
    "cd {a} && {p}",
    "cd {m} && {p}; {p}",
    "cd {m}; {p}",
    "cd {m} || {p}",
    "cd {a}; {p}; cd {b} && {p}; {p}",
    "cd {a} && cd {m} && {p}; {p}",
    "cd {a} && cd {m}; {p}",
    "! cd {m} && {p}",
    "! cd {a} || {p}",
    "cd {a} | {p}; {p}",
    "(cd {a} && {p}); {p}",
    "echo $(cd {a} && {p}); {p}",
    "bash -c 'cd {a} && {p}'; {p}",
    "{ cd {a}; {p}; }; {p}",
    "if cd {m}; then {p}; else {p}; fi; {p}",
    "cd ~ && {p}",
    "cd ~/{a} && cd .. && {p}",
    "pushd {a} > /dev/null && {p}",
    "cd {a} && cd .. && cd {a}/{b} && {p}",
    "cd {a} && {p} && cd .. && {p}",
]


def _home_form(path: str, work: str, home: str) -> str:
    if path == work or path.startswith(work + "/"):
        return posixpath.relpath(path, work) if path != work else ""
    assert path == home or path.startswith(home + "/"), path
    return "~" if path == home else "~/" + posixpath.relpath(path, home)


def _normal(folder: str) -> str:
    if folder in ("", "~"):
        return folder
    normal = posixpath.normpath(folder)
    return "" if normal == "." else normal


@pytest.mark.parametrize("chain", _CHAINS)
def test_every_folder_bash_runs_a_command_in_is_one_the_reader_names(chain, tmp_path):
    home, work = (tmp_path / "home").resolve(), (tmp_path / "home" / "work").resolve()
    for folder in (work / A / B, home / A):
        folder.mkdir(parents=True, exist_ok=True)
    marks = iter(range(100))
    text = chain.replace("{a}", A).replace("{b}", B).replace("{m}", MISSING)
    text = re.sub(r"\{p\}", lambda _: f'echo {next(marks)} "$PWD"', text)
    reading = shell_grammar.read(text)
    assert reading.understood, reading.why
    named = {c[1]: set(folders)
             for c, folders in zip(reading.commands, reading.folders) if c[0] == "echo" and c[1].isdigit()}
    ran = subprocess.run([*terminal_exec.SHELL, "-c", text], cwd=work, capture_output=True, text=True, timeout=10,
                         env={"PATH": "/usr/bin:/bin", "HOME": str(home)})
    seen = [line.split(" ", 1) for line in ran.stdout.splitlines() if line.split(" ", 1)[0].isdigit()]
    assert seen, ran.stderr
    for mark, path in seen:
        actual = _home_form(path, str(work), str(home))
        assert _normal(actual) in named[mark], (mark, actual, named[mark])


# ── the path rules, through a stand-in ───────────────────────────────────────

DEL, PUT, FIND = "zz-del", "zz-put", "zz-find"
GUARDED = "zz-guarded"


@pytest.fixture(autouse=True)
def stand_in_rules(monkeypatch):
    monkeypatch.setattr(tp, "_MOVED_DELETERS", frozenset({DEL}))
    monkeypatch.setattr(tp, "_MOVED_WRITERS", frozenset({PUT}))
    monkeypatch.setattr(tp, "_MOVED_FINDERS", frozenset({FIND}))
    monkeypatch.setattr(tp, "_PROTECTED_PATH_C", re.compile(r"~/" + GUARDED + r"(?:/|$)"))
    tp._after_moves.cache_clear()
    yield
    tp._after_moves.cache_clear()


def _verdict(text: str) -> tuple[str, str]:
    a = tp.assess(text)
    return a.level, a.rule


@pytest.mark.parametrize("text", [
    f"{DEL} zz-file",                               # no change of folder: the stand-in is none of main's rules
    f"cd {A} && {DEL} zz-file",
    f"cd {A}/{B} && {DEL} zz-file",
    f"(cd ~); {DEL} zz-file",
    f"cd ~ | {TOOL}; {DEL} zz-file",
    f"cd ~ & {DEL} zz-file",
    f"cd {A} && {DEL} -f zz-file",
    pytest.param(f"cd {A} && {TOOL} && cd .. && {DEL} zz-file", id="fold-delete-work"),
    pytest.param(f"cd {A}/{B} && cd .. && {DEL} zz-file", id="fold-delete-partial"),
])
def test_a_delete_in_the_work_folder_runs(text):
    assert _verdict(text) == ("run", "")


@pytest.mark.parametrize("text", [
    f"cd ~ && {DEL} zz-file",
    f"cd ~; {DEL} zz-file",                         # either folder: one of them is outside
    f"cd .. && {DEL} zz-file",
    f"cd /{A} && {DEL} zz-file",
    f"cd {A} && cd ../.. && {DEL} zz-file",
    f"cd ~ && {DEL}",                               # no operand: it can't say what goes
    f"(cd ~ && {DEL} zz-file)",
    f"echo $(cd ~ && {DEL} zz-file)",
    f"bash -c 'cd ~ && {DEL} zz-file'",
    f"cd ~ && nohup {DEL} zz-file",                 # through a wrapper
    f"cd ~ && {FIND} zz-dir -delete",
    f"cd ~ && {FIND} -delete",
    f"if {TOOL}; then cd ~; fi; {DEL} zz-file",
    pytest.param(f"cd ~ && echo $({DEL} zz-file)", id="outer-substitution"),
    pytest.param(f"cd ~ && bash -c '{DEL} zz-file'", id="outer-shell"),
    pytest.param(f"cd ..; cd {A} && {DEL} zz-file", id="every-folder"),
    pytest.param(f"cd .. && cd {A} && {DEL} zz-file", id="leading-parent-delete"),
    pytest.param(f"cd {A}/{B} && cd .. && {DEL} ../zz-file", id="operand-parent"),
])
def test_a_delete_after_moving_outside_asks(text):
    assert _verdict(text) == ("ask", "delete-outside")


@pytest.mark.parametrize("text", [
    f"cd ~ && {TOOL} > {GUARDED}/zz-file",
    f"cd ~ && {TOOL} >> {GUARDED}",
    f"cd ~; {TOOL} &> {GUARDED}/zz-file",
    f"cd ~ && {PUT} zz-file {GUARDED}/zz-file",
    f"cd ~ && {PUT} of={GUARDED}/zz-file",
    f"cd ~/{GUARDED} && {PUT} zz-file",
    f"cd ~/{A} && {PUT} ../{GUARDED}/zz-file",       # normalized
    f"cd ~/{A} && {TOOL} > ../{GUARDED}/zz-file",
    pytest.param(f"cd ~ && {TOOL} <> {GUARDED}/zz-file", id="read-write"),
    pytest.param(f"cd {A} && cd ~ && {TOOL} > {GUARDED}/zz-file", id="home-after-move"),
])
def test_a_write_into_the_protected_folder_after_moving_asks(text):
    assert _verdict(text) == ("ask", "protected-write")


@pytest.mark.parametrize("text", [
    f"cd {A} && {PUT} {GUARDED}/zz-file",            # a folder of that name inside the work folder
    f"cd {A} && {TOOL} > {GUARDED}/zz-file",
    f"cd ~ && {PUT} {A}/zz-file",
    f"cd ~ && {TOOL} > {A}/zz-file",
    f"cd ~ && {TOOL} < {GUARDED}/zz-file",           # read, not written
    f"{TOOL} > {GUARDED}/zz-file",
    f"(cd ~); {TOOL} > {GUARDED}/zz-file",
])
def test_other_writes_run(text):
    assert _verdict(text) == ("run", "")


def test_a_command_the_reader_does_not_understand_is_judged_as_before():
    """Step 3 wires `not understood` itself; here only the folders of understood text are followed."""
    assert not shell_grammar.read(f"cd; {DEL} zz-file").understood
    assert tp._after_moves(f"cd; {DEL} zz-file") == (False, False)


def test_the_card_lists_the_rule():
    assert tp.ask_rules(f"cd ~ && {DEL} zz-file") == {"delete-outside"}
    assert tp.ask_rules(f"cd ~ && {TOOL} > {GUARDED}") == {"protected-write"}


def test_the_stand_ins_are_not_real_programs():
    for name in (DEL, PUT, FIND, TOOL):
        assert not any(os.path.exists(os.path.join(d, name)) for d in ("/bin", "/usr/bin", "/usr/local/bin",
                                                                          "/opt/homebrew/bin"))

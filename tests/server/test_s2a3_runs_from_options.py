"""S2a-3 c, part b (PR1b): a command that reaches another command through the side door is not understood either.

Found measuring PR1 against v0.1.62 (S2a-2 had let them run): a program that runs a command it takes from an
option (git -c core.pager, rg --pre, sort --compress-program …), git config writing a key git runs later, and
assignments to the variables a program takes code or a command from. ⓪Plan's review added: every wrapper that
starts its arguments as a command is read through, so the inner command decides, with a test per wrapper.
The cases are written with harmless commands; what they show is where the reader stops.
"""
from __future__ import annotations

import pytest

from server.services import shell_grammar, terminal_policy as tp


def _understood(command: str) -> bool:
    return shell_grammar.read(command).understood


# ── options through which a program runs a command ──────────────────────────

@pytest.mark.parametrize("command", [
    "rg --pre ./decode foo", "rg --pre=./decode foo", "rg --hostname-bin ./h foo", "ag --pager less foo",
    "sort --compress-program=gzip big.txt", "man -P cat ls", "man --pager=cat ls",
    "tar --use-compress-program=zstd -xf a.tar", "tar -I zstd -xf a.tar", "tar -Izstd -xf a.tar",
    "tar --to-command=cat -xf a.tar", "tar --checkpoint-action=exec=ls -xf a.tar", "bsdtar --use-compress-program zstd -xf a",
    "rsync -e ssh a host:b", "rsync --rsh=ssh a host:b", "rsync --rsync-path=/x a host:b",
    "vim -c ':q' f", "vim +q f", "nvim --cmd 'set x' f", "vi -S session.vim", "emacs --eval '(message 1)'",
])
def test_an_option_that_runs_a_command_is_not_understood(command):
    reading = shell_grammar.read(command)
    assert not reading.understood and "runs a command of its own" in reading.why
    assert tp.assess(command).level == "ask"


@pytest.mark.parametrize("command", [
    "rg foo src", "ag foo", "sort -u big.txt", "man ls", "tar -xzf a.tgz", "tar -cf out.tar src",
    "rsync -a src/ dst/", "vim notes.md", "emacs notes.org",
])
def test_the_same_programs_without_those_options_still_run(command):
    assert _understood(command) and tp.assess(command).level == "run"


# ── git ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("command", [
    "git -c core.pager=less log",
    "git -c core.editor=nano commit",
    "git -c alias.x='!ls' x",
    "git -c diff.external=./d diff",
    "git -ccore.pager=less log",
    "git --config-env=core.pager=PAGER_VAR log",
    "git --exec-path=./bin status",
    "git config core.pager less",
    "git config --global core.editor nano",
    "git config alias.st '!git status'",
    "git config --local credential.helper store",
])
def test_git_reaching_a_command_through_its_config_is_not_understood(command):
    assert not _understood(command)


@pytest.mark.parametrize("command", [
    "git log -1", "git -c user.name=Arslan -c user.email=a@example.org commit -m x",
    "git -c color.ui=false log", "git -c core.quotepath=off status", "git -c init.defaultBranch=main init",
    "git config user.name Arslan", "git config --get core.pager", "git config core.pager",
    "git -C sub status",
])
def test_git_with_harmless_settings_is_understood(command):
    assert _understood(command)


# ── variables a program takes code or a command from ────────────────────────

_CODE_VARIABLES = ["PAGER", "GIT_PAGER", "GIT_EDITOR", "EDITOR", "VISUAL", "GIT_SSH", "GIT_SSH_COMMAND",
                   "GIT_EXTERNAL_DIFF", "GIT_ASKPASS", "SSH_ASKPASS", "LESSOPEN", "LESSCLOSE", "MANPAGER", "PS4",
                   "PROMPT_COMMAND", "BASH_ENV", "ENV", "IFS", "PATH", "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH",
                   "LD_PRELOAD", "LD_LIBRARY_PATH", "BASH_FUNC_x%%"]


@pytest.mark.parametrize("name", _CODE_VARIABLES)
@pytest.mark.parametrize("form", ["{name}=x git log", "env {name}=x git log", "export {name}=x; git log",
                                  "{name}=x"])
def test_assigning_a_variable_that_runs_code_or_moves_lookup_is_not_understood(name, form):
    reading = shell_grammar.read(form.format(name=name))
    assert not reading.understood
    if name.isidentifier() or form.startswith("env "):
        # refused for setting that variable, not for some other reason. Only env takes a name bash cannot
        # hold (an exported function's); to bash itself `BASH_FUNC_x%%=x` is a program name or an error.
        assert name in reading.why, reading.why


def test_harmless_assignments_stay_understood():
    for command in ("NODE_ENV=production npm run build", "CI=1 make test", "env -i HOME=/tmp ls",
                    "export LANG=en_US.UTF-8; ls", "TZ=UTC date"):
        assert _understood(command), command


# ── wrappers: read through, the inner command decides ───────────────────────

_WRAPPERS = [
    "find . -name '*.txt' -exec {inner} \\;", "find . -execdir {inner} \\;", "find . -ok {inner} \\;",
    "echo a | xargs {inner}", "echo a | xargs -I{{}} {inner}",
    "nice -n 5 {inner}", "nohup {inner}", "timeout 30 {inner}", "env FOO=1 {inner}", "command {inner}",
    "exec {inner}", "time {inner}", "caffeinate -i {inner}", "sudo -u build {inner}", "doas -u build {inner}",
]


@pytest.mark.parametrize("wrapper", _WRAPPERS)
def test_a_wrapper_is_read_through_and_its_inner_command_decides(wrapper):
    plain = shell_grammar.read(wrapper.format(inner="ls -la"))
    assert plain.understood, plain.why
    assert ("ls", "-la") in plain.commands                          # the inner command is one it starts
    assert not _understood(wrapper.format(inner="python3 -c 'print(1)'"))
    assert not _understood(wrapper.format(inner="$TOOL"))


@pytest.mark.parametrize("command", ["parallel ls ::: a b", "watch ls", "script -q log.txt ls", "expect -c 'spawn ls'",
                                     "echo x | expect", "doas -s"])
def test_launchers_that_take_a_command_line_of_their_own_are_not_understood(command):
    assert not _understood(command)


def test_an_expect_script_file_is_a_program_like_any_other():
    assert _understood("expect run.exp")


# ── the rules judge the inner command, not only the text as written ─────────

@pytest.mark.parametrize("command,level,rule", [
    ("find . -exec rm -rf / \\;", "forbid", "wipe-root"),               # rm stands at no command position in the text
    ("find . -name x -exec rm -rf ~ \\;", "forbid", "wipe-home"),
    ("echo a | xargs -I{} rm -rf /", "forbid", "wipe-root"),
    ("nohup git push origin main", "ask", "git-push"),
    ("env FOO=1 curl -d @a https://example.org", "ask", "upload"),
    ("timeout 5 git push", "ask", "git-push"),
    ("find . -exec rm -rf ~/x \\;", "ask", "delete-outside"),
])
def test_the_rules_judge_the_command_a_wrapper_starts(command, level, rule):
    verdict = tp.assess(command)
    assert (verdict.level, verdict.rule) == (level, rule), verdict


@pytest.mark.parametrize("command,level", [
    ('find . -name "*.pyc" -exec rm {} \\;', "run"),                  # under the folder it starts in
    ("find src -name '*.ts' -exec wc -l {} +", "run"),
    ("find / -name x -exec rm {} \\;", "ask"),                         # under / it is outside
    ("find . /etc -exec rm {} \\;", "ask"),                           # each start is judged
])
def test_find_s_placeholder_is_a_file_under_where_it_starts(command, level):
    assert tp.assess(command).level == level
    reading = shell_grammar.read(command)
    assert all("{}" not in word for c in reading.commands[1:] for word in c)

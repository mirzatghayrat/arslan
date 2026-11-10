"""HR-1 (v0.1.64): the files that make something run later, and where the kernel holds them.

- The list (server/services/run_later.py): its SBPL regexes and `matches` agree on a table of plain paths, at any
  depth, and leave ordinary look-alikes (instruction files, the rest of `.git`, other files in `.github`) alone.
- The profile texts: the denies come after every grant and reopen in the commands profile, after the grants in the
  MCP preset, and in the outside floor only when given the work folder.
- `core.hooksPath`: read, never run; its target is denied; an error reading it builds no profile, so the command
  doesn't start.
- The gate: only a click on the command's own card lifts the hold outside the sandbox; under this conversation's
  grant with no such click, the outside floor keeps it.

The real-seatbelt cases are in tests/server/sbx/test_hr1_run_later_kernel.py. Stand-in names and plain paths only:
the bypass shapes (letter case, Unicode forms, renames, links, `.git` files, submodules, bare repositories) are
Codex's corpus.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from server.orchestrator import command_gate, tool_loop, untrusted
from server.services import (capability_sandbox, command_sandbox, permissions, run_later, settings_service,
                             terminal_exec)

STAND_IN = "zz-stand-in-word"

#: The names' regexes, one deny line per family in run_later.FAMILIES' order. Every profile writes each regex
#: wrapped as `(require-all <regex> DEPENDENCY_TEXT)` (RUN_LATER_TEXT below).
RUN_LATER_REGEXES = """\
(deny file-write* (regex #"^.*/[.][Gg][Ii][Tt]/[Hh][Oo][Oo][Kk][Ss](/.*)?$") (regex #"^.*/[.][Gg][Ii][Tt]/[Cc][Oo][Nn][Ff][Ii][Gg]$") (regex #"^.*/[.][Gg][Ii][Tt]/[Cc][Oo][Nn][Ff][Ii][Gg][.][Ww][Oo][Rr][Kk][Tt][Rr][Ee][Ee]$") (regex #"^.*/[.][Gg][Ii][Tt]/[Ww][Oo][Rr][Kk][Tt][Rr][Ee][Ee][Ss]/[^/]*/[Cc][Oo][Nn][Ff][Ii][Gg][.][Ww][Oo][Rr][Kk][Tt][Rr][Ee][Ee]$") (regex #"^.*/[.][Gg][Ii][Tt]/[Mm][Oo][Dd][Uu][Ll][Ee][Ss]/[^/]*/[Hh][Oo][Oo][Kk][Ss](/.*)?$") (regex #"^.*/[.][Gg][Ii][Tt]/[Mm][Oo][Dd][Uu][Ll][Ee][Ss]/[^/]*/[Cc][Oo][Nn][Ff][Ii][Gg]$") (regex #"^.*/[.][Gg][Ii][Tt][Mm][Oo][Dd][Uu][Ll][Ee][Ss]$"))
(deny file-write* (regex #"^.*/[.][Ee][Nn][Vv][Rr][Cc]$"))
(deny file-write* (regex #"^.*/[.][Vv][Ss][Cc][Oo][Dd][Ee]/[Tt][Aa][Ss][Kk][Ss][.][Jj][Ss][Oo][Nn]$") (regex #"^.*/[.][Vv][Ss][Cc][Oo][Dd][Ee]/[Ll][Aa][Uu][Nn][Cc][Hh][.][Jj][Ss][Oo][Nn]$") (regex #"^.*/[.][Vv][Ss][Cc][Oo][Dd][Ee]/[Ss][Ee][Tt][Tt][Ii][Nn][Gg][Ss][.][Jj][Ss][Oo][Nn]$") (regex #"^.*/[.][Vv][Ss][Cc][Oo][Dd][Ee]/[Mm][Cc][Pp][.][Jj][Ss][Oo][Nn]$") (regex #"^.*/[^/]*[.][Cc][Oo][Dd][Ee]-[Ww][Oo][Rr][Kk][Ss][Pp][Aa][Cc][Ee]$"))
(deny file-write* (regex #"^.*/[.][Cc][Ll][Aa][Uu][Dd][Ee]/[Ss][Ee][Tt][Tt][Ii][Nn][Gg][Ss][^/]*[.][Jj][Ss][Oo][Nn]$") (regex #"^.*/[.][Cc][Ll][Aa][Uu][Dd][Ee]/[Ll][Aa][Uu][Nn][Cc][Hh][.][Jj][Ss][Oo][Nn]$") (regex #"^.*/[.][Mm][Cc][Pp][.][Jj][Ss][Oo][Nn]$") (regex #"^.*/[.][Cc][Oo][Dd][Ee][Xx]/[Cc][Oo][Nn][Ff][Ii][Gg][.][Tt][Oo][Mm][Ll]$") (regex #"^.*/[.][Gg][Ee][Mm][Ii][Nn][Ii]/[Ss][Ee][Tt][Tt][Ii][Nn][Gg][Ss][.][Jj][Ss][Oo][Nn]$") (regex #"^.*/[.][Cc][Uu][Rr][Ss][Oo][Rr]/[^/]*[.][Jj][Ss][Oo][Nn]$"))
(deny file-write* (regex #"^.*/[.][Nn][Pp][Mm][Rr][Cc]$") (regex #"^.*/[.][Yy][Aa][Rr][Nn][Rr][Cc]$") (regex #"^.*/[.][Yy][Aa][Rr][Nn][Rr][Cc][.][Yy][Mm][Ll]$") (regex #"^.*/[Pp][Ii][Pp][.][Cc][Oo][Nn][Ff]$") (regex #"^.*/[Uu][Vv][.][Tt][Oo][Mm][Ll]$"))
(deny file-write* (regex #"^.*/[.][Pp][Rr][Ee]-[Cc][Oo][Mm][Mm][Ii][Tt]-[Cc][Oo][Nn][Ff][Ii][Gg][.][Yy][Aa][Mm][Ll]$") (regex #"^.*/[.][Hh][Uu][Ss][Kk][Yy](/.*)?$"))
"""

# (path, family): each name at more than one depth, and the /System/Volumes/Data spelling of a path.
HELD = [
    ("/w/.git/hooks/pre-commit", "git"), ("/w/.git/hooks", "git"), ("/w/a/b/.git/hooks/zz/x", "git"),
    ("/w/.git/config", "git"), ("/w/a/.git/config", "git"), ("/System/Volumes/Data/w/.git/config", "git"),
    ("/w/.git/config.worktree", "git"), (f"/w/.git/worktrees/{STAND_IN}/config.worktree", "git"),
    (f"/w/.git/modules/{STAND_IN}/hooks/post-checkout", "git"), (f"/w/.git/modules/{STAND_IN}/config", "git"),
    ("/w/.gitmodules", "git"), ("/w/sub/.gitmodules", "git"),
    ("/w/.envrc", "envrc"), ("/w/a/b/.envrc", "envrc"),
    ("/w/.vscode/tasks.json", "editor"), ("/w/.vscode/launch.json", "editor"), ("/w/.vscode/settings.json", "editor"),
    ("/w/.vscode/mcp.json", "editor"), (f"/w/{STAND_IN}.code-workspace", "editor"), ("/w/a/.vscode/tasks.json", "editor"),
    ("/w/.claude/settings.json", "agent"), ("/w/.claude/settings.local.json", "agent"),
    ("/w/.claude/launch.json", "agent"), ("/w/.mcp.json", "agent"), ("/w/a/.mcp.json", "agent"),
    ("/w/.codex/config.toml", "agent"), ("/w/.gemini/settings.json", "agent"), ("/w/.cursor/mcp.json", "agent"),
    ("/w/.cursor/hooks.json", "agent"),
    ("/w/.npmrc", "package"), ("/w/a/.npmrc", "package"), ("/w/.yarnrc", "package"), ("/w/.yarnrc.yml", "package"),
    ("/w/.venv/pip.conf", "package"), ("/w/uv.toml", "package"),
    ("/w/.pre-commit-config.yaml", "hooks"), ("/w/.husky/pre-commit", "hooks"), ("/w/.husky/_/h", "hooks"),
    ("/w/.husky", "hooks"),
]
#: CI files: recognised (`is_ci_file`, for HR-2b's push card), not held (the user's list decision, #813 review 3).
CI = [f"/w/.github/workflows/{STAND_IN}.yml", "/w/.github/workflows", "/w/x/.gitlab-ci.yml", "/w/.gitlab-ci.yml",
      "/w/.circleci/config.yml", "/w/.circleci", "/w/azure-pipelines.yml", "/w/Jenkinsfile", "/w/sub/Jenkinsfile",
      "/w/bitbucket-pipelines.yml", f".github/workflows/{STAND_IN}.yml", "/w/.GitHub/Workflows/x.yml"]
# Ordinary files: the instruction files (the user's ruling), CI files, the rest of `.git`, and names beside the held
# ones.
ORDINARY = [*CI,
    "/w/AGENTS.md", "/w/CLAUDE.md", "/w/CLAUDE.local.md", "/w/GEMINI.md", "/w/.cursorrules", "/w/a/AGENTS.md",
    "/w/.claude/CLAUDE.md", f"/w/.claude/commands/{STAND_IN}.md", f"/w/.claude/agents/{STAND_IN}.md",
    f"/w/.cursor/rules/{STAND_IN}.mdc", f"/w/.codex/{STAND_IN}.md", "/w/.gemini/GEMINI.md",
    "/w/.github/README.md", "/w/.github/FUNDING.yml", "/w/.github/CODEOWNERS", "/w/.github/workflows-notes.md",
    "/w/.git/objects/ab/cdef0123", "/w/.git/HEAD", "/w/.git/index", "/w/.git/refs/heads/main",
    "/w/.git/description", "/w/.git/COMMIT_EDITMSG", "/w/.git/info/exclude", "/w/.git/config.lock.d/x",
    "/w/.gitignore", "/w/.gitattributes", "/w/src/config", "/w/git/hooks/x", "/w/hooks/pre-commit",
    "/w/.vscode/extensions.json", f"/w/{STAND_IN}.code-workspace.bak", "/w/.envrc.example", "/w/.npmrc.d/x",
    "/w/package.json", "/w/Makefile", "/w/pyproject.toml", "/w/zz/uv.lock", f"/w/{STAND_IN}.txt",
]


def _regexes() -> list[str]:
    return [run_later.pattern_regex(p) for _, patterns in run_later.FAMILIES for p in patterns]


#: Every name's regex is written as `(require-all <regex> <this>)`: never inside a dependency folder (#813 review).
DEPENDENCY_TEXT = '(require-not (regex #"^.*/([Nn][Oo][Dd][Ee]_[Mm][Oo][Dd][Uu][Ll][Ee][Ss])/.*$"))'
#: The run-later denies, exactly as every profile writes them.
RUN_LATER_TEXT = re.sub(r'(\(regex #"[^"]*"\))', lambda m: f"(require-all {m.group(1)} {DEPENDENCY_TEXT})",
                        RUN_LATER_REGEXES)


def _by_regex(path: str) -> bool:
    # The SBPL text is POSIX extended syntax that Python's re reads the same way (classes, groups, ?, *, anchors).
    return (any(re.fullmatch(r, path) for r in _regexes())
            and not re.fullmatch(run_later.dependency_regex(), path))


# ── the list: two forms that agree ───────────────────────────────────────────

def test_the_kernel_text_is_these_rules(tmp_path):
    lines = "".join("(deny file-write* " + " ".join(f) + ")\n" for f in run_later.kernel_filters([tmp_path]))
    assert lines == RUN_LATER_TEXT and RUN_LATER_TEXT.count("(require-all ") == RUN_LATER_REGEXES.count("(regex ")
    assert [name for name, _ in run_later.FAMILIES] == ["git", "envrc", "editor", "agent", "package", "hooks"]


@pytest.mark.parametrize("path, family", HELD)
def test_a_held_name_matches_at_any_depth_in_both_forms(path, family):
    assert run_later.family(path) == family
    assert run_later.matches(path) and run_later.matches(Path(path)) and _by_regex(path)


@pytest.mark.parametrize("path", ORDINARY)
def test_an_ordinary_look_alike_matches_neither_form(path):
    assert not run_later.matches(path) and not _by_regex(path)


@pytest.mark.parametrize("path", ORDINARY)
def test_ci_files_are_recognised_for_the_push_card_and_nothing_else_is(path):
    """#813 review 3: their guard moves to HR-2b's push card, which names a pushed change to one."""
    assert run_later.is_ci_file(path) is (path in CI)


def test_ci_files_are_kept_out_of_the_kernel_text(tmp_path):
    text = "".join(" ".join(f) for f in run_later.kernel_filters([tmp_path]))
    assert "[Ww][Oo][Rr][Kk][Ff][Ll][Oo][Ww][Ss]" not in text and "[Jj][Ee][Nn][Kk][Ii][Nn][Ss]" not in text
    assert all(run_later.pattern_regex(p) not in text for p in run_later.CI_FILES)
    assert all(run_later.is_ci_file(f"/w/{p.removesuffix('/**')}") for p in run_later.CI_FILES)


DEPENDENCY = [f"/w/node_modules/{STAND_IN}/.vscode/tasks.json", f"/w/node_modules/{STAND_IN}/.vscode/settings.json",
              f"/w/a/node_modules/@{STAND_IN}/x/.husky/pre-commit", f"/w/NODE_MODULES/{STAND_IN}/.npmrc"]
# The same names outside a dependency folder: a component that only contains the word is not one.
NOT_DEPENDENCY = ["/w/.vscode/tasks.json", f"/w/{STAND_IN}-lib/.vscode/settings.json",
                  "/w/not-node_modules/.vscode/tasks.json", "/w/node_modules_x/.vscode/settings.json",
                  "/w/node_modules.bak/.npmrc", "/w/node_modules"]


@pytest.mark.parametrize("path", DEPENDENCY)
def test_a_dependency_folder_holds_ordinary_files_in_both_forms(path):
    assert not run_later.matches(path) and not _by_regex(path)


@pytest.mark.parametrize("path", NOT_DEPENDENCY)
def test_the_same_names_outside_a_dependency_folder_stay_held(path):
    if path.endswith("/node_modules"):
        assert not run_later.matches(path)                        # an ordinary name, and no folder above it
        return
    assert run_later.matches(path) and _by_regex(path)


def test_a_substring_exemption_would_be_caught():
    """Mutant: any path containing the word, rather than the folder as a component, is exempt."""
    substring = "^.*node_modules.*$"
    held = [p for p in NOT_DEPENDENCY if "node_modules" in p and not p.endswith("/node_modules")]
    assert all(re.fullmatch(substring, p) for p in held)          # the mutant would exempt them: the test above refuses
    assert not any(re.fullmatch(run_later.dependency_regex(), p) for p in held)


#: #813 review 2: roots whose own path passes through a dependency folder (the folder itself included).
INSIDE_DEPENDENCY_ROOTS = [f"/n/node_modules/{STAND_IN}/repo", "/n/node_modules", f"/n/NODE_MODULES/{STAND_IN}"]


@pytest.mark.parametrize("root", INSIDE_DEPENDENCY_ROOTS)
def test_a_root_inside_a_dependency_folder_keeps_every_name_held(root):
    """A repository kept inside node_modules: nothing exempts its names, not even a nested node_modules below it."""
    assert not run_later.exempts([root])
    for rest, family in [(".vscode/tasks.json", "editor"), (".git/hooks/pre-commit", "git"),
                         (f"node_modules/{STAND_IN}/.npmrc", "package"), ("a/node_modules/x/.husky/h", "hooks")]:
        assert run_later.family(f"{root}/{rest}", root) == family and run_later.matches(f"{root}/{rest}", root)


def test_below_an_ordinary_root_a_nested_dependency_folder_stays_exempt():
    assert run_later.exempts(["/w", "/w/node_modules_x", "/w/not-node_modules"])
    for path in DEPENDENCY:
        assert run_later.family(path, "/w") is None and not run_later.matches(path, "/w")
    assert run_later.matches("/w/.vscode/tasks.json", "/w")
    assert run_later.family(DEPENDENCY[0]) is None                # no root: a dependency folder anywhere exempts


def test_the_kernel_text_has_no_exemption_for_a_root_inside_a_dependency_folder(home, tmp_path):
    """The bare regexes, for the work folder by its real path: a link with an ordinary name gains nothing."""
    inside = tmp_path / "node_modules" / STAND_IN / "repo"
    inside.mkdir(parents=True)
    (tmp_path / f"{STAND_IN}-link").symlink_to(inside)
    for folders, roots in [([inside], []), ([tmp_path / f"{STAND_IN}-link"], []), ([tmp_path / "node_modules"], []),
                           ([tmp_path], [inside])]:
        lines = "".join("(deny file-write* " + " ".join(f) + ")\n" for f in run_later.kernel_filters(folders,
                                                                                                    roots=roots))
        assert lines == RUN_LATER_REGEXES and "require-not" not in lines
    # And in the profiles: the commands preset for that work folder, the MCP preset for a grant there.
    assert RUN_LATER_REGEXES.splitlines()[0] in command_sandbox.commands_profile(inside).splitlines()
    mcp = capability_sandbox.profile(root=home / "mcp", folders=[str(inside)], network=False, read=[])
    assert RUN_LATER_REGEXES.splitlines()[0] in mcp.splitlines() and DEPENDENCY_TEXT not in mcp


def test_a_relative_path_is_matched_by_its_names():
    assert run_later.matches(".envrc") and run_later.matches("a/.git/hooks/x") and not run_later.matches("AGENTS.md")


def test_a_name_outside_the_regex_alphabet_is_refused():
    for bad in ('a"b', "a b", "a/b", "", "a\\b"):
        with pytest.raises(ValueError):
            run_later._component(bad)


# ── where the profiles put them ──────────────────────────────────────────────

def _lines() -> list[str]:
    return RUN_LATER_TEXT.splitlines()


@pytest.fixture
def home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    (home / "ws").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


def test_in_the_commands_profile_they_come_after_the_reopen_and_the_shared_caches(home):
    desk = home / "Desktop"
    (desk / "ws").mkdir(parents=True)
    text = command_sandbox.commands_profile(desk / "ws", closed=[desk]).splitlines()
    reopen = text.index(f'(allow file-read* file-write* file-map-executable (subpath "{os.path.realpath(desk / "ws")}"))')
    caches = next(i for i, line in enumerate(text) if line.startswith("(deny file-write* (subpath") and ".npm" in line)
    first = text.index(_lines()[0])
    assert reopen < caches < first and text[first:first + len(_lines())] == _lines()
    # Every write grant comes before them, so none can override them (the last matching rule wins).
    grants = [i for i, line in enumerate(text) if line.startswith("(allow") and "file-write" in line]
    assert grants and max(grants) < first


def test_in_the_mcp_preset_they_come_after_its_grants(home):
    granted = home / "granted"
    granted.mkdir()
    text = capability_sandbox.profile(root=home / "mcp", folders=[str(granted)], network=False, read=[]).splitlines()
    first = text.index(_lines()[0])
    assert text[first:first + len(_lines())] == _lines()
    grants = [i for i, line in enumerate(text) if line.startswith("(allow") and "file-write" in line]
    assert grants and max(grants) < first


def test_the_outside_floor_holds_them_only_when_given_the_work_folder(home):
    assert _lines()[0] not in command_sandbox.minimal_profile()
    text = command_sandbox.minimal_profile(run_later_in=home / "ws").splitlines()
    first = text.index(_lines()[0])
    cap6b = next(i for i, line in enumerate(text) if ".agents/skills" in line and line.startswith("(deny file-read*"))
    assert cap6b < first and text[first:first + len(_lines())] == _lines()
    assert all(not line.startswith("(allow") or "file-write" not in line for line in text)


# ── core.hooksPath ───────────────────────────────────────────────────────────

def _repo(folder: Path, config: str) -> Path:
    (folder / ".git").mkdir(parents=True)
    (folder / ".git" / "config").write_text(config)
    return folder


@pytest.mark.parametrize("config, expected", [
    (f"[core]\n\thooksPath = {STAND_IN}\n", STAND_IN),
    (f'[core]\n\tbare = false\n[CORE]\n\tHooksPath = "{STAND_IN} two" ; a comment\n', f"{STAND_IN} two"),
    (f"[core] hookspath = {STAND_IN}\n", STAND_IN),
    (f'[core "{STAND_IN}"]\n\thooksPath = elsewhere\n', None),             # a subsection is another section
    (f"[user]\n\thooksPath = {STAND_IN}\n", None),
    ("[core]\n\t# hooksPath = commented\n", None),
    ("[core]\n\tbare = false\n", None),
])
def test_the_hooks_path_is_read_from_the_config_text(tmp_path, config, expected):
    ws = _repo(tmp_path / "ws", config)
    assert run_later.hooks_path(ws) == (ws / expected if expected else None)


async def test_the_hooks_path_target_is_denied_and_an_unreadable_config_builds_no_profile(home, tmp_path, monkeypatch):
    ws = home / "ws"
    absolute = tmp_path / "elsewhere" / STAND_IN
    _repo(ws, f"[core]\n\thooksPath = {STAND_IN}\n")
    # Relative: from the repository's top, also for a command started in a folder below it.
    (ws / "sub").mkdir()
    assert run_later.hooks_path(ws / "sub") == ws / STAND_IN
    target = f'(deny file-write* (subpath "{os.path.realpath(ws / STAND_IN)}"))'
    for text in (command_sandbox.commands_profile(ws),
                 capability_sandbox.profile(root=home / "mcp", folders=[str(ws)], network=False, read=[]),
                 command_sandbox.minimal_profile(run_later_in=ws)):
        lines = text.splitlines()
        assert lines[lines.index(_lines()[-1]) + 1] == target           # right after the families
    # Absolute, and a link: the folder by its real path and the link by its name, so it can't be swapped.
    (tmp_path / "elsewhere").mkdir()
    absolute.mkdir()
    (ws / "link").symlink_to(absolute)
    (ws / ".git" / "config").write_text(f'[core]\n\thooksPath = "{ws / "link"}"\n')
    shown = command_sandbox.commands_profile(ws)
    assert (f'(deny file-write* (subpath "{os.path.realpath(absolute)}") '
            f'(subpath "{os.path.realpath(ws)}/link"))') in shown
    # An I/O error reading it: no profile, no MCP server, and the command doesn't start.
    real_open = os.open

    def failing(path, *a, **k):
        if Path(path) == ws / ".git" / "config":
            raise OSError(5, "Input/output error")
        return real_open(path, *a, **k)
    monkeypatch.setattr(run_later.os, "open", failing)
    with pytest.raises(OSError):
        command_sandbox.commands_profile(ws)
    with pytest.raises(OSError):
        capability_sandbox.profile(root=home / "mcp", folders=[str(ws)], network=False, read=[])
    with pytest.raises(OSError):
        command_sandbox.minimal_profile(run_later_in=ws)
    started: list = []

    async def spawn(*a, **k):
        started.append(a)
        raise AssertionError("started")
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    monkeypatch.setattr(terminal_exec.asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(OSError):
        await terminal_exec.run(f"echo {STAND_IN}", cwd=ws, sandbox=True)
    assert started == []


def test_a_permission_error_fails_closed_and_no_repository_reads_as_none(tmp_path, monkeypatch):
    assert run_later.hooks_path(tmp_path) is None                          # no .git at or above a pytest folder
    ws = _repo(tmp_path / "ws", f"[core]\n\thooksPath = {STAND_IN}\n")
    real_open = os.open

    def denied(path, *a, **k):
        if Path(path) == ws / ".git" / "config":
            raise PermissionError(13, "Permission denied")
        return real_open(path, *a, **k)
    monkeypatch.setattr(run_later.os, "open", denied)
    with pytest.raises(PermissionError):
        run_later.hooks_path(ws)
    with pytest.raises(PermissionError):
        run_later.kernel_filters([ws])


async def test_an_lstat_error_while_walking_up_fails_closed(tmp_path, monkeypatch):
    """#813 review: an error other than a missing `.git` (here on the parent's, reached from a folder below it)
    builds no profile and starts no command; it isn't read as "no repository"."""
    ws = _repo(tmp_path / "ws", f"[core]\n\thooksPath = {STAND_IN}\n")
    (ws / "sub").mkdir()
    real_lstat = os.lstat

    def denied(path, *a, **k):
        if Path(path) == ws / ".git":
            raise PermissionError(13, "Permission denied")
        return real_lstat(path, *a, **k)
    monkeypatch.setattr(run_later.os, "lstat", denied)
    with pytest.raises(PermissionError):
        run_later.hooks_path(ws / "sub")
    with pytest.raises(PermissionError):
        command_sandbox.commands_profile(ws / "sub")
    started: list = []

    async def spawn(*a, **k):
        started.append(a)
        raise AssertionError("started")
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    monkeypatch.setattr(terminal_exec.asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(PermissionError):
        await terminal_exec.run(f"echo {STAND_IN}", cwd=ws / "sub", sandbox=True)
    assert started == []


def test_a_fifo_where_the_config_is_does_not_stall_and_fails_closed(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".git").mkdir(parents=True)
    os.mkfifo(ws / ".git" / "config")
    with pytest.raises(OSError):
        run_later.hooks_path(ws)


# ── the gate: only a click on its own card lifts the hold outside ────────────

class _Exec:
    key = "run_command"

    def __init__(self):
        self.seen: list[tuple[bool, bool]] = []

    async def execute(self, args):
        self.seen.append((terminal_exec.OUTSIDE_SANDBOX.get(), terminal_exec.HOLD_RUN_LATER.get()))
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "sandbox": "outside"}


async def _run(monkeypatch, args, *, grant, by: str | None):
    async def answer(value):
        return value
    monkeypatch.setattr(command_gate, "_sandbox_enabled", lambda: answer(True))
    monkeypatch.setattr(command_gate, "_asks_for_everything", lambda: answer(False))
    monkeypatch.setattr(command_gate, "_work_folder_holds_home", lambda: answer(False))
    monkeypatch.setattr(command_gate, "_outside_grant", lambda conversation_id, command: answer(grant))
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    monkeypatch.setattr(settings_service, "shell_confirm_policy", lambda db: answer("ask_risky"))
    asked: list = []

    async def card(command, argv, **kw):
        asked.append(kw)
        if by is not None:
            permissions.LAST_DECISION.set(permissions.Decision(True, by, "once"))
            from server.services import approvals
            approvals.LAST_OUTCOME.set("approved")
        return by is not None
    ex = _Exec()
    monkeypatch.setitem(tool_loop.EXECUTORS, "run_command", ex)

    async def resolve():
        return [{"key": "run_command", "description": "run"}]
    trace: list = []
    turn = untrusted.track_turn()
    try:
        await tool_loop._dispatch_tool("run_command", args, "{}", resolve_tools=resolve, emit=lambda e: None,
                                       tool_timeout_s=5, tool_trace=trace, convo=[], confirm_command=card,
                                       conversation_id="c1")
    finally:
        untrusted.end_turn(turn)
    return ex.seen, asked


async def test_only_a_click_on_its_own_card_lifts_the_hold_outside(execution_db, monkeypatch):
    grant = object()
    # Out under the grant, no card (layer ③): held.
    assert await _run(monkeypatch, {"command": "ls"}, grant=grant, by=None) == ([(True, True)], [])
    # Out under the grant, its own card (a layer ② rule) clicked by the user: lifted.
    seen, asked = await _run(monkeypatch, {"command": f"git push origin {STAND_IN}"}, grant=grant, by="user")
    assert seen == [(True, False)] and len(asked) == 1
    # The same card answered by anything but the user's click: held.
    seen, _ = await _run(monkeypatch, {"command": f"git push origin {STAND_IN}"}, grant=grant, by="grant")
    assert seen == [(True, True)]
    # No grant: the outside card, clicked, lets it out with the hold lifted.
    seen, asked = await _run(monkeypatch, {"command": "ls", "outside_sandbox": True, "why": STAND_IN}, grant=None,
                             by="user")
    assert seen == [(True, False)] and len(asked) == 1


async def test_the_executor_and_terminal_exec_pass_the_hold_to_the_outside_floor(tmp_path, monkeypatch):
    from server.registry.executors import RunCommandExecutor
    from tests.server.test_workspace_tool_gate import _wire
    ws = tmp_path / "ws"
    ws.mkdir()
    await _wire(tmp_path, monkeypatch, workspace=str(ws))
    passed: list = []
    real_run = terminal_exec.run

    async def spy(command, **kw):
        passed.append((kw.get("hold_run_later"), kw["cwd"]))
        return await real_run(command, **kw)
    monkeypatch.setattr(terminal_exec, "run", spy)
    floors: list = []

    def floor(**kw):
        floors.append(kw.get("run_later_in"))
        return ["/usr/bin/env"]
    monkeypatch.setattr(command_sandbox, "outside_wrapper", floor)
    tokens = [terminal_exec.OUTSIDE_SANDBOX.set(True), terminal_exec.HOLD_RUN_LATER.set(True)]
    try:
        await RunCommandExecutor().execute({"command": "true"})
    finally:
        terminal_exec.HOLD_RUN_LATER.reset(tokens[1])
        terminal_exec.OUTSIDE_SANDBOX.reset(tokens[0])
    await RunCommandExecutor().execute({"command": "true", "outside_sandbox": True})   # the model can't set it
    token = terminal_exec.OUTSIDE_SANDBOX.set(True)
    try:
        await RunCommandExecutor().execute({"command": "true"})
    finally:
        terminal_exec.OUTSIDE_SANDBOX.reset(token)
    assert [hold for hold, _ in passed] == [True, False, False]
    assert floors == [passed[0][1], None]                    # the floor is given the command's work folder


def test_the_note_names_them_and_points_to_write_file(tmp_path):
    note = command_sandbox.note(tmp_path)
    sentence = note[note.index("Commands also can't change"):note.index("Find a way")]
    assert "git hooks and config, editor tasks, agent and package settings" in sentence and "CI" not in sentence
    assert "write_file" in sentence and "outside_sandbox" not in sentence
    assert "Commands also can't change" not in command_sandbox.note(tmp_path, proxy=True)
    assert "partly updated" not in note and "partly updated" in command_sandbox.note(tmp_path, git=True)


# ── git's refusal line: the note even at exit 0 (#813 review 1) ──────────────

GIT_REFUSED = "error: unable to unlink old '.vscode/settings.json': Operation not permitted\n"


def _explained(tmp_path, *, exit_code: int, stderr: str, sandbox: str = "workspace"):
    from server.orchestrator import run_trace
    result = {"ok": exit_code == 0, "exit_code": exit_code, "stdout": "", "stderr": stderr, "cwd": str(tmp_path),
              "sandbox": sandbox}
    if exit_code:
        result["error"] = f"exit code {exit_code}"
    with run_trace.collecting() as trace:
        terminal_exec.explain(result, cwd=tmp_path, closed=[], mode=sandbox, timed_out=False)
        run_trace.record(tool="run_command", args={}, result=result, ok=result["ok"], error=None, ms=1)
    return result, trace[0].get("denial")


def test_git_refusing_a_held_file_at_exit_0_shows_the_note_and_one_denial(tmp_path):
    """git checkout moved HEAD and exited 0, leaving the held file as it was: not a failed step, but the model reads
    the note, and SBX-7 counts one EPERM denial."""
    result, denial = _explained(tmp_path, exit_code=0, stderr=GIT_REFUSED)
    assert "partly updated" in result["note"] and "git status" in result["note"] and denial == "eperm"
    assert "sandbox_denied" not in result and "error" not in result and result["ok"] is True
    # A removal is a warning in git's words, a new file (exit 0 too) an error, and a new folder a fatal one: all count.
    for line in (f"warning: unable to unlink '.husky/{STAND_IN}': Operation not permitted\n",
                 f"error: unable to create file .husky/{STAND_IN}: Operation not permitted\n",
                 "fatal: cannot create directory at '.husky': Operation not permitted\n"):
        assert "partly updated" in _explained(tmp_path, exit_code=0, stderr=line)[0]["note"]


def test_git_refusing_a_held_file_at_exit_1_adds_the_same_sentence_to_the_stop(tmp_path):
    result, denial = _explained(tmp_path, exit_code=1, stderr=GIT_REFUSED)
    assert result["sandbox_denied"] is True and "partly updated" in result["note"] and denial == "eperm"
    assert result["error"] == "the sandbox stopped this command (exit code 1)"


def test_only_gits_work_tree_lines_in_the_workspace_sandbox_count(tmp_path):
    # A config write is a stop, but the work tree is untouched: no sentence about it.
    config, denial = _explained(tmp_path, exit_code=4,
                                stderr="error: could not write config file .git/config: Operation not permitted\n")
    assert config["sandbox_denied"] is True and "partly updated" not in config["note"] and denial == "eperm"
    # Any other tool's EPERM at exit 0, and git's line outside the workspace sandbox: nothing.
    for stderr, sandbox in [(f"{STAND_IN}: Operation not permitted\n", "workspace"), (GIT_REFUSED, "outside"),
                            (GIT_REFUSED, "off")]:
        result, denial = _explained(tmp_path, exit_code=0, stderr=stderr, sandbox=sandbox)
        assert "note" not in result and denial is None

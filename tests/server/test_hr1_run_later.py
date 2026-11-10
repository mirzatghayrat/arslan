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


def test_the_mcp_preset_decides_the_exemption_by_its_own_folder_and_its_cache_too(home):
    """#813 review 4: `roots=` in the MCP preset. A server whose own folder, or whose cache, lies inside node_modules
    (with no grant there) gets the bare regexes; with neither, the exempting ones."""
    inside, outside = home / "node_modules" / STAND_IN / "mcp", home / "mcp"
    first_bare, first_wrapped = RUN_LATER_REGEXES.splitlines()[0], RUN_LATER_TEXT.splitlines()[0]
    for root, cache, bare in [(inside, home / "cache", True), (outside, inside / "cache", True),
                              (outside, home / "cache", False)]:
        root.mkdir(parents=True, exist_ok=True)
        lines = capability_sandbox.profile(root=root, folders=[], network=False, read=[], cache=cache).splitlines()
        assert (first_bare in lines, first_wrapped in lines) == (bare, not bare), (root, cache)


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


# ── the ancestor hold (#813 review 6, option B) ─────────────────────────────

def _tree(ws: Path) -> Path:
    """Held folders at the top and below, git's own folders (searched for its held ones only), a nested repository
    under `.claude`, a dependency's repository, an ordinary folder, and a link named like a held folder."""
    for folder in (".git/hooks", f".git/modules/{STAND_IN}/hooks", ".git/worktrees", ".git/objects/.vscode",
                   "sub/.vscode", "sub/.husky", f".claude/worktrees/{STAND_IN}/.git/hooks",
                   f"node_modules/{STAND_IN}/.git/hooks", f"node_modules/{STAND_IN}/.vscode", f"{STAND_IN}-plain"):
        (ws / folder).mkdir(parents=True, exist_ok=True)
    (ws / "sub" / ".cursor").symlink_to(ws / f"{STAND_IN}-plain")
    return ws


def _found(ws: Path, *names: str) -> list[Path]:
    return [Path(os.path.realpath(ws)) / name for name in names]


def test_the_walk_finds_the_held_folders_each_after_the_ones_above_it(tmp_path):
    ws = _tree(tmp_path / "ws")
    walk = run_later.held_folders([ws])
    assert walk.complete
    expected = _found(ws, ".git", ".git/hooks", ".git/modules", ".git/worktrees", ".claude",
                      f".claude/worktrees/{STAND_IN}/.git", f".claude/worktrees/{STAND_IN}/.git/hooks",
                      "sub/.vscode", "sub/.husky")
    assert sorted(walk.folders) == sorted(expected)
    assert all(walk.folders.index(f.parent) < walk.folders.index(f) for f in walk.folders if f.parent in walk.folders)


def test_the_held_folders_are_the_plain_names_above_the_held_files():
    assert run_later.HELD_FOLDERS == {".git": {"hooks": {}, "worktrees": {}, "modules": {}}, ".vscode": {},
                                      ".claude": {}, ".codex": {}, ".gemini": {}, ".cursor": {}, ".husky": {}}


def test_inside_a_dependency_folder_the_walk_holds_nothing_unless_the_root_is_inside_one(tmp_path):
    ws = _tree(tmp_path / "ws")
    assert not any("node_modules" in f.parts for f in run_later.held_folders([ws]).folders)
    inside = _tree(tmp_path / "node_modules" / "ws")                     # a root inside one: no exemption
    found = run_later.held_folders([inside]).folders
    assert set(_found(inside, f"node_modules/{STAND_IN}/.git", f"node_modules/{STAND_IN}/.vscode")) <= set(found)


@pytest.mark.parametrize("caps", [{"max_entries": 3}, {"max_depth": 1}, {"max_held": 8}, {"max_held_bytes": 400}])
def test_the_walk_stops_at_its_caps_incomplete(tmp_path, caps):
    ws = _tree(tmp_path / "ws")                                    # 9 held folders
    walk = run_later.held_folders([ws], **caps)
    assert not walk.complete
    assert len(walk.folders) <= caps.get("max_held", 9)
    assert run_later.held_folders([ws], max_entries=1000, max_depth=8, max_held=9).complete


def _repositories(ws: Path, count: int) -> Path:
    for i in range(count):
        for sub in (".git/hooks", ".vscode"):
            (ws / "fixtures" / f"r{i:04}" / sub).mkdir(parents=True)
    return ws


def test_the_held_folder_cap_keeps_the_profile_small(home):
    """#813 review 7: the walk returns at most `WALK_HELD` folders, so the literals stay a fraction of ARG_MAX."""
    ws = _repositories(home / "ws", 400)                            # 1,200 held folders
    walk = run_later.held_folders([ws])
    assert not walk.complete and len(walk.folders) == run_later.WALK_HELD
    text = command_sandbox.commands_profile(ws)
    assert len(text.encode()) < 256 * 1024


def test_the_held_byte_cap_bounds_deep_long_paths(tmp_path):
    """Fewer held folders than the count cap, each under a long chain of its own: the byte cap ends the walk."""
    ws = tmp_path / "ws"
    for i in range(40):
        chain = ws.joinpath(*(f"{i:02}-{'x' * 60}-{depth}" for depth in range(12)))
        (chain / ".vscode").mkdir(parents=True)
    walk = run_later.held_folders([ws])
    assert not walk.complete and len(walk.folders) < run_later.WALK_HELD
    assert run_later.held_folders([ws], max_held_bytes=10**9).complete


def test_holding_many_folders_and_the_folders_above_them_is_linear(tmp_path):
    """#813 review 7: `held_ancestors` judged membership against a list, quadratic in the folders held. 1,000
    repositories (3,000 held folders, uncapped walk) now take about 0.2 s alone; the list took 6 to 8 s. The bound is
    generous for a loaded parallel run."""
    import time
    ws = _repositories(tmp_path / "ws", 1000)
    walk = run_later.held_folders([ws], max_held=10**6, max_held_bytes=10**9)
    started = time.perf_counter()
    held = command_sandbox.held_ancestors([ws], [], kept=walk.folders)
    took = time.perf_counter() - started
    print(f"\nHR-1 review 7: 3,000 held folders, hold {took:.3f} s")
    assert walk.complete and len(walk.folders) == 3000
    assert len(held) == len(set(held)) == 1 + 1 + 4000                      # ws, fixtures, each r, .git, hooks, .vscode
    assert took < 2.0


def test_a_folder_the_walk_cannot_list_ends_it_incomplete(tmp_path):
    ws = _tree(tmp_path / "ws")
    shut = ws / f"{STAND_IN}-plain"
    shut.chmod(0)
    try:
        assert not run_later.held_folders([ws]).complete
    finally:
        shut.chmod(0o700)


def _held_line(text: str) -> str:
    """The deny line with the folders `held_ancestors` holds as literals (the last one with the work folder's)."""
    return [line for line in text.splitlines() if line.startswith("(deny file-write* (literal")][-1]


def test_the_profiles_hold_the_held_folders_and_the_folders_above_them_in_order(home):
    ws = _tree(home / "ws")
    real = Path(os.path.realpath(ws))
    order = [real, real / "sub", real / "sub" / ".vscode"]
    git = [real / ".git", real / ".git" / "hooks"]
    texts = {"commands": command_sandbox.commands_profile(ws),
             "mcp": capability_sandbox.profile(root=home / "mcp", folders=[str(ws)], network=False, read=[]),
             "floor": command_sandbox.minimal_profile(run_later_in=ws)}
    for name, text in texts.items():
        line = _held_line(text)
        for chain in (order, git):
            spots = [line.index(f'(literal "{f}")') for f in chain]
            assert spots == sorted(spots), name
        assert f'(literal "{real / ".git" / "objects"}")' not in line
        assert f"{real}/node_modules" not in text, name                    # a dependency's folders are not held
        assert f'(literal "{real / f"{STAND_IN}-plain"}")' not in line     # nor an ordinary folder
    # The floor holds them all the way up, as every folder is writable there.
    assert '(literal "/")' in _held_line(texts["floor"])


def test_the_mcp_preset_holds_them_in_its_own_folder_too(home):
    root = _tree(home / "mcp")
    line = _held_line(capability_sandbox.profile(root=root, folders=[], network=False, read=[]))
    assert f'(literal "{os.path.realpath(root / ".git" / "hooks")}")' in line


def test_past_the_cap_the_profiles_hold_them_by_name_and_otherwise_do_not(home, monkeypatch):
    ws = _tree(home / "ws")
    by_name = run_later.folder_filters([ws])
    assert by_name[0] == ('(require-all (regex #"^.*/[.][Gg][Ii][Tt]$") '
                          f'(require-not (regex #"{run_later.dependency_regex()}")))')
    build = {"commands": lambda: command_sandbox.commands_profile(ws),
             "mcp": lambda: capability_sandbox.profile(root=home / "mcp", folders=[str(ws)], network=False, read=[]),
             "floor": lambda: command_sandbox.minimal_profile(run_later_in=ws)}
    line = f"(deny file-write* {' '.join(by_name)})"
    assert all(line not in make() for make in build.values())
    monkeypatch.setattr(run_later, "WALK_ENTRIES", 3)
    assert all(line in make().splitlines() for make in build.values())


_WHY = "too large to map, so Arslan holds the folders those files live in (such as .git and .vscode) by name"


def test_the_note_says_why_when_the_folder_is_too_large_to_map(home, monkeypatch):
    """⓪Plan (#813 review 6): past the cap, the held folders are held by name; the stop note says so (review 7: and
    doesn't blame the size for git init or clone, which HR-1 refuses in every folder)."""
    monkeypatch.setattr(command_sandbox, "_TOO_LARGE", set())
    ws = _tree(home / "ws")
    why = _WHY
    entries = run_later.WALK_ENTRIES
    command_sandbox.commands_profile(ws)
    assert why not in command_sandbox.note(ws)
    monkeypatch.setattr(run_later, "WALK_ENTRIES", 3)
    command_sandbox.commands_profile(ws)
    assert why in command_sandbox.note(ws)
    assert why not in command_sandbox.note(home / "other")
    monkeypatch.setattr(run_later, "WALK_ENTRIES", entries)
    command_sandbox.commands_profile(ws)                      # a complete walk clears it again
    assert why not in command_sandbox.note(ws)


def test_an_mcp_servers_walk_or_the_floors_does_not_change_the_command_note(home, monkeypatch):
    """#813 review 7: only the commands profile's own walk of the work folder marks or clears it. An MCP server's walk
    covers its own folder too, and the floor's note is another one."""
    monkeypatch.setattr(command_sandbox, "_TOO_LARGE", set())
    ws = _tree(home / "ws")
    others = (lambda: capability_sandbox.profile(root=home / "mcp", folders=[str(ws)], network=False, read=[]),
              lambda: command_sandbox.minimal_profile(run_later_in=ws))
    entries = run_later.WALK_ENTRIES
    monkeypatch.setattr(run_later, "WALK_ENTRIES", 3)
    for make in others:                                       # their incomplete walks don't mark it
        make()
        assert _WHY not in command_sandbox.note(ws)
    command_sandbox.commands_profile(ws)
    assert _WHY in command_sandbox.note(ws)
    monkeypatch.setattr(run_later, "WALK_ENTRIES", entries)
    for make in others:                                       # nor do their complete walks clear it
        make()
        assert _WHY in command_sandbox.note(ws)


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
    assert "partly updated" not in note


def test_the_git_note_ends_with_the_user_not_with_outside_sandbox():
    note = command_sandbox.git_note()
    assert "partly updated" in note and "git status" in note and "tell the user" in note and "upstream" in note
    assert "outside_sandbox" not in note and "Find a way" not in note and note.endswith("undo that change).")


# ── git naming a held file: the note at any exit code, in any language (#813 reviews 1 and 4) ──

GIT_REFUSED = "error: unable to unlink old '.vscode/settings.json': Operation not permitted\n"
CONFIG_REFUSED = "error: could not write config file .git/config: Operation not permitted\n"
CHECKOUT = f"git checkout -q {STAND_IN}"
WIDE_COLON = chr(0xFF1A)                 # git's Chinese messages put it right after a path, with no space


def _explained(tmp_path, monkeypatch, *, exit_code: int, stderr: str, sandbox: str = "workspace",
               command: str = CHECKOUT, hold: bool = False, cwd=None, stdout: str = ""):
    """terminal_exec.explain on a fake result: the result, the denial on the run trace, and how many times a denial
    was noted (SBX-7: exactly one per run)."""
    from server.orchestrator import run_trace
    noted: list[str] = []
    real_note = run_trace.note_denial

    def counting(code):
        noted.append(code)
        real_note(code)
    monkeypatch.setattr(run_trace, "note_denial", counting)
    result = {"ok": exit_code == 0, "exit_code": exit_code, "stdout": stdout, "stderr": stderr, "cwd": str(tmp_path),
              "sandbox": sandbox}
    if exit_code:
        result["error"] = f"exit code {exit_code}"
    with run_trace.collecting() as trace:
        terminal_exec.explain(result, cwd=cwd or tmp_path, closed=[], mode=sandbox, timed_out=False, command=command,
                              hold=hold)
        run_trace.record(tool="run_command", args={}, result=result, ok=result["ok"], error=None, ms=1)
    return result, trace[0].get("denial"), noted


def _git_noted(explained, *, floor: bool = False) -> bool:
    """Whether the git note was given; when it was, with exactly one `eperm` denial noted (never two), or, under the
    outside floor, none (#813 review 5: SBX-7 counts the workspace sandbox's denials)."""
    result, denial, noted = explained
    if result.get("note") != command_sandbox.git_note():
        return False
    if floor:
        assert denial is None and noted == [], noted
    else:
        assert denial == "eperm" and noted == ["eperm"], noted
    return True


def _nothing(explained) -> bool:
    result, denial, noted = explained
    return "note" not in result and denial is None and noted == []


#: A translated line: stand-in German words around the path, and macOS's strerror, which it never translates.
GERMAN = "Fehler: Konnte alte Datei '.vscode/settings.json' nicht entfernen: Operation not permitted\n"
#: git's refusal lines naming a held file, in its English words and others (git translates the words, never the path,
#: and macOS never translates "Operation not permitted").
HELD_LINES = [
    GIT_REFUSED, CONFIG_REFUSED, CONFIG_REFUSED * 2,
    f"warning: unable to unlink '.husky/{STAND_IN}': Operation not permitted\n",
    f"error: unable to create file .husky/{STAND_IN}: Operation not permitted\n",
    "error: unable to create symlink .vscode/settings.json: Operation not permitted\n",
    "error: unable to write file .npmrc mode 100644: Operation not permitted\n",
    "fatal: cannot create directory at '.husky': Operation not permitted\n",
    f"error: cannot copy '/{STAND_IN}/templates/hooks/pre-push.sample' to '/w/.git/hooks/pre-push.sample': "
    "Operation not permitted\n",
    GERMAN,
    "Fehler: Konnte Konfigurationsdatei '.git/config' nicht sperren.: Operation not permitted\n",
    f"{STAND_IN}{WIDE_COLON}{STAND_IN} .git/config{WIDE_COLON}Operation not permitted\n",
    f"{STAND_IN}{WIDE_COLON}unable to unlink old '.envrc'{WIDE_COLON}Operation not permitted\n",
    f"{STAND_IN} .git/config.worktree. Operation not permitted\n",
    f"{STAND_IN}\n{GIT_REFUSED}{STAND_IN}\n",                    # the refusal line among others
]


@pytest.mark.parametrize("line", HELD_LINES)
def test_a_git_line_naming_a_held_file_gets_the_note_at_exit_0_with_one_denial(tmp_path, monkeypatch, line):
    """checkout and switch move HEAD and exit 0 leaving a held tracked file as it was; a tracking checkout, push -u and
    --set-upstream-to exit 0 with no upstream saved. Not a failed step, but the model reads the note, and SBX-7
    counts one EPERM denial."""
    explained = _explained(tmp_path, monkeypatch, exit_code=0, stderr=line)
    assert _git_noted(explained)
    assert "sandbox_denied" not in explained[0] and "error" not in explained[0] and explained[0]["ok"] is True


def test_a_git_line_naming_a_held_file_at_exit_1_is_a_stop_with_the_git_note(tmp_path, monkeypatch):
    """A refusal on a work-tree file (merge, stash, rebase): the tree may be partly updated, so the git note."""
    for line in (GIT_REFUSED, GERMAN, CONFIG_REFUSED + GIT_REFUSED):
        explained = _explained(tmp_path, monkeypatch, exit_code=1, stderr=line)
        assert _git_noted(explained) and explained[0]["sandbox_denied"] is True
        assert explained[0]["error"] == "the sandbox stopped this command (exit code 1)"


SETUP_REFUSED = [CONFIG_REFUSED,
                 f"fatal: cannot copy '/{STAND_IN}/templates/hooks/pre-push.sample' to "
                 f"'/w/{STAND_IN}/.git/hooks/pre-push.sample': Operation not permitted\n",
                 f"error: could not lock config file {STAND_IN}/.git/config: Operation not permitted\n"]


@pytest.mark.parametrize("line", SETUP_REFUSED)
def test_a_setup_step_that_failed_on_the_repositorys_own_config_or_hooks_gets_the_stop_note(tmp_path, monkeypatch,
                                                                                          line):
    """#813 review 5: clone, init, remote add and a config write fail outright (non-zero) on `.git` only: nothing in
    the work tree moved, so the ordinary stop note (one denial) in the sandbox, and the floor's own note, which says
    only a click on its own card lifts the hold, under the floor (no denial). At exit 0 the git note, as before."""
    result, denial, noted = _explained(tmp_path, monkeypatch, exit_code=128, stderr=line, command=f"git clone {STAND_IN}")
    assert result["note"] == command_sandbox.note(tmp_path) and result["sandbox_denied"] is True
    assert denial == "eperm" and noted == ["eperm"]
    result, denial, noted = _explained(tmp_path, monkeypatch, exit_code=128, stderr=line, sandbox="outside", hold=True,
                                       command=f"git clone {STAND_IN}")
    assert "without the user's click on its own card" in result["note"] and denial is None and noted == []
    assert _git_noted(_explained(tmp_path, monkeypatch, exit_code=0, stderr=line))


def test_the_hooks_path_target_counts_from_the_work_folder_and_below_it(tmp_path, monkeypatch):
    ws = _repo(tmp_path / "ws", f"[core]\n\thooksPath = {STAND_IN}-hooks\n")
    (ws / "sub").mkdir()
    line = f"error: unable to unlink old '{STAND_IN}-hooks/pre-commit': Operation not permitted\n"
    for cwd in (ws, ws / "sub"):
        assert _git_noted(_explained(tmp_path, monkeypatch, exit_code=0, stderr=line, cwd=cwd))
    assert _nothing(_explained(tmp_path, monkeypatch, exit_code=0, stderr=line))             # no such setting here


def test_the_outside_floor_gets_the_git_note_only_when_it_holds_them(tmp_path, monkeypatch):
    for line, exit_code in [(GIT_REFUSED, 0), (CONFIG_REFUSED, 0), (GIT_REFUSED, 1)]:
        assert _git_noted(_explained(tmp_path, monkeypatch, exit_code=exit_code, stderr=line, sandbox="outside",
                                     hold=True), floor=True)
        for sandbox, hold in [("outside", False), ("off", True), ("off", False)]:
            result, denial, noted = _explained(tmp_path, monkeypatch, exit_code=exit_code, stderr=line,
                                               sandbox=sandbox, hold=hold)
            assert result.get("note") != command_sandbox.git_note() and denial is None and noted == []
    # Another command refused under the floor: its note names the run-later files only when the floor holds them.
    refused = f"{STAND_IN}: .envrc: Operation not permitted\n"
    held, _, noted = _explained(tmp_path, monkeypatch, exit_code=1, stderr=refused, sandbox="outside", hold=True,
                                command=f"cp {STAND_IN} .envrc")
    free, _, _ = _explained(tmp_path, monkeypatch, exit_code=1, stderr=refused, sandbox="outside",
                            command=f"cp {STAND_IN} .envrc")
    assert "run later" in held["note"] and "run later" not in free["note"] and "Arslan's own data" in free["note"]
    assert noted == []                                                   # the floor's own note records no denial


def test_only_a_git_command_naming_a_held_file_gets_the_git_note(tmp_path, monkeypatch):
    # Another program printing a held path: no git note (at exit 1 the ordinary stop note, as before). `.git` in a
    # path is not the word git (#813 review 5).
    for command in (f"python3 {STAND_IN}.py", f"{STAND_IN}-git checkout x", f"cat {STAND_IN}.gitx", "cat .git/config",
                    f"cp {STAND_IN} .git/hooks/pre-commit"):
        assert _nothing(_explained(tmp_path, monkeypatch, exit_code=0, stderr=GIT_REFUSED, command=command))
        result, denial, noted = _explained(tmp_path, monkeypatch, exit_code=1, stderr=GIT_REFUSED, command=command)
        assert result["note"] == command_sandbox.note(tmp_path) and denial == "eperm" and noted == ["eperm"]
    # git naming an ordinary file, or a held name inside a node_modules below the work folder (written there).
    for line in (f"error: unable to unlink old '{STAND_IN}.txt': Operation not permitted\n",
                 f"error: unable to unlink old 'node_modules/{STAND_IN}/.npmrc': Operation not permitted\n",
                 "error: unable to unlink old 'src/config': Operation not permitted\n",
                 f"{STAND_IN}: Operation not permitted\n", "Switched to branch 'main'\n"):
        assert _nothing(_explained(tmp_path, monkeypatch, exit_code=0, stderr=line))


def test_a_refusal_on_stdout_under_2_and_1_gets_the_note(tmp_path, monkeypatch):
    """#813 review 5: `git checkout <b> 2>&1`, `push -u ... 2>&1`: git's refusal line reaches stdout, at exit 0. Both
    streams are read, each on its own."""
    for line in (GIT_REFUSED, CONFIG_REFUSED, GERMAN):
        assert _git_noted(_explained(tmp_path, monkeypatch, exit_code=0, stderr="", stdout=line,
                                     command=f"{CHECKOUT} 2>&1 | tail -n 3"))
        assert _git_noted(_explained(tmp_path, monkeypatch, exit_code=0, stderr=f"{STAND_IN}\n", stdout=line))
    # The EPERM text on one stream and a held path only on the other is no refusal line.
    assert _nothing(_explained(tmp_path, monkeypatch, exit_code=0, stderr=f"{STAND_IN}: Operation not permitted\n",
                               stdout="diff --git a/.npmrc b/.npmrc\n"))


#: #813 review 5: git (or a command with `git` as a path word) naming a held file with no refusal on that line. Each
#: got a false git note and an `eperm` while only the path was keyed. (exit code, stdout, stderr, command)
NAMED_NOT_REFUSED = {
    "a commit whose hook prints its own path": (
        0, f"[main 1a2b3c4] {STAND_IN}\n", f"{STAND_IN} .husky/pre-commit\n", f"git commit -qm {STAND_IN}"),
    "the not-executable hook hint": (
        0, "", "hint: The '.git/hooks/pre-commit' hook was ignored because it's not set as executable.\n"
               "hint: You can disable this warning with `git config advice.ignoredHook false`.\n",
        f"git commit -qm {STAND_IN}"),
    "a pathspec error on checkout": (
        1, "", "error: pathspec '.vscode/settings.json' did not match any file(s) known to git\n",
        "git checkout -- .vscode/settings.json"),
    "a pathspec error on rm --cached": (
        128, "", "fatal: pathspec '.envrc' did not match any files\n", "git rm --cached .envrc"),
    "ls-files --error-unmatch": (
        1, "", "error: pathspec '.npmrc' did not match any file(s) known to git\n"
               "Did you forget to 'git add'?\n", "git ls-files --error-unmatch .npmrc"),
    "add of an ignored .envrc": (
        1, "", "The following paths are ignored by one of your .gitignore files:\n.envrc\n"
               "hint: Use -f if you really want to add them.\n", "git add .envrc"),
    "show of a held file": (
        128, "", "fatal: path '.npmrc' does not exist in 'HEAD'\n", "git show HEAD:.npmrc"),
    "show's diff on stdout": (
        0, "diff --git a/.npmrc b/.npmrc\n--- a/.npmrc\n+++ b/.npmrc\n", "", "git show HEAD"),
    "a git apply that doesn't apply": (
        1, "", "error: patch failed: .vscode/settings.json:1\n"
               "error: .vscode/settings.json: patch does not apply\n", f"git apply {STAND_IN}.patch"),
    "the CRLF warning": (
        0, "", "warning: in the working copy of '.vscode/settings.json', CRLF will be replaced by LF the next time "
               "Git touches it\n", "git add -A"),
    "a bad config line": (
        128, "", "fatal: bad config line 3 in file .git/config\n", "git status"),
    "config --list --show-origin": (
        0, "file:.git/config\tcore.bare=false\n", "", "git config --list --show-origin"),
    "ls of a path with git as a word": (
        1, "", "ls: git/.npmrc: No such file or directory\n", "ls git/.npmrc"),
}


@pytest.mark.parametrize("case", sorted(NAMED_NOT_REFUSED))
def test_a_held_path_named_without_a_refusal_gets_no_note(tmp_path, monkeypatch, case):
    exit_code, stdout, stderr, command = NAMED_NOT_REFUSED[case]
    assert _nothing(_explained(tmp_path, monkeypatch, exit_code=exit_code, stdout=stdout, stderr=stderr,
                               command=command))
    assert _nothing(_explained(tmp_path, monkeypatch, exit_code=exit_code, stdout=stdout, stderr=stderr,
                               command=command, sandbox="outside", hold=True))


def test_a_work_folder_inside_a_dependency_folder_keeps_the_git_note(tmp_path, monkeypatch):
    """#813 review 5: the held-path check uses the work folder's root rule, as the kernel does. A work folder inside
    node_modules holds every name, so git's refusal there still gets the note; a node_modules below an ordinary work
    folder is exempt (test above)."""
    work = tmp_path / "node_modules" / STAND_IN / "work"
    work.mkdir(parents=True)
    for line in (GIT_REFUSED, f"error: unable to unlink old 'node_modules/{STAND_IN}/.npmrc': Operation not permitted\n"):
        assert _git_noted(_explained(tmp_path, monkeypatch, exit_code=0, stderr=line, cwd=work))


@pytest.mark.parametrize("command", [CHECKOUT, f"cd sub && /usr/bin/git switch {STAND_IN}", "g'i't checkout x",
                                     f"env GIT_TRACE=0 git push -u origin {STAND_IN}", "git -C .. checkout x"])
def test_git_is_read_from_the_command_text_or_the_reader(tmp_path, monkeypatch, command):
    assert _git_noted(_explained(tmp_path, monkeypatch, exit_code=0, stderr=CONFIG_REFUSED, command=command))

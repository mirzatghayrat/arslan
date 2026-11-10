"""Files that make something run later (v0.1.64 HR-1): the list, and the two forms that hold it.

The user's test for a name on this list: another program runs it, or loads it as configuration. A write to one of
these, made by a sandboxed command or an MCP server now, would run later outside the sandbox: a git hook, a CI job,
an editor task, an agent's hooks and MCP servers, a package manager's settings. Instruction files (AGENTS.md,
CLAUDE.md, CLAUDE.local.md, GEMINI.md, .cursorrules and any other instruction `.md`) are ordinary files, by the
user's ruling: Claude Code and Codex don't guard them separately either. Package scripts and Makefiles are out of
scope (HR's design).

Each name matches at any depth. It has two forms, which tests/server/test_hr1_run_later.py keeps in agreement:
  `kernel_filters` SBPL regexes built only from the constants here (never a path from outside), written after the
                   writable roots in the commands and MCP profiles, so the last rule wins (command_sandbox,
                   capability_sandbox); plus the work folder's `core.hooksPath` target, as a path;
  `matches`        the same names for Python, for HR-2's file tools.

APFS ignores letter case, so both forms do too: the regex spells each letter as a class, `matches` folds case.
Whether the kernel needs the classes was not measured here (a write in another case to an existing name may reach
the vnode by its stored name); the classes cost nothing and hold either way. Codex's bypass corpus measures case and
Unicode forms (`matches` folds with casefold, which the regex can't: a name only Unicode folding makes equal is
held by the file tools and not by the kernel, if APFS folds it at all).

Not on the list, and why: the rest of `.git` (commit, branch, checkout and stash must keep working); the user's
home-level files (shell startup, global git config, LaunchAgents: the commands profile doesn't make them writable
unless the work folder is ~; a separate set, not this one); a submodule's git folder deeper than one name under
`.git/modules`, a bare repository's hooks, and a `.git` that is a link to a folder named otherwise (Codex's corpus).
"""
from __future__ import annotations

import fnmatch
import os
import stat
from collections.abc import Iterable
from pathlib import Path, PurePath

#: The names, by family. A pattern is path components; `*` in one is any run of characters but `/`, and a final
#: `**` is the folder itself and everything below it.
FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # git runs hooks and loads config (which can name programs: core.hooksPath, core.fsmonitor, filters, aliases).
    ("git", (".git/hooks/**", ".git/config", ".git/config.worktree", ".git/worktrees/*/config.worktree",
             ".git/modules/*/hooks/**", ".git/modules/*/config", ".gitmodules")),
    ("envrc", (".envrc",)),                                     # direnv runs it on cd
    ("ci", (".github/workflows/**", ".gitlab-ci.yml", ".circleci/**", "azure-pipelines.yml", "Jenkinsfile",
            "bitbucket-pipelines.yml")),
    # Editors run tasks and launch configs, and load settings and MCP servers (VS Code reads .vscode/mcp.json).
    ("editor", (".vscode/tasks.json", ".vscode/launch.json", ".vscode/settings.json", ".vscode/mcp.json",
                "*.code-workspace")),
    # Agents' settings (hooks, MCP servers, permissions) and launch configs; never their instruction files.
    ("agent", (".claude/settings*.json", ".claude/launch.json", ".mcp.json", ".codex/config.toml",
               ".gemini/settings.json", ".cursor/*.json")),
    # Package managers' settings: registries, scripts to run (yarn's yarn-path), install hooks.
    ("package", (".npmrc", ".yarnrc", ".yarnrc.yml", "pip.conf", "uv.toml")),
    ("hooks", (".pre-commit-config.yaml", ".husky/**")),
)

#: Dependency folders: a package installed there ships its own CI, editor and hook files, which nothing runs or loads
#: from there, so they pass the user's test as ordinary files. Without this a dependency install fails (#813 review).
#: Matched as a path component on the real path the kernel sees, so a link named so elsewhere gains nothing. Only
#: below the root (the work folder, or an MCP server's own and granted folders): when a root's real path already
#: passes through one (a repository kept inside node_modules), its profile has no exemption and every name stays
#: held (`exempts`, #813 review 2). The tool caches (.venv, uv and pip unpack folders) wait for Codex's measurement.
DEPENDENCY_FOLDERS = ("node_modules",)

_ALLOWED = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_*")


def _component(glob: str) -> str:
    """One component as an SBPL (POSIX extended) regex: a letter as its two cases, `.` as `[.]`, `*` as `[^/]*`."""
    if not glob or not set(glob) <= _ALLOWED:
        raise ValueError("a run-later name is letters, digits, '.', '-', '_' and '*'")
    out = []
    for ch in glob:
        if ch == "*":
            out.append("[^/]*")
        elif ch == ".":
            out.append("[.]")
        elif ch.isalpha():
            out.append(f"[{ch.upper()}{ch.lower()}]")
        else:
            out.append(ch)
    return "".join(out)


def pattern_regex(pattern: str) -> str:
    """`pattern` at any depth of an absolute path."""
    parts = pattern.split("/")
    below = parts[-1] == "**"
    if below:
        parts = parts[:-1]
    return "^.*/" + "/".join(map(_component, parts)) + ("(/.*)?" if below else "") + "$"


def _fits(parts: tuple[str, ...], names: tuple[str, ...]) -> bool:
    if names[-1] == "**":
        names = names[:-1]
        if len(parts) < len(names):
            return False
    elif len(parts) != len(names):
        return False
    return all(fnmatch.fnmatchcase(part.casefold(), name.casefold()) for part, name in zip(parts, names))


def dependency_regex() -> str:
    """A path with a dependency folder as one of its folders (not as its last component)."""
    return "^.*/(" + "|".join(map(_component, DEPENDENCY_FOLDERS)) + ")/.*$"


def _parts(path) -> tuple[str, ...]:
    return tuple(p for p in PurePath(os.fspath(path)).parts if p not in ("/", ""))


_FOLDED_DEPENDENCIES = frozenset(name.casefold() for name in DEPENDENCY_FOLDERS)


def exempts(roots: Iterable) -> bool:
    """Whether a profile (or a check) for these roots exempts dependency folders: only when no root's path has one
    as a component, itself included. Callers pass real paths, as the kernel matches them."""
    return not any(part.casefold() in _FOLDED_DEPENDENCIES for root in roots for part in _parts(root))


def family(path, root=None) -> str | None:
    """The family of the first name `path` matches at any depth, or None. None inside a dependency folder too, unless
    `root` is given and its own path has one (`exempts`): the same rule as the kernel's for that root, which HR-2
    passes (the work folder, by its real path). Without `root` a dependency folder anywhere on the path exempts."""
    parts = _parts(path)
    if (root is None or exempts([root])) and any(part.casefold() in _FOLDED_DEPENDENCIES for part in parts[:-1]):
        return None
    for name, patterns in FAMILIES:
        for pattern in patterns:
            names = tuple(pattern.split("/"))
            if any(_fits(parts[i:], names) for i in range(len(parts))):
                return name
    return None


def matches(path, root=None) -> bool:
    """Whether a write to `path` (as given: HR-2 passes the resolved path, and the work folder's real path as `root`)
    is a write into a file that runs later. The names only; the work folder's `core.hooksPath` target is
    `hooks_path`'s."""
    return family(path, root) is not None


# ── core.hooksPath: read, never run ─────────────────────────────────────────

def _value(raw: str) -> str:
    """A git config value: comments (`#`, `;`) outside quotes end it, quotes are removed, escapes decoded, and
    surrounding white space trimmed (inner white space outside quotes kept, as git does closely enough here)."""
    out, quoted, i = [], False, 0
    while i < len(raw):
        ch = raw[i]
        if ch == '"':
            quoted = not quoted
        elif ch == "\\" and i + 1 < len(raw):
            i += 1
            out.append({"n": "\n", "t": "\t", "b": "\b"}.get(raw[i], raw[i]))
        elif ch in "#;" and not quoted:
            break
        else:
            out.append(ch)
        i += 1
    return "".join(out).strip()


def _core_hooks_path(text: str) -> str | None:
    """The last `core.hooksPath` in one config file's text, or None. Sections and keys ignore case; a subsection
    (`[core "x"]`) is another section. Includes are not followed (not covered: Codex's corpus)."""
    section, found = "", None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            head, _, line = line[1:].partition("]")
            section = head.strip().lower()
            line = line.strip()
        if not line or line[0] in "#;" or section != "core":
            continue
        key, eq, raw = line.partition("=")
        if eq and key.strip().lower() == "hookspath":
            found = _value(raw)
    return found or None


def _is_folder(path: Path) -> bool:
    """`path` is a folder (a link followed). Only a missing one is False: any other error propagates, where
    `Path.is_dir` and `os.path.lexists` would read it as absent and the hold would drop out."""
    try:
        return stat.S_ISDIR(os.stat(path).st_mode)
    except (FileNotFoundError, NotADirectoryError):
        return False


_MAX_CONFIG = 1 << 20


def _read(path: Path) -> str | None:
    """A regular file's text, or None when it is missing. Opened without blocking and checked once open, so a
    FIFO or a device put where a config is expected can't stall the profile; that, and any other error, raises."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except (FileNotFoundError, NotADirectoryError):
        return None
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(f"not a regular file: {path}")
        return handle.read(_MAX_CONFIG).decode("utf-8", errors="surrogateescape")


def _config_files(top: Path, git: Path) -> list[Path] | None:
    """The config files git reads for the repository whose `.git` entry is `git`, in order (later wins), or None
    when it is not a repository Arslan can place. A `.git` file (a worktree) names its git folder, whose
    `commondir` names the shared one. Written for worktrees but not tested here: Codex's corpus has `.git` files."""
    if _is_folder(git):
        return [git / "config", git / "config.worktree"]
    try:
        line = (_read(git) or "").strip()
    except OSError:
        if not stat.S_ISREG(os.lstat(git).st_mode) and not os.path.islink(git):
            return None                                         # a FIFO or the like named .git: no repository
        raise
    if not line.startswith("gitdir:"):
        return None
    own = Path(os.path.expanduser(line.removeprefix("gitdir:").strip()))
    own = own if own.is_absolute() else top / own
    shared = (_read(own / "commondir") or "").strip()
    common = own / shared if shared else own
    return [common / "config", own / "config.worktree"]


def hooks_path(folder: Path) -> Path | None:
    """Where git runs hooks from for `folder`, when its repository's config sets `core.hooksPath`: the nearest
    `.git` at or above `folder`, read as text (git itself never runs). Relative values are taken from the
    repository's top, as git takes them for a work tree; `~` is the user's home. None when there's no repository
    or no setting. An error other than a missing file (permission, I/O) propagates, so no profile is built and the
    command doesn't start (as `command_sandbox._identity`)."""
    folder = Path(os.path.abspath(folder))
    for top in (folder, *folder.parents):
        git = top / ".git"
        try:
            os.lstat(git)
        except (FileNotFoundError, NotADirectoryError):
            continue
        found = None
        for config in _config_files(top, git) or ():
            text = _read(config)
            found = (_core_hooks_path(text) if text is not None else None) or found
        if found is None:
            return None
        target = Path(os.path.expanduser(found))
        return target if target.is_absolute() else top / target
    return None


def kernel_filters(folders: Iterable[Path], *, roots: Iterable[Path] = ()) -> list[tuple[str, ...]]:
    """The SBPL filters a profile denies `file-write*` over, one tuple per family in FAMILIES' order, then one for
    the `core.hooksPath` targets of `folders` (the work folder, or an MCP server's granted folders) when any is
    set: the folder by its real path and by its name in its real parent, so a link there can't be swapped.
    Each name is wrapped to exempt dependency folders only when `exempts` holds for the real paths of `folders`
    and `roots` (an MCP server's own folder); otherwise it is the bare regex. The regexes stay built from constants."""
    from server.services.sandbox_profile import real, regex, subpath
    folders = list(folders)
    if exempts(real(Path(os.path.abspath(p))) for p in (*folders, *roots)):
        outside_dependencies = f"(require-not {regex(dependency_regex())})"
        out = [tuple(f"(require-all {regex(pattern_regex(p))} {outside_dependencies})" for p in patterns)
               for _, patterns in FAMILIES]
    else:
        out = [tuple(regex(pattern_regex(p)) for p in patterns) for _, patterns in FAMILIES]
    targets: list[str] = []
    for folder in folders:
        target = hooks_path(folder)
        if target is None:
            continue
        lexical = Path(os.path.abspath(target))
        for spelling in (real(lexical), real(lexical.parent) / lexical.name):
            if subpath(spelling) not in targets:
                targets.append(subpath(spelling))
    if targets:
        out.append(tuple(targets))
    return out

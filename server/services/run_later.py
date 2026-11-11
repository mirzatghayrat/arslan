"""Files that make something run later (v0.1.64 HR-1): the list, and the two forms that hold it.

The user's test for a name on this list: another program runs it, or loads it as configuration. A write to one of
these, made by a sandboxed command or an MCP server now, would run later outside the sandbox: a git hook, an editor
task, an agent's hooks and MCP servers, a package manager's settings. Instruction files (AGENTS.md, CLAUDE.md,
CLAUDE.local.md, GEMINI.md, .cursorrules and any other instruction `.md`) are ordinary files, by the user's ruling:
Claude Code and Codex don't guard them separately either. Package scripts and Makefiles are out of scope (HR's
design). CI files are recognised (`CI_FILES`, `is_ci_file`) but not denied, by the user's list decision: a CI job
runs on the CI service after a push, so their guard is the push card (HR-2b).

Each name matches at any depth. It has two forms, which tests/server/test_hr1_run_later.py keeps in agreement:
  `kernel_filters` SBPL regexes built only from the constants here (never a path from outside), written after the
                   writable roots in the commands and MCP profiles, so the last rule wins (command_sandbox,
                   capability_sandbox); plus the work folder's `core.hooksPath` target, as a path;
  `matches`        the same names for Python, for HR-2's file tools.
The folders above them are held in place by literal (`held_folders`, the ancestor hold, #813 review 6), so a rename
can't take a held name out of its path.

APFS ignores letter case, so both forms do too: the regex spells each letter as a class, `matches` folds case.
Whether the kernel needs the classes was not measured here (a write in another case to an existing name may reach
the vnode by its stored name); the classes cost nothing and hold either way. Codex's bypass corpus measures case and
Unicode forms (`matches` folds with casefold, which the regex can't: a name only Unicode folding makes equal is
held by the file tools and not by the kernel, if APFS folds it at all).

Not on the list, and why: the rest of `.git` (commit, branch, checkout and stash must keep working); the user's
home-level files (shell startup, global git config, LaunchAgents: the commands profile doesn't make them writable
unless the work folder is ~; a separate set, not this one); a submodule's git folder deeper than one name under
`.git/modules`, and a bare repository's hooks (Codex's corpus). A `.git` (or any held name or held folder) that is a
link to a path named otherwise is held at that path (`link_filters`, #813 review 10).
"""
from __future__ import annotations

import fnmatch
import itertools
import os
import re
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePath

#: The names, by family. A pattern is path components; `*` in one is any run of characters but `/`, and a final
#: `**` is the folder itself and everything below it.
FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # git runs hooks and loads config (which can name programs: core.hooksPath, core.fsmonitor, filters, aliases).
    ("git", (".git/hooks/**", ".git/config", ".git/config.worktree", ".git/worktrees/*/config.worktree",
             ".git/modules/*/hooks/**", ".git/modules/*/config", ".gitmodules")),
    ("envrc", (".envrc",)),                                     # direnv runs it on cd
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

#: CI files: recognised, not denied (the user's list decision, #813 review 3). A CI job runs only after a push, on
#: the CI service and not on this Mac, so their guard moves to the push card (HR-2b), which uses `is_ci_file` to name
#: a pushed change to one. The same pattern form as FAMILIES; not in the kernel's profiles nor in `matches`.
CI_FILES: tuple[str, ...] = (".github/workflows/**", ".gitlab-ci.yml", ".circleci/**", "azure-pipelines.yml",
                             "Jenkinsfile", "bitbucket-pipelines.yml")

#: Dependency folders: a package installed there ships its own CI, editor and hook files, which nothing runs or loads
#: from there, so they pass the user's test as ordinary files. Without this a dependency install fails (#813 review).
#: Matched as a path component on the real path the kernel sees, so a link named so elsewhere gains nothing. Only
#: below the root (the work folder, or an MCP server's own and granted folders): when a root's real path already
#: passes through one (a repository kept inside node_modules), its profile has no exemption and every name stays
#: held (`exempts`, #813 review 2). Nor when a held name or held folder below a root is a link out of its folder (the
#: consumer reads the dependency's file through it), or the walk couldn't look everywhere (`held_folders`, #813 review
#: 9). The tool caches (.venv, uv and pip unpack folders) wait for Codex's measurement.
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


def _pattern_body(pattern: str) -> str:
    parts = pattern.split("/")
    below = parts[-1] == "**"
    if below:
        parts = parts[:-1]
    return "/".join(map(_component, parts)) + ("(/.*)?" if below else "")


def pattern_regex(pattern: str) -> str:
    """`pattern` at any depth of an absolute path."""
    return "^.*/" + _pattern_body(pattern) + "$"


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


def is_ci_file(path) -> bool:
    """Whether `path` (relative to a repository, or absolute) names a CI file (CI_FILES) at any depth, letter case
    folded. For HR-2b's push card; nothing is refused by it."""
    parts = _parts(path)
    return any(_fits(parts[i:], tuple(pattern.split("/"))) for pattern in CI_FILES for i in range(len(parts)))


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


def kernel_filters(folders: Iterable[Path], *, roots: Iterable[Path] = (),
                   aliased: bool = False) -> list[tuple[str, ...]]:
    """The SBPL filters a profile denies `file-write*` over, one tuple per family in FAMILIES' order, then one for
    the `core.hooksPath` targets of `folders` (the work folder, or an MCP server's granted folders) when any is
    set: the folder by its real path and by its name in its real parent, so a link there can't be swapped.
    Each name is wrapped to exempt dependency folders only when `exempts` holds for the real paths of `folders`
    and `roots` (an MCP server's own folder) and not `aliased` (#813 review 9: the walk found a held name that links
    out of its folder, or couldn't finish); otherwise it is the bare regex. The regexes stay built from constants."""
    from server.services.sandbox_profile import real, subpath
    folders = list(folders)
    exempt = _exempt(folders, roots) and not aliased
    out =[tuple(_filter(pattern_regex(p), exempt) for p in patterns) for _, patterns in FAMILIES]
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


def _exempt(folders: Iterable[Path], roots: Iterable[Path]) -> bool:
    from server.services.sandbox_profile import real
    return exempts(real(Path(os.path.abspath(p))) for p in (*folders, *roots))


def _filter(pattern: str, exempt: bool) -> str:
    """One regex filter, wrapped to leave dependency folders out when `exempt`."""
    from server.services.sandbox_profile import regex
    if not exempt:
        return regex(pattern)
    return f"(require-all {regex(pattern)} (require-not {regex(dependency_regex())}))"


# ── the ancestor hold (#813 review 6, ⓪Plan's option B) ─────────────────────
#
# The names above match by path. A command could rename a folder above one (`.git`, `.git/hooks`, `.vscode`, a
# submodule's `.git/modules`), write inside it under the new name, where no regex sees a held path, and rename it
# back. So the profiles also deny `file-write*` as a literal on every existing folder that is a held folder
# (`HELD_FOLDERS`) and on every folder above it up to the root (`command_sandbox.held_ancestors`, SBX-5a's
# mechanism): a literal holds that one folder in place (rename, removal, mode) while files inside are created,
# written and removed as before. The files themselves are the regexes' (writes), never literals here.
#
# A held folder that doesn't exist yet needs nothing, by design: `git init`, `git clone` and a first `.vscode` are
# made by mkdir. The residual is a folder prepared elsewhere, outside every held name, and renamed into a fresh place
# (SECURITY.md); git's consumer-view check is HR-1b's.

def _held_folder_tree() -> dict[str, dict]:
    """The held folders as a tree of case-folded names: each pattern's leading components that are plain names (up to
    its first `*`), the last component left out unless the pattern ends in `**` (then that folder is one).
    {".git": {"hooks": {}, "worktrees": {}, "modules": {}}, ".vscode": {}, ...}"""
    tree: dict[str, dict] = {}
    for _, patterns in FAMILIES:
        for pattern in patterns:
            parts = pattern.split("/")
            parts = parts[:-1]                      # a file, or the `**` after a folder that is held itself
            node = tree
            for part in parts:
                if "*" in part:
                    break                           # renaming a `*` component keeps the path matching
                node = node.setdefault(part.casefold(), {})
    return tree


HELD_FOLDERS = _held_folder_tree()

#: The walk's caps (#813 review 6). Past any of them, or on a folder it can't list, the walk is incomplete and the
#: profile holds the held folders by name instead (`folder_filters`): closed and constant in size, at the cost of
#: making a new one (a `.git`, a first `.vscode`) in that run. Measured on APFS tmp trees, warm (2026-11-11): the walk
#: takes about 10 ms for 5,000 entries and 90 ms for 49,500 (4,500 folders), where the whole commands profile took
#: about 110 ms.
WALK_ENTRIES = 50_000
WALK_DEPTH = 32
#: #813 review 7: every held folder found, and every folder above it, becomes a literal in the profile, which went to
#: `sandbox-exec -p` on the command line (ARG_MAX is 1 MiB on macOS, the environment included; a file since review 11)
#: and is built for every command. Uncapped, 2,000 small repositories took 23 s to build and the command couldn't
#: start at all (E2BIG, a 1.2 MB profile). So the walk also stops after `WALK_HELD` held folders, and after
#: `WALK_HELD_BYTES` of literals for them and the folders above them inside the walk (the count alone doesn't bound
#: that: 256 folders each 32 deep under long names could still pass ARG_MAX). Either keeps the profile well under the
#: limit: measured at the cap with 2,000 repositories in a pytest tmp folder, the commands profile is about 73 KB
#: (19 KB with none) and builds in about 0.03 s; the byte cap bounds the held literals to 128 KiB whatever the layout.
WALK_HELD = 256
WALK_HELD_BYTES = 128 * 1024
#: #813 review 11: links at held names and held folder names have their own cap, outside the two above: every one the
#: walk sees has its target held (`link_filters`, and the target and the folders above it in place) whatever the
#: held-folder cap did, since the by-name fallback can't name a target with an ordinary name. Only links at held names
#: count (a pnpm node_modules full of ordinary links doesn't). Past this cap no profile is built (`TooManyLinks`): the
#: command or the server doesn't start in the sandbox. The profile goes to sandbox-exec as a file (`-f`), so ARG_MAX
#: no longer bounds it; what bounds it is sandbox-exec's own compiler, which this cap stays inside. Measured on macOS
#: 26.6.2 (2026-11-11, `.vscode -> vsc` links in a pytest tmp folder, the commands profile): Python builds the profile
#: in ~0.2 s for 200 links and ~0.9 s for 1,000, but sandbox-exec's start (its compile) grows with the square of it:
#: 0.02 s with none, 0.09 s for 50, 1.0 s for 200, 4.8 s for 400, 10 s for 600, and at 800 it refuses the profile
#: ("data object length 65588 exceeds maximum (65535)"); at 4,096 it ran 4 min and aborted. ⓪Plan ruled 4,096 on the
#: build alone; 256 keeps the start near 1.5 s (#813 review 11, for ⓪Plan to confirm).
WALK_LINKS = 256


class TooManyLinks(RuntimeError):
    """#813 review 11: the walk saw more than `WALK_LINKS` links at held names: fail closed, no profile."""

    def __init__(self, limit: int):
        super().__init__(f"the folder has more than {limit:,} links at names of files that make something run later; "
                         "too many to hold, so nothing starts in the sandbox there")
        self.limit = limit


#: #813 review 8: the home folders macOS's privacy controls (TCC) protect. Listing one can raise a privacy prompt, so
#: the walk never lists them, nor the folders the user keeps closed (`private_folders`); their contents are held by
#: name instead (`private_filters`).
PRIVATE_HOME_FOLDERS = ("Desktop", "Documents", "Downloads", "Library", "Pictures", "Movies", "Music")


def private_folders(closed: Iterable[Path] = ()) -> list[Path]:
    """The folders the walk never lists, by real path (`~` may itself be a link): the user's closed folders and
    `PRIVATE_HOME_FOLDERS` in the home folder. Whether they exist is not checked here."""
    from server.services.sandbox_profile import real
    home = Path.home()
    out = [real(Path(os.path.abspath(os.path.expanduser(str(p))))) for p in closed]
    out += [real(home / name) for name in PRIVATE_HOME_FOLDERS]
    return list(dict.fromkeys(out))


def _identities(folders: Iterable[Path]) -> set[tuple[int, int]]:
    """`(st_dev, st_ino)` of each folder that exists (the folder's own metadata: reading it lists nothing). A
    folder whose metadata can't be read is left out: nothing reaches it through the walk's listing either way."""
    out = set()
    for folder in folders:
        try:
            st = os.stat(folder)
        except OSError:
            continue
        if stat.S_ISDIR(st.st_mode):
            out.add((st.st_dev, st.st_ino))
    return out


@dataclass(frozen=True)
class HeldWalk:
    folders: tuple[Path, ...]       # the held folders found, by real path, each after the ones above it
    complete: bool                  # False: a cap was reached or a folder couldn't be listed
    #: #813 review 8: the private folders (`private_folders`) the walk met inside a walked folder and didn't list,
    #: by real path; the profiles hold the held folders inside them by name (`private_filters`).
    skipped: tuple[Path, ...] = ()
    #: #813 review 9: the held names and held folder names the walk listed that are links whose real path leaves the
    #: folder the link is in (`aliases`, by their own path). #813 review 10: the real paths of every held name and
    #: held folder name the walk listed as a link, wherever they are (`targets`, each once, held in place), and the
    #: filters that hold the held names at them (`link_filters`: the profiles deny `file-write*` over them).
    aliases: tuple[Path, ...] = ()
    targets: tuple[Path, ...] = ()
    link_filters: tuple[str, ...] = ()


class _Incomplete(Exception):
    pass


def _listing(folder: Path, budget: list[int]) -> list[os.DirEntry]:
    """The folder's entries, counted against `budget`. A folder gone since it was seen lists as empty; any other
    error, or the budget running out, ends the walk incomplete."""
    entries = []
    try:
        with os.scandir(folder) as found:
            for entry in found:
                budget[0] -= 1
                if budget[0] < 0:
                    raise _Incomplete
                entries.append(entry)
    except (FileNotFoundError, NotADirectoryError):
        return []
    except OSError:
        raise _Incomplete from None
    return entries


def _is_folder_entry(entry: os.DirEntry) -> bool:
    """A folder itself, links not followed (a link's target is matched by its real path already)."""
    try:
        return entry.is_dir(follow_symlinks=False)
    except OSError:
        raise _Incomplete from None


#: What `(literal "…")` and the space before it add to a path in the profile.
_LITERAL_BYTES = len('(literal "")') + 1


def held_folders(folders: Iterable[Path], *, roots: Iterable[Path] = (), closed: Iterable[Path] = (),
                 max_entries: int | None = None, max_depth: int | None = None, max_held: int | None = None,
                 max_held_bytes: int | None = None, max_links: int | None = None) -> HeldWalk:
    """The existing held folders under `folders` (the work folder, or an MCP server's granted folders and its own),
    found by a bounded walk of real paths (caps `WALK_ENTRIES`, `WALK_DEPTH`, `WALK_HELD` and `WALK_HELD_BYTES`
    unless given). Links aren't followed. Dependency folders are skipped when `exempts` holds for `folders` and
    `roots`, as `kernel_filters` exempts them; otherwise they are walked too. A held folder with held folders of its
    own (`.git`) is searched for those only, never walked (git's objects).

    #813 review 8: a private folder (`private_folders(closed)`: the closed ones and the TCC home folders) met below
    a walked folder is never listed, nor anything under it; it is returned in `skipped`. It is recognised by its
    `(st_dev, st_ino)`, so a spelling in another case or Unicode form is the same folder. A walked folder that is one
    of them or lies inside one (a work folder in ~/Documents) is walked: Arslan works there already.

    #813 review 9: a held name or held folder name the walk lists as a link (from the listing's type: one call more,
    `realpath`, only for those) is an alias when its real path leaves the folder it is in; it is returned in
    `aliases`. A held folder with no held folders of its own (`.git/hooks`) is listed for its links too.

    #813 review 10: every such link, alias or not (`.vscode -> vsc`, `.envrc -> envrc.real`, a repository can check
    one out), has its real path in `targets` and the held names at that path in `link_filters` (`link_filters`); a
    target that is a folder is listed for links at held names as the consumer sees them through it (`through`), its
    entries counted as the walk's, except inside a private folder no walked folder lies in.

    #813 review 11: links are outside the held-folder caps (`WALK_HELD`, `WALK_HELD_BYTES`). Past those the walk goes
    on, keeping no further held folder (they are held by name: `complete` is False) but every link it sees at a held
    name, with its target and filters; only the entry and depth caps, or a folder it can't list, end it. Those links
    have their own cap, `max_links` (`WALK_LINKS`), past which `TooManyLinks` is raised: no profile, closed."""
    from server.services.sandbox_profile import real
    max_entries = WALK_ENTRIES if max_entries is None else max_entries
    max_depth = WALK_DEPTH if max_depth is None else max_depth
    max_held = WALK_HELD if max_held is None else max_held
    max_held_bytes = WALK_HELD_BYTES if max_held_bytes is None else max_held_bytes
    max_links = WALK_LINKS if max_links is None else max_links
    folders = [real(Path(os.path.abspath(p))) for p in folders]
    skip = _exempt(folders, roots)
    private_list = private_folders(closed)
    private_paths = set(map(str, private_list))
    private = _identities(private_list)
    private_inodes = {ino for _, ino in private}
    skipped: list[Path] = []
    starts = [f for f in dict.fromkeys(folders) if not any(o != f and o in f.parents for o in folders)]
    budget = [max_entries]
    found: list[Path] = []
    aliases: list[Path] = []
    targets: list[Path] = []
    filters: list[str] = []
    through_seen: set[Path] = set()
    counted: set[Path] = set(starts)          # the folders whose literal is counted (the starts: by the caller)
    held_bytes = [0]
    full = [False]                            # #813 review 11: a held-folder cap was reached; the walk goes on
    links = [0]

    def keep(path: Path) -> None:
        """`path` is a held folder: count it and the folders above it in the walk (each once) against the held-folder
        caps. Past either it isn't kept, nor is any later one (`full`), and the walk goes on for links."""
        if full[0] or len(found) >= max_held:
            full[0] = True
            return
        added = 0
        for folder in (path, *path.parents):
            if folder in counted:
                break                         # it, and every folder above it, is counted already
            added += len(os.fsencode(folder)) + _LITERAL_BYTES
        if held_bytes[0] + added > max_held_bytes:
            full[0] = True
            return
        for folder in (path, *path.parents):
            if folder in counted:
                break
            counted.add(folder)
        held_bytes[0] += added
        found.append(path)

    def alias(entry: os.DirEntry, folder: Path, seen_as: Path | None = None) -> None:
        """`entry` is a link. When a held name lies at it or below it (`_below`: it is a held name or a held folder
        name, at any depth, `*` components included; by `seen_as`, the path a consumer reads it by, when the walk
        reached `folder` through a link), #813 review 10: its real path is held in place, as a held folder
        (`targets`, for `held_ancestors(kept=...)`), the held names at that path are denied (`link_filters`), and a
        folder there is listed for further links (`through`). #813 review 9: when that real path leaves `folder`,
        it is an alias too: the profile drops the dependency exemption. #813 review 11: counted against `max_links`
        only, never the held-folder caps; past it, `TooManyLinks`."""
        path = folder / entry.name
        seen_as = seen_as or path
        below = _below(_parts(seen_as))
        if not below:
            return
        links[0] += 1
        if links[0] > max_links:
            raise TooManyLinks(max_links)
        if links[0] > max_links:
            raise TooManyLinks(max_links)
        target = Path(os.path.realpath(path))
        targets.append(target)
        filters.extend(link_filters(target, below))
        if target.parent != folder:
            aliases.append(path)
        try:
            listed = _is_folder(target)
        except OSError:                         # a loop, a folder it can't read: not mapped, so closed
            raise _Incomplete from None
        if listed:
            through(target, seen_as)

    def through(folder: Path, seen_as: Path) -> None:
        """#813 review 10: `folder`, the real path of a link a consumer reads as `seen_as`, listed for the links in it
        at held names by that path (`.claude -> c`, `c/settings.local.json -> ../x.json`): the folders on the way to
        a held name are listed too, a held folder (`**`) for its own entries only, as `inside_held` lists
        `.git/hooks`. Each folder once; never one the walk doesn't list (`private_folders`)."""
        if folder in through_seen or not listable(folder):
            return
        through_seen.add(folder)
        further = any(rest for rest, _ in _below(_parts(seen_as)))
        for entry in _listing(folder, budget):
            if _is_link_entry(entry):
                alias(entry, folder, seen_as / entry.name)
            elif further and _is_folder_entry(entry) and _below(_parts(seen_as / entry.name)):
                through(folder / entry.name, seen_as / entry.name)

    #: The private folders no walked folder lies at or inside (Arslan works in those), as strings: `listable`'s test,
    #: by prefix (#813 review 11: `Path.parents` per link was most of a large walk's time).
    unlisted = [str(p) for p in private_list if not any(s == p or p in s.parents for s in starts)]

    def listable(folder: Path) -> bool:
        """Not inside a private folder, unless a walked folder lies at or inside that one (Arslan works there)."""
        text = str(folder)
        return not any(text == p or text.startswith(p.rstrip("/") + "/") for p in unlisted)

    def inside_held(folder: Path, tree: dict) -> None:
        for entry in _listing(folder, budget):
            if _is_link_entry(entry):
                alias(entry, folder)
                continue
            sub = tree.get(entry.name.casefold())
            if sub is not None and _is_folder_entry(entry):
                keep(folder / entry.name)
                inside_held(folder / entry.name, sub)       # an empty `sub` too (.git/hooks): for its links

    stack = [(start, 0) for start in reversed(starts)]
    try:
        while stack:
            folder, depth = stack.pop()
            for entry in _listing(folder, budget):
                if _is_link_entry(entry):
                    alias(entry, folder)
                    continue
                if not _is_folder_entry(entry):
                    continue
                name = entry.name.casefold()
                if skip and name in _FOLDED_DEPENDENCIES:
                    continue
                path = folder / entry.name
                if _is_private(entry, path, private, private_inodes, private_paths):
                    skipped.append(path)
                    continue
                tree = HELD_FOLDERS.get(name)
                if tree is not None:
                    keep(path)
                    if tree:
                        inside_held(path, tree)
                        continue
                if depth + 1 > max_depth:
                    raise _Incomplete
                stack.append((path, depth + 1))
    except _Incomplete:
        complete = False
    else:
        complete = not full[0]
    return HeldWalk(tuple(dict.fromkeys(found)), complete, tuple(dict.fromkeys(skipped)),
                    tuple(dict.fromkeys(aliases)), tuple(dict.fromkeys(targets)), tuple(dict.fromkeys(filters)))


def _is_link_entry(entry: os.DirEntry) -> bool:
    """A link, from the listing's own type (no further call where the file system reports it)."""
    try:
        return entry.is_symlink()
    except OSError:
        raise _Incomplete from None


#: FAMILIES' patterns as (components, whether everything below them is held): `.husky/**` is ((".husky",), True).
_SPLIT: tuple[tuple[tuple[str, ...], bool], ...] = tuple(
    (tuple(p.split("/")[:-1]), True) if p.endswith("/**") else (tuple(p.split("/")), False)
    for _, patterns in FAMILIES for p in patterns)

#: Each pattern's first component, case-folded, as one regex (`_below`'s quick test).
_FIRST_COMPONENT = re.compile("|".join(sorted({fnmatch.translate(fixed[0].casefold()) for fixed, _ in _SPLIT})))


def _matcher(name: str):
    """A test of one case-folded component against a pattern component: equality for a plain name, else its glob."""
    name = name.casefold()
    if not any(ch in name for ch in "*?["):
        return name.__eq__
    return lambda part, pattern=re.compile(fnmatch.translate(name)): pattern.match(part) is not None


_SPLIT_MATCHERS = tuple(tuple(map(_matcher, fixed)) for fixed, _ in _SPLIT)


def _below(parts: tuple[str, ...]) -> tuple[tuple[tuple[str, ...], bool], ...]:
    """#813 review 10: the held names at and below a path with components `parts`, by the patterns' own components,
    relative to it: `((), False)` is the path itself (a held file), `((), True)` the path and everything below it,
    `(("tasks.json",), False)` that name in it, `(("hooks",), True)` that folder and everything below it,
    `(("modules", "*", "config"), False)` a `*` component on the way. Empty: no held name at or below it.
    For `.vscode` that is its four files; for `.git` its hooks, configs, worktrees' and modules' ones.
    #813 review 11: every match needs a component of `parts` to match some pattern's first component, so a path with
    none (a pnpm node_modules' links) is answered by one regex per component; the rest compares case-folded components
    with each pattern's compiled ones (`_SPLIT_MATCHERS`), the same test as `fnmatchcase` on folded names."""
    folded = tuple(part.casefold() for part in parts)
    if not any(_FIRST_COMPONENT.match(part) for part in folded):
        return ()
    out: list[tuple[tuple[str, ...], bool]] = []
    n = len(folded)
    for (fixed, below), matchers in zip(_SPLIT, _SPLIT_MATCHERS):
        width = len(matchers)
        if below and any(all(m(folded[i + j]) for j, m in enumerate(matchers)) for i in range(n - width + 1)):
            out.append(((), True))             # at or below a `**` folder: everything below the path is held
            continue
        for k in range(1, min(width, n) + 1):     # the path is the pattern's k-th component
            if all(m(part) for part, m in zip(folded[n - k:], matchers)):
                out.append((fixed[k:], below))
    return tuple(dict.fromkeys(out))


#: A component in a regex: a run of characters but `/`.
_ANY_COMPONENT = "/[^/]+"


def link_filters(target: Path, below: Iterable[tuple[tuple[str, ...], bool]]) -> tuple[str, ...]:
    """#813 review 10: the filters that hold, at `target` (the real path of a link at a held name or held folder
    name), the held names `below` (`_below`) the link: what a consumer reads through the link, whatever `target` is
    named and wherever it is. A fixed name as a `literal` (a file) or a `subpath` (`**`), each by its real path and by
    its spelling under `target` when another link in there leads elsewhere; a name with a `*` component as
    `(require-all (subpath <folder>) (regex …))`, the folder before its first `*` by its real path, and the regex
    built from the pattern's components with that folder's depth counted in `[^/]+` components (never its path), so
    it holds that name exactly under that folder and nothing deeper (`.claude -> c`: `c/settings.json`, not
    `c/x/settings.json`; past `MAX_REGEX`, any depth below the folder: closed, not open); that folder itself as a
    literal too, so it stays in place or, missing, isn't made. And, for a path in there that doesn't exist (a broken
    link's target, a name not made yet), its first missing component as a literal: nothing can be made there, a link
    included, that would carry the name elsewhere. Paths go in as SBPL strings (`sbpl_string`), never into a regex."""
    from server.services.sandbox_profile import literal, regex, subpath
    out: list[str] = []
    for rest, everything in below:
        fixed = tuple(itertools.takewhile(lambda part: "*" not in part, rest))
        wild = rest[len(fixed):]
        lexical = target.joinpath(*fixed)
        anchor = _real_below(target, fixed)
        spellings = tuple(dict.fromkeys((anchor, lexical)))
        if not wild:
            out += [subpath(s) if everything else literal(s) for s in spellings]
        else:
            body = "/".join(map(_component, wild)) + ("(/.*)?" if everything else "")
            counted = "^" + _ANY_COMPONENT * len(_parts(anchor)) + "/" + body + "$"
            pattern = counted if len(counted) <= MAX_REGEX else "^.*/" + body + "$"
            out += [f"(require-all {subpath(anchor)} {regex(pattern)})", *map(literal, spellings)]
        missing = _first_missing(anchor)
        if missing is not None:
            out.append(literal(missing))
    return tuple(dict.fromkeys(out))


def _real_below(target: Path, fixed: tuple[str, ...]) -> Path:
    """`realpath(target/fixed...)` for `target`, a real path already (#813 review 11: one `lstat` per component
    instead of `realpath`'s walk from the root, which was much of a large walk's time). Only when a component is a link
    does it take `realpath`; a missing one ends it, as `realpath` keeps the rest as written."""
    path = target
    for name in fixed:
        path = path / name
        try:
            info = os.lstat(path)
        except (FileNotFoundError, NotADirectoryError):
            return target.joinpath(*fixed)
        if stat.S_ISLNK(info.st_mode):
            return Path(os.path.realpath(target.joinpath(*fixed)))
    return path


def _first_missing(path: Path) -> Path | None:
    """The first component of `path`, from the top, that doesn't exist (a link counts as existing), or None."""
    if os.path.lexists(path):
        return None
    while not os.path.lexists(path.parent) and path.parent != path:
        path = path.parent
    return path


def _is_private(entry: os.DirEntry, path: Path, private: set[tuple[int, int]], inodes: set[int],
                paths: set[str]) -> bool:
    """`entry` (a folder) is a private folder: by its real path's spelling, or by `(st_dev, st_ino)` (the inode from
    the listing, the device read only when the inode is one of theirs)."""
    if str(path) in paths:
        return True
    try:
        if entry.inode() not in inodes:
            return False
        st = entry.stat(follow_symlinks=False)
    except OSError:
        raise _Incomplete from None
    return (st.st_dev, st.st_ino) in private


def _chains(tree: dict, above: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    out = []
    for name, sub in tree.items():
        out.append((*above, name))
        out.extend(_chains(sub, (*above, name)))
    return out


def folder_filters(folders: Iterable[Path], *, roots: Iterable[Path] = (), aliased: bool = False) -> tuple[str, ...]:
    """The fallback when the walk is incomplete: every held folder held by its name at any depth (the folder itself,
    not what's inside), with the same dependency exemption as `kernel_filters` (none when `aliased`). Making one is
    then refused too."""
    exempt = _exempt(list(folders), roots) and not aliased
    return tuple(_filter("^.*/" + "/".join(map(_component, chain)) + "$", exempt) for chain in _chains(HELD_FOLDERS))


def held_name_regex() -> str:
    """Every held folder by its name at any depth, as one regex (the alternation of `folder_filters`' names)."""
    return "^.*/(" + "|".join("/".join(map(_component, chain)) for chain in _chains(HELD_FOLDERS)) + ")$"


#: sandbox-exec refuses a string past about 1,000 bytes ("Error reading string", measured on macOS 26.6.2: 1,005
#: read, 1,032 not), so a regex here stays under this.
MAX_REGEX = 960


def held_path_regexes() -> tuple[str, ...]:
    """Every held folder by its name (`held_name_regex`) and every held name (FAMILIES, one regex per family) at any
    depth: the regexes that, together, match a held path."""
    out = (held_name_regex(),
           *("^.*/(" + "|".join(map(_pattern_body, patterns)) + ")$" for _, patterns in FAMILIES))
    if max(map(len, out)) > MAX_REGEX:
        raise ValueError("a held-path regex is past what sandbox-exec reads")
    return out


def symlink_filters() -> tuple[str, ...]:
    """#813 review 9, part 2: a link made at a held name or a held folder name, anywhere (a dependency folder too), by
    `symlink` or by renaming a link made elsewhere onto it, which profiles deny `file-write-create` over. An ordinary
    file or folder of those names is another vnode type and stays as it was (measured on macOS 26.6.2)."""
    from server.services.sandbox_profile import regex
    return tuple(f"(require-all (vnode-type SYMLINK) {regex(r)})" for r in held_path_regexes())


def private_filters(skipped: Iterable[Path]) -> tuple[str, ...]:
    """#813 review 8: the by-name hold inside the private folders the walk didn't list (`HeldWalk.skipped`):
    `(require-all (subpath <folder>) <regex>)` for each of `held_path_regexes`. The path goes into a `subpath` string
    literal, never into the regex. Making a held folder in there is refused too; elsewhere in the walked folders it is
    not. #813 review 9: with no dependency exemption, the held names in there too: the walk can't see an alias there."""
    from server.services.sandbox_profile import regex, subpath
    return tuple(f"(require-all {subpath(folder)} {regex(r)})"
                 for folder in dict.fromkeys(skipped) for r in held_path_regexes())

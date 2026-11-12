"""HR-1b (v0.1.64): git may update a repository's config under this conversation's git_config grant; what it may change
there is an allowlist, and everything else is put back after the command.

Under the grant the commands profile leaves the config names (`run_later.GIT_CONFIG`) writable where this walk looks.
terminal_exec calls `snapshot` before (every such config under the work folder, by a bounded walk; an error fails
closed: the command runs held) and `restore` after: a changed or new config is read by git's own reader in a fixed
environment; a key off ALLOWED added, changed or removed is put back (the pre-run bytes with only the allowed changes
replayed, or a new repository's file minus every key off the list), read back and compared, written atomically; any
step failing restores the pre-run bytes whole. Review delta 2: the group ends first; a snapshot starts from the last
put-back (`_BASELINES`); a config with a second name drops the lift (`Linked`); a put-back still refused once flags
and ACL are cleared is `held` and ends the grant. Review deltas 3 and 4: a process in its own session can write after
the put-back, so once any folder had the grant every command, of any conversation, is preceded by `recheck`, refused
if a walk or a put-back fails; a config removed alone is written back. Not covered (residuals): a writer after that
check, git outside Arslan or in its other runners (plugin hooks, MCP servers); the file tools run no git. The model
reads key names, never a value. Codex's corpus owns the adversarial shapes: see the PR body.

HR-1c, D: a path rule can't see a write to what git later reads through another name (a `.git` file or link,
`commondir`, a submodule at any depth, a bare repository, a hooks path or setting in an included file). So around
every command in the sandbox, and one under the outside floor that holds run-later files, where seatbelt can start,
`snapshot(view=True)` also records git's own view of each repository the same walk finds (`view`: git, common and
hooks folders, `rev-parse` only), each hooks folder's entries and the keys off ALLOWED reached through an include;
`restore` puts the configs git reads back through the allowlist above (with or without the grant; without it no
baseline is kept), then quarantines new or changed hooks inside the work folder, names a moved repository, renames
aside a new `.git` pointing outside, and checks the includes (`_check_includes`). Nothing a repository names runs:
files are read directly, and git runs only `rev-parse` and `config --list`/`--file` under `_env`, the first two in a
read-only, no-network seatbelt profile with a time limit, failing closed (the repository is named as unchecked).
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

#: The keys git may change under the grant: (section, has a subsection, variable), as git compares them: section and
#: variable names fold case, a subsection is kept verbatim. Nothing here names a program.
ALLOWED: frozenset[tuple[str, bool, str]] = frozenset({
    ("remote", True, "url"), ("remote", True, "fetch"), ("remote", True, "pushurl"),
    ("branch", True, "remote"), ("branch", True, "merge"), ("branch", True, "rebase"),
    ("user", False, "name"), ("user", False, "email"),
    ("core", False, "repositoryformatversion"), ("core", False, "filemode"), ("core", False, "bare"),
    ("core", False, "logallrefupdates"), ("core", False, "ignorecase"), ("core", False, "precomposeunicode"),
    ("init", False, "defaultbranch"),
    ("submodule", True, "url"), ("submodule", True, "active"),
    ("pull", False, "rebase"), ("push", False, "default"),
})

#: How many folders the walk opens before it gives up (fails closed). node_modules and `.git` folders aren't opened.
MAX_FOLDERS = 30_000
_MAX_CONFIG = 1 << 20
_TIMEOUT_S = 10
#: A real git first: /usr/bin/git is xcrun's shim, which under a fresh empty home takes about 0.9 s a run.
_GITS = ("/Library/Developer/CommandLineTools/usr/bin/git", "/opt/homebrew/bin/git", "/usr/local/bin/git",
         "/Applications/Xcode.app/Contents/Developer/usr/bin/git", "/usr/bin/git")
#: At most this many key names in what the model reads, each cut to this length.
_NAMES_SHOWN, _NAME_MAX = 20, 120
#: D: `view`'s limit for each batch of repositories (past it, those are unanswered: fail closed), the entries read in
#: one hooks folder, an included file's names in the message, and the sandbox git is asked in.
VIEW_TIMEOUT_S, _MAX_HOOKS, _PATH_MAX = 5, 1000, 400
_SANDBOX_EXEC = "/usr/bin/sandbox-exec"
#: Where moved hooks and included files go; None is Arslan's data folder (`quarantine/git-hooks`), closed to commands.
QUARANTINE: Path | None = None


class GuardError(Exception):
    """The check could not be done: the caller fails closed."""


Key = tuple[str, str | None, str]       # (section folded, subsection verbatim or None, variable folded)


def split_key(name: str) -> Key:
    """A key as git prints it (`section[.subsection].variable`), folded the way git compares it."""
    first, last = name.find("."), name.rfind(".")
    if first <= 0 or last == len(name) - 1:
        raise GuardError("a config key git printed has no section or variable")
    return name[:first].lower(), (name[first + 1:last] if last > first else None), name[last + 1:].lower()


def allowed(key: Key | str) -> bool:
    section, subsection, variable = split_key(key) if isinstance(key, str) else key
    return (section, subsection is not None, variable) in ALLOWED


def _entries(folder: Path) -> list[os.DirEntry]:
    with os.scandir(folder) as found:
        return list(found)


def _git_dir_configs(git: Path) -> list[Path]:
    """The config files the grant lifts inside one `.git` folder, names folded as APFS folds them."""
    out: list[Path] = []
    for entry in _entries(git):
        name = entry.name.casefold()
        if name in ("config", "config.worktree") and not entry.is_dir(follow_symlinks=False):
            out.append(Path(entry.path))
        elif name in ("worktrees", "modules") and entry.is_dir(follow_symlinks=False):
            want = "config.worktree" if name == "worktrees" else "config"
            for each in _entries(Path(entry.path)):
                if each.is_dir(follow_symlinks=False):
                    out.extend(Path(inner.path) for inner in _entries(Path(each.path))
                               if inner.name.casefold() == want and not inner.is_dir(follow_symlinks=False))
    return out


def _private(folder: Path, closed) -> set[tuple[int, int]]:
    """The private folders the walk doesn't open, as HR-1's doesn't (#813 review 8), except one `folder` is in; the
    profile holds their configs under the grant too (`run_later.private_filters`)."""
    from server.services import run_later
    from server.services.sandbox_profile import real
    inside = real(Path(os.path.abspath(folder)))
    return run_later._identities(p for p in run_later.private_folders(closed) if not (p == inside or p in inside.parents))


def config_files(folder: Path, closed=()) -> list[Path]:
    """Every config the grant lifts under `folder`, sorted (the profile lifts only where this walk looks)."""
    return _walk(folder, closed)[0]


_GIT_FOLDER = frozenset({"head", "objects", "refs"})


def _walk(folder: Path, closed=()) -> tuple[list[Path], list[Path]]:
    """The configs the grant lifts, and (D) each repository by the entry git is pointed at: a `.git` folder, file or
    link, a bare repository (a folder holding HEAD, objects and refs, not walked into), and a submodule's git folder
    under `modules/` at any depth, `/` in its name included. No link, node_modules, private folder or `.git` folder
    past its configs and modules is opened. Too many folders, or an error, raises."""
    found: list[Path] = []
    repos: list[Path] = []
    private = _private(folder, closed)
    stack, opened = [(Path(folder), False)], 0          # (folder, inside a git folder's `modules`)
    while stack:
        current, modules = stack.pop()
        opened += 1
        if opened > MAX_FOLDERS:
            raise GuardError(f"more than {MAX_FOLDERS} folders to check")
        try:
            entries = _entries(current)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError as exc:
            raise GuardError(f"a folder could not be read: {exc.strerror or exc}") from None
        if _GIT_FOLDER <= {entry.name.casefold() for entry in entries}:
            repos.append(current)
            stack.append((current / "modules", True))
            continue
        for entry in entries:
            name = entry.name.casefold()
            if name == ".git" and not modules and not entry.is_dir(follow_symlinks=False):
                repos.append(Path(entry.path))
            if not entry.is_dir(follow_symlinks=False) or (name == "node_modules" and not modules):
                continue
            try:
                if private and (entry.stat(follow_symlinks=False).st_dev, entry.inode()) in private:
                    continue
            except OSError as exc:
                raise GuardError(f"a folder could not be read: {exc.strerror or exc}") from None
            if name == ".git" and not modules:
                try:
                    found.extend(_git_dir_configs(Path(entry.path)))
                except OSError as exc:
                    raise GuardError(f"a .git folder could not be read: {exc.strerror or exc}") from None
                repos.append(Path(entry.path))
                stack.append((Path(entry.path) / "modules", True))
            else:
                stack.append((Path(entry.path), modules))
    return sorted(found), repos


def _read(path: Path) -> bytes | None:
    """A regular file's bytes (a link followed), None when missing; anything else raises GuardError."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        raise GuardError(f"a config could not be read: {exc.strerror or exc}") from None
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise GuardError("a config is not a regular file")
        data = handle.read(_MAX_CONFIG + 1)
    if len(data) > _MAX_CONFIG:
        raise GuardError("a config is larger than 1 MiB")
    return data


class Linked(GuardError):
    """A config is not a regular file with one name (a hard link, or a link): no lift this run (review delta 2)."""


def _single(path: Path) -> os.stat_result | None:
    """`path`'s own metadata when it is a regular file with one name, None when missing; else Linked."""
    try:
        st = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        raise GuardError(f"a config could not be read: {exc.strerror or exc}") from None
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise Linked("a config has another name, or is a link")
    return st


#: Review delta 2: each config as the last put-back left it (bytes, mode; None: a new repository's it couldn't write),
#: taken instead of the file. Oldest out past the caps. Cost: a key the user set outside Arslan meanwhile goes too.
_BASELINES: dict[Path, tuple[bytes, int] | None] = {}
_MAX_BASELINES, _MAX_BASELINE_BYTES = 4096, 32 << 20


def _keep_baseline(path: Path, value: tuple[bytes, int] | None) -> None:
    _BASELINES.pop(path, None)
    _BASELINES[path] = value
    while len(_BASELINES) > _MAX_BASELINES or sum(len(v[0]) for v in _BASELINES.values() if v) > _MAX_BASELINE_BYTES:
        del _BASELINES[next(iter(_BASELINES))]


@dataclass(frozen=True)
class Snapshot:
    folder: Path
    files: dict[Path, bytes]
    closed: tuple[Path, ...] = ()
    modes: dict[Path, int] = field(default_factory=dict)
    grant: bool = True              # under the git_config grant: baselines kept (D without it: none)
    viewed: bool = False            # D: git's view was taken (`repos`, `hooks`, `included`)
    repos: dict[Path, Answer | None] = field(default_factory=dict)
    hooks: dict[Path, dict[str, Hook]] = field(default_factory=dict)
    included: dict[Path, Included] = field(default_factory=dict)


def snapshot(folder: Path, closed=(), *, grant: bool = True, view: bool = False) -> Snapshot:
    """Before the command: each config's path, bytes and mode, its baseline when there is one (under the grant), and
    with `view` git's own view (D), whose configs join the walk's. Raises GuardError (no grant this run), Linked
    under the grant when a config isn't a regular file with one name (without it such a file is left alone)."""
    folder = Path(os.path.abspath(folder))
    closed = tuple(closed)
    walked, repos = _walk(folder, closed)
    seen = _survey(repos) if view else _Survey({}, {}, [], {})
    files, modes = {}, {}
    for path in _merged(walked, seen.configs):
        try:
            st, data = _single(path), _read(path)
        except Linked:
            if grant:
                raise
            continue
        if st is None or data is None or (grant and path in _BASELINES and _BASELINES[path] is None):
            continue                                      # gone, or a new repository's whose put-back failed
        files[path], modes[path] = (grant and _BASELINES.get(path)) or (data, stat.S_IMODE(st.st_mode))
    return Snapshot(folder, files, closed, modes, grant, view, seen.answers, seen.hooks, seen.included)


def _git_binary() -> str:
    for path in _GITS:
        if os.access(path, os.X_OK):
            return path
    raise GuardError("git was not found")


def _env(scratch: Path) -> dict[str, str]:
    """The pinned environment of every git run here: nothing of the caller's (no GIT_*), no system, global or XDG
    config, a home and temp folder of its own (`scratch`), C locale, no prompt, no repository above its folder."""
    return {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(scratch), "TMPDIR": str(scratch),
            "XDG_CONFIG_HOME": "", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "LANG": "C", "GIT_CEILING_DIRECTORIES": str(scratch.parent)}


def _git(args: list[str], scratch: Path) -> subprocess.CompletedProcess:
    """git with the pinned environment (`_env`). No network: `git config --file` reads and writes that file only."""
    try:
        return subprocess.run([_git_binary(), *args], cwd=scratch, env=_env(scratch), capture_output=True,
                              timeout=_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GuardError(f"git could not run: {exc}") from None


# ── D: git's own view, never running anything from the repository ───────────

Answer = tuple[Path, Path, Path]        # the git folder, the common folder and the hooks folder, real paths
#: rev-parse runs no hook, filter or fsmonitor; `--git-path hooks` is git's own hooks folder, core.hooksPath (an
#: included one too) followed, so `-c core.hooksPath=/dev/null` would replace the very answer asked for.
_ASK = ("-c", "core.fsmonitor=false", "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir",
        "--git-path", "hooks")
#: The effective config, includes followed, each value with its file: `config --list` reads files only.
_LIST = ("config", "--list", "--includes", "--null", "--show-origin")
#: How many repositories are asked at once, one sandbox-exec each (measured 2026-11-11: one about 17 ms, three
#: together about 21 ms).
_AT_ONCE = 8


def _top(entry: Path) -> Path:
    """Where git runs a repository's hooks from: its top, or a bare one's folder."""
    return entry.parent if entry.name.casefold() == ".git" else entry


def _each(entries: list[Path], args: tuple[str, ...]) -> dict[Path, bytes | None]:
    """git's output for `args` for each repository, its git folder given (nothing discovered), from its top (so a
    relative hooksPath resolves as when git runs a hook); None where git failed or gave none in VIEW_TIMEOUT_S. In
    sandbox-exec with a read-only profile (default deny, no network, writes to its scratch only) and `_env`."""
    from server.services.sandbox_profile import default_deny_profile
    outputs: dict[Path, bytes | None] = dict.fromkeys(entries)
    with tempfile.TemporaryDirectory(prefix="arslan-git-view-") as name:
        scratch = Path(name)
        for start in range(0, len(entries), _AT_ONCE):
            running, deadline = [], time.monotonic() + VIEW_TIMEOUT_S
            try:
                argv = [_SANDBOX_EXEC, "-p", default_deny_profile(writable=[scratch]), _git_binary()]
                for entry in entries[start:start + _AT_ONCE]:
                    running.append((entry, subprocess.Popen(
                        [*argv, f"--git-dir={entry}", *args], cwd=_top(entry), env=_env(scratch),
                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)))
            except (OSError, GuardError):
                pass                                      # those not started stay unanswered
            for entry, process in running:
                try:
                    out, _ = process.communicate(timeout=max(0.0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                    continue
                if process.returncode == 0:
                    outputs[entry] = out
    return outputs


def view(entries: list[Path]) -> dict[Path, Answer | None]:
    """git's answer for each repository (`_each`), None where it gave none (the caller fails closed)."""
    answers: dict[Path, Answer | None] = {}
    for entry, out in _each(entries, _ASK).items():
        lines = out.decode("utf-8", errors="surrogateescape").split("\n") if out is not None else []
        answers[entry] = (tuple(Path(os.path.realpath(line)) for line in lines[:3])
                          if len(lines) == 4 and lines[3] == "" and all(lines[:3]) else None)
    return answers


#: Off the allowlist, by key: the (file, value) pairs reached through an included file (not a config git reads
#: directly, which the allowlist covers). None: git couldn't list it.
Included = dict[Key, frozenset[tuple[Path, str]]] | None


def _parse_included(out: bytes | None, direct: set[Path]) -> Included:
    items = out.split(b"\0") if out is not None else []
    if items[-1:] != [b""] or len(items) % 2 != 1:
        return None
    found: dict[Key, set[tuple[Path, str]]] = {}
    try:
        for origin, item in zip(items[:-1:2], items[1:-1:2]):
            where = origin.decode("utf-8", errors="surrogateescape")
            name, _, value = item.decode("utf-8", errors="surrogateescape").partition("\n")
            key = split_key(name)
            if not where.startswith("file:"):
                return None                               # git reads no other origin here: unknown, unchecked
            path = Path(os.path.realpath(where[len("file:"):]))
            if path not in direct and not allowed(key):
                found.setdefault(key, set()).add((path, value))
    except GuardError:
        return None
    return {key: frozenset(pairs) for key, pairs in found.items()}


def _fallback(entry: Path) -> Answer | None:
    """Where git gave no answer: the entry itself when it is a folder (a link followed), so its hooks and config are
    still compared. The repository is named as unchecked either way."""
    real = Path(os.path.realpath(entry))
    return (real, real, real / "hooks") if os.path.isdir(real) else None


def _configs(answer: Answer) -> list[Path]:
    """The config files git reads for a repository: the common config, the worktree configs, a linked worktree's."""
    git_dir, common, _ = answer
    paths = [common / "config", common / "config.worktree", git_dir / "config.worktree"]
    try:
        with os.scandir(common / "worktrees") as found:
            paths += [Path(e.path) / "config.worktree" for e in found if e.is_dir(follow_symlinks=False)]
    except OSError:
        pass
    return [p for p in dict.fromkeys(paths) if os.path.lexists(p)]


Hook = tuple[str, str, bool]            # kind, a file's hash or a link's target, executable


def _hooks(folder: Path) -> dict[str, Hook]:
    """A hooks folder's entries, by name. A missing folder has none; too many, or one unreadable, raises GuardError."""
    out: dict[str, Hook] = {}
    try:
        with os.scandir(folder) as found:
            for entry in found:
                if len(out) >= _MAX_HOOKS:
                    raise GuardError("a hooks folder has too many entries")
                mode = entry.stat(follow_symlinks=False).st_mode
                if stat.S_ISLNK(mode):
                    out[entry.name] = ("link", os.readlink(entry.path), False)
                elif stat.S_ISREG(mode):
                    fd = os.open(entry.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                    with os.fdopen(fd, "rb") as handle:
                        digest = hashlib.file_digest(handle, "sha256").hexdigest()
                    out[entry.name] = ("file", digest, bool(mode & 0o111))
                else:
                    out[entry.name] = ("folder" if stat.S_ISDIR(mode) else "other", "", False)
    except (FileNotFoundError, NotADirectoryError):
        return {}
    except OSError as exc:
        raise GuardError(f"a hooks folder could not be read: {exc.strerror or exc}") from None
    return out


@dataclass
class _Survey:
    answers: dict[Path, Answer | None]
    hooks: dict[Path, dict[str, Hook]]
    configs: list[Path]
    included: dict[Path, Included]


def _survey(repos: list[Path]) -> _Survey:
    """git's answers, each hooks folder's entries, the config paths and the included keys of `repos`. With none,
    git never starts."""
    answers = view(repos) if repos else {}
    used = [a for a in (answer or _fallback(entry) for entry, answer in answers.items()) if a]
    asked = [entry for entry, answer in answers.items() if answer is not None]
    listed = _each(asked, _LIST) if asked else {}
    included = {entry: _parse_included(listed.get(entry), {Path(os.path.realpath(p)) for p in _configs(answers[entry])})
                for entry in asked}
    return _Survey(answers, {answer[2]: _hooks(answer[2]) for answer in used},
                   sorted({path for answer in used for path in _configs(answer)}), included)


def _merged(walked: list[Path], seen: list[Path], keep=lambda path: True) -> list[Path]:
    """The walk's configs and the ones git reads (real paths), each file once, by its walk spelling."""
    reals = {Path(os.path.realpath(path)) for path in walked}
    return sorted(set(walked) | {path for path in seen if path not in reals and keep(path)})


Values = dict[Key, list[str]]


def parse(path: Path, scratch: Path) -> tuple[Values, dict[Key, str]]:
    """One config file as git reads it, includes not followed: each key's values in order (an implicit `true` reads
    as "true"), and the name git printed for it. A failed read raises GuardError."""
    ran = _git(["config", "--file", str(path), "--list", "--null", "--no-includes"], scratch)
    if ran.returncode != 0:
        raise GuardError("git could not read a config")
    values: Values = {}
    names: dict[Key, str] = {}
    for item in ran.stdout.split(b"\0")[:-1]:
        name, newline, value = item.decode("utf-8", errors="surrogateescape").partition("\n")
        key = split_key(name)
        values.setdefault(key, []).append(value if newline else "true")
        names.setdefault(key, name)
    return values, names


def _set(path: Path, scratch: Path, *args: str) -> None:
    ran = _git(["config", "--file", str(path), *args], scratch)
    # --unset-all exits 5 when the key is absent: nothing to remove.
    if ran.returncode != 0 and not (args[0] == "--unset-all" and ran.returncode == 5):
        raise GuardError("git could not update a config")


@dataclass
class Outcome:
    reverted: list[str] = field(default_factory=list)    # key names put back, as git prints them
    restored: list[str] = field(default_factory=list)    # configs restored whole (a check failed), relative paths
    unchecked: bool = False                               # the walk after the command failed
    held: list[str] = field(default_factory=list)         # configs that couldn't be written back, relative paths
    replaced: list[str] = field(default_factory=list)     # review delta 3: configs removed, written back
    # D: hook names quarantined; repositories whose metadata resolves elsewhere; `.git` entries renamed aside; hooks
    # folders outside the work folder with a new hook; repositories git couldn't answer for; "keys in file" of
    # included files quarantined, and of those outside; whether the check couldn't finish.
    quarantined: list[str] = field(default_factory=list)
    moved: list[str] = field(default_factory=list)
    aside: list[str] = field(default_factory=list)
    outside: list[str] = field(default_factory=list)
    unanswered: list[str] = field(default_factory=list)
    includes_moved: list[str] = field(default_factory=list)
    includes_outside: list[str] = field(default_factory=list)
    unfinished: bool = False
    #: Repositories (their top, a real path) whose next git command asks first, with what the card names.
    marks: dict[Path, str] = field(default_factory=dict)

    def message(self) -> str:
        """What the model reads and the step shows: key names, hook names and paths only, never a value or content.
        "" when nothing was done."""
        parts = []
        if self.reverted:
            shown = [_clean(n) for n in self.reverted[:_NAMES_SHOWN]]
            more = len(self.reverted) - len(shown)
            parts.append("Arslan put back git settings the git_config permission doesn't cover (they can name programs "
                         "that run later): " + ", ".join(shown) + (f" and {more} more" if more > 0 else "")
                         + ". Upstreams, remotes and user.name/email it changed were kept.")
        if self.restored:
            parts.append(f"Arslan couldn't check the git settings changed in {len(self.restored)} config file(s), so "
                         "it restored them as they were (a new repository's config was removed), keeping none of it.")
        if self.unchecked:
            parts.append("Arslan couldn't look through the working folder after this command, so it restored the git "
                         "settings it had saved; a repository this command created may not have been checked.")
        if self.replaced:
            parts.append(f"A git config file was removed ({', '.join(map(_clean, self.replaced[:_NAMES_SHOWN]))}); "
                         "Arslan wrote it back as it was at its last check.")
        if self.held:
            parts.append(HELD_NOTE)
        for names, text in (
                (self.quarantined, "Arslan moved git hooks this command added or changed into its quarantine folder, "
                                   "where nothing runs them"),
                (self.aside, "Arslan renamed aside new .git files or links that pointed outside the working folder"),
                (self.includes_moved, "Arslan moved config files git includes, changed by this command, into its "
                                      "quarantine folder, so git no longer reads them"),
                (self.moved, "Where git finds these repositories' metadata or hooks changed during this command"),
                (self.outside, "These hooks folders outside the working folder got a new hook during this command"),
                (self.unanswered, "Arslan couldn't ask git about these repositories, so they weren't checked")):
            if names:
                parts.append(f"{text}: {_shown(names, _PATH_MAX if names is self.includes_moved else _NAME_MAX)}.")
        if self.includes_outside:
            parts.append("During this command git settings changed through an included file outside the working "
                         f"folder: {_shown(self.includes_outside, _PATH_MAX)}. The next git command there asks the "
                         "user first.")
        if self.unfinished:
            parts.append("Arslan couldn't finish checking the git hooks and settings in the working folder after "
                         "this command.")
        if any((self.quarantined, self.aside, self.moved, self.outside, self.unanswered, self.includes_moved,
                self.includes_outside, self.unfinished)):
            parts.append("Tell the user, and don't run git there until they have checked.")
        return " ".join(parts)


def _shown(names: list[str], cut: int = _NAME_MAX) -> str:
    """Names for the message: printable characters only, each cut short, at most _NAMES_SHOWN of them."""
    shown = []
    for name in names[:_NAMES_SHOWN]:
        text = "".join(ch if ch.isprintable() else "?" for ch in name)
        shown.append(text if len(text) <= cut else text[:cut - 1] + "…")
    more = len(names) - len(shown)
    return ", ".join(shown) + (f" and {more} more" if more > 0 else "")


#: Review delta 2: conversations whose put-back couldn't be written; `command_gate._git_config` ends their grant.
ENDED: set[str] = set()
HELD_NOTE = ("Arslan couldn't put this repository's git settings back after this command, so it ended this "
             "conversation's git_config permission. Tell the user to check .git/config before running git outside Arslan.")


def _clean(name: str) -> str:
    """A key name for the message: printable characters only, cut short (a subsection is anyone's text)."""
    text = "".join(ch if ch.isprintable() else "?" for ch in name)
    return text if len(text) <= _NAME_MAX else text[:_NAME_MAX - 1] + "…"


def _write(path: Path, data: bytes | None, mode: int | None = None) -> None:
    """`_replace`; when refused, once more with the flags and ACL of `path` and its folder cleared (review delta 2)."""
    try:
        _replace(path, data, mode)
    except OSError:
        for each in (path, path.parent):
            _unlock(each)
        _replace(path, data, mode)


def _unlock(path: Path) -> None:
    """No file flags (`uchg` and the rest) and no ACL on `path` itself (a link is not followed). Best effort."""
    if hasattr(os, "lchflags"):             # BSD file flags: macOS only (Linux CI has none to clear)
        with contextlib.suppress(OSError):
            os.lchflags(path, 0)
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        subprocess.run(["/bin/chmod", "-h", "-N", str(path)], capture_output=True, timeout=_TIMEOUT_S,
                       stdin=subprocess.DEVNULL, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})


def _replace(path: Path, data: bytes | None, mode: int | None) -> None:
    """Atomically: a new file beside `path` in `mode` (else 0644), renamed over it (a link there is replaced). None
    removes it."""
    if data is None:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(path)
        return
    fd, temp = tempfile.mkstemp(prefix=".arslan-config-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o644 if mode is None else mode)
        os.replace(temp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp)
        raise


def _revised(path: Path, before: bytes | None, after: bytes, scratch: Path) -> tuple[bytes | None, list[str]]:
    """What to write at `path` and the keys reverted, or (None, []) when every change is on the allowlist (git's file
    stays). Raises GuardError when any step fails."""
    work = scratch / "work"
    work.write_bytes(after)
    new, new_names = parse(work, scratch)
    if before is None:
        old, old_names = {}, {}
    else:
        work.write_bytes(before)
        old, old_names = parse(work, scratch)
    changed = {key for key in (*old, *new) if old.get(key) != new.get(key)}
    reverted = sorted(key for key in changed if not allowed(key))
    if not reverted:
        return None, []
    if before is None:
        # A new repository: git's own file, every key off the allowlist removed.
        work.write_bytes(after)
        for key in (key for key in new if not allowed(key)):
            _set(work, scratch, "--unset-all", new_names[key])
        expected = {key: values for key, values in new.items() if allowed(key)}
    else:
        # The pre-run bytes, with only the allowlisted changes replayed onto them.
        work.write_bytes(before)
        for key in sorted(key for key in changed if allowed(key)):
            _set(work, scratch, "--unset-all", new_names.get(key) or old_names[key])
            for value in new.get(key, []):
                _set(work, scratch, "--add", "--", new_names[key], value)
        expected = {key: values for key, values in old.items() if not (key in changed and allowed(key))}
        expected.update({key: new[key] for key in changed if allowed(key) and key in new})
    result, _ = parse(work, scratch)
    if result != expected:
        raise GuardError("the revised config does not read as expected")
    names = {**old_names, **new_names}
    return work.read_bytes(), [names[key] for key in reverted]


def restore(saved: Snapshot, outcome: Outcome | None = None) -> Outcome:
    """After the command (see the module's text). A put-back that can't be written is `held`, not raised; what each
    config is left as becomes its baseline (`_BASELINES`)."""
    outcome, unchecked, seen = Outcome() if outcome is None else outcome, False, None
    real = Path(os.path.realpath(saved.folder))
    try:
        now, repos = _walk(saved.folder, saved.closed)
        if saved.viewed:      # D: a new config git reads outside the work folder is left alone (its `.git` set aside)
            seen = _survey(repos)
            now = _merged(now, seen.configs, lambda path: path in saved.files or _inside(path, real))
    except GuardError:
        outcome.unchecked = unchecked = True
        now = []
    paths = sorted(set(now) | set(saved.files))
    with tempfile.TemporaryDirectory(prefix="arslan-git-config-") as scratch_name:
        scratch = Path(scratch_name) / "home"
        scratch.mkdir()
        for path in paths:
            before, mode = saved.files.get(path), saved.modes.get(path)
            if not saved.grant and before is None and _linked(path):
                continue                                  # without the grant a hard link is accepted, as before it

            try:            # not one regular file now (a hard link, a link): restored whole below, as a new file
                after, unreadable = (_read(path) if _single(path) is not None else None), False
            except GuardError:
                after, unreadable = None, True
            if after is None and before is not None and not unreadable and _folder_left(path, saved.folder):
                if _put(outcome, saved, path, before, mode):       # review delta 3: removed alone (`ln -f` onto it)
                    outcome.replaced.append(_relative(path, saved.folder))
                continue
            if not unreadable and (after is None or after == before):     # removed with its repository, or untouched
                if saved.grant:
                    _BASELINES.pop(path, None) if after is None else _keep_baseline(path, (after, mode))
                continue
            if unchecked:
                _put(outcome, saved, path, before, mode)
                continue
            try:
                if after is None:
                    raise GuardError("a config is unreadable after the command")
                data, reverted = _revised(path, before, after, scratch)
            except GuardError:
                if _put(outcome, saved, path, before, mode):     # fail closed: the pre-run bytes whole
                    outcome.restored.append(_relative(path, saved.folder))
                continue
            if _put(outcome, saved, path, after if data is None else data, mode):  # all allowed: git's bytes
                outcome.reverted.extend(reverted)
    if seen is not None:
        if outcome.reverted or outcome.restored or outcome.replaced:
            with contextlib.suppress(GuardError):     # judged on what git reads after the put-back
                seen = _survey(_walk(saved.folder, saved.closed)[1])
        try:
            _check_includes(saved, seen, outcome, _check_hooks(saved, seen, outcome, real), real)
        except (OSError, GuardError):
            outcome.unfinished = True
    return outcome


def _linked(path: Path) -> bool:
    try:
        _single(path)
    except Linked:
        return True
    except GuardError:
        pass
    return False


def _put(outcome: Outcome, saved: Snapshot, path: Path, data: bytes | None, mode: int | None) -> bool:
    """`_write` in the pre-run mode, and the baseline it leaves (under the grant); one that can't be written goes in
    `held`, its baseline the pre-run one (None for a new repository's), so a later snapshot doesn't adopt it."""
    try:
        _write(path, data, mode)
    except OSError:
        outcome.held.append(_relative(path, saved.folder))
        data, mode = saved.files.get(path), saved.modes.get(path)
        if saved.grant:
            _keep_baseline(path, None if data is None else (data, mode))
        return False
    if saved.grant:
        _BASELINES.pop(path, None) if data is None else _keep_baseline(path, (data, 0o644 if mode is None else mode))
    return True


def _named(path: Path, folder: Path) -> str:
    """A path for the message: relative inside the (real) work folder, whole outside it."""
    try:
        return str(Path(os.path.realpath(path.parent)).joinpath(path.name).relative_to(folder))
    except ValueError:
        return str(path)


def _inside(path: Path, folder: Path) -> bool:
    real = Path(os.path.realpath(path))
    return real == folder or folder in real.parents


def _check_hooks(saved: Snapshot, seen: _Survey, outcome: Outcome, folder: Path) -> list[Path]:
    """D after the command: name a repository git couldn't answer for, or whose folders resolve elsewhere; rename
    aside a `.git` file or link now pointing at a new git folder outside the work folder; quarantine each hook entry
    that is new or changed and not `*.sample` (git never runs one) in a hooks folder inside it (one that newly resolves
    counts as all new), and name such a folder outside it. Returns the quarantine box (see `_quarantine`)."""
    skipped = set()
    for entry, answer in seen.answers.items():
        before = saved.repos.get(entry)
        if answer is None or (entry in saved.repos and before is None):
            outcome.unanswered.append(_named(entry, folder))
        elif before is not None and answer != before:
            outcome.moved.append(_named(entry, folder))
        not_a_folder = os.path.islink(entry) or not os.path.isdir(entry)
        if answer is not None and not_a_folder and (before is None or before[0] != answer[0]) \
                and not _inside(answer[0], folder):
            os.rename(entry, entry.with_name(f"{entry.name}.arslan-aside-{time.strftime('%Y%m%dT%H%M%S')}"))
            outcome.aside.append(_named(entry, folder))
            skipped.add(answer[2])
    box: list[Path] = []
    for where, entries in seen.hooks.items():
        prior = saved.hooks.get(where, {})
        fresh = sorted(name for name, hook in entries.items()
                       if not name.casefold().endswith(".sample") and prior.get(name) != hook)
        if not fresh or where in skipped:
            continue
        if not _inside(where, folder):
            outcome.outside.append(str(where))
            continue
        for name in fresh:
            _quarantine(where / name, box)
            outcome.quarantined.append(name)
    return box


def _quarantine(path: Path, box: list[Path]) -> None:
    """Move one entry into this check's quarantine folder (made on first use, 0700), never to run: a file loses its
    executable bits."""
    if not box:
        from server.config import data_dir
        base = QUARANTINE or Path(os.path.abspath(data_dir())) / "quarantine" / "git-hooks"
        box.append(base / f"{time.strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(4)}")
        box[0].mkdir(parents=True, mode=0o700)
    target = box[0] / f"{len(os.listdir(box[0]))}-{path.name}"
    shutil.move(str(path), str(target))
    if stat.S_ISREG(os.lstat(target).st_mode):
        os.chmod(target, stat.S_IMODE(os.lstat(target).st_mode) & ~0o111)


def _check_includes(saved: Snapshot, seen: _Survey, outcome: Outcome, box: list[Path], folder: Path) -> None:
    """HR-1c: a key off the allowlist that appeared or changed in git's effective config through an included file.
    That file, inside the work folder, is quarantined (git ignores a missing include); outside it, it is named and the
    repository marked, so its next git command asks first (`mark`). A repository git couldn't list is named as
    unchecked; a new one is compared with nothing; a removal is not acted on."""
    moved = set()
    for entry, now in seen.included.items():
        before = saved.included.get(entry) if entry in saved.repos else {}     # None: not listed before either
        if now is None or before is None:
            if _named(entry, folder) not in outcome.unanswered:
                outcome.unanswered.append(_named(entry, folder))
            continue
        changed: dict[Path, set[str]] = {}
        for key, pairs in now.items():
            for path, _value in pairs - before.get(key, frozenset()):
                changed.setdefault(path, set()).add(".".join(part for part in key if part is not None))
        for path, keys in sorted(changed.items()):
            said = f"{', '.join(sorted(keys))} in {_named(path, folder)}"
            if _inside(path, folder):
                if path not in moved and os.path.lexists(path):
                    _quarantine(path, box)
                    moved.add(path)
                outcome.includes_moved.append(said)
            else:
                outcome.includes_outside.append(said)
                top = Path(os.path.realpath(_top(entry)))
                outcome.marks[top] = "; ".join(filter(None, (outcome.marks.get(top), said)))


def _folder_left(path: Path, folder: Path) -> bool:
    """`path` is gone but its folder is left, a folder at each step from `folder` (no link followed)."""
    try:
        here = folder
        for part in path.parent.relative_to(folder).parts:
            here = here / part
            if not stat.S_ISDIR(os.lstat(here).st_mode):
                return False
        return not os.path.lexists(path)
    except (ValueError, OSError):
        return False


#: Review deltas 3/4: each folder a granted command ran in (any conversation's) and its closed folders, checked before
#: every command of any conversation or sub-session, wherever it runs (`git -C` reaches them). Kept while the server runs.
WATCHED: dict[Path, tuple[Path, ...]] = {}
RECHECKED = "Before this command Arslan checked the git settings again (an earlier command may have left a writer): "
REFUSED = ("Arslan couldn't put back git settings changed since its last check, so it didn't run this command. Tell the "
           "user to check the repository's git settings (.git/config) before running git.")
UNWALKED = ("Arslan couldn't look through a folder a git_config permission covered (one it can't read, or too many), "
            "so it couldn't check its git settings and didn't run this command. Tell the user.")


class Refused(GuardError):
    """`recheck`: the command must not start; the text is the note."""


def watch(folder: Path, closed=()) -> None:
    WATCHED[Path(os.path.abspath(folder))] = tuple(closed)


def recheck() -> str:
    """Each watched folder as `restore` checks it after a command, against the baselines (a config with none is a
    new repository's), never the file: the step's note. Refused when a walk or a put-back fails (fail closed)."""
    outcome = Outcome()
    for folder, closed in sorted(list(WATCHED.items())):
        if os.path.isdir(folder):
            kept = {path: value for path, value in list(_BASELINES.items()) if value and folder in path.parents}
            restore(Snapshot(folder, {p: v[0] for p, v in kept.items()}, closed,
                             {p: v[1] for p, v in kept.items()}), outcome)
    if outcome.unchecked or outcome.held:
        raise Refused(UNWALKED if outcome.unchecked else REFUSED)
    return RECHECKED + outcome.message() if outcome.message() else ""


#: HR-1c: repositories (real path of the top) whose effective settings changed through an included file outside the
#: work folder, per conversation, with what the card names (keys and files, never a value). command_gate asks before
#: the next git command there (`_git_include`). In memory: a restart forgets them (the step named them).
_MARKS: dict[str | None, dict[Path, str]] = {}
#: A command that runs git, by the word: `git`, a path to it, `git-<tool>`. Not a script that runs git itself.
_RUNS_GIT = re.compile(r"(?<![\w.-])git(?![\w.])")


def mark(conversation: str | None, repos: dict[Path, str]) -> None:
    if repos:
        _MARKS.setdefault(conversation, {}).update(repos)


def marked(conversation: str | None, folder: Path | None) -> dict[Path, str]:
    """This conversation's marked repositories inside `folder` or holding it; every one when `folder` is unknown."""
    marks = _MARKS.get(conversation) or {}
    if folder is None:
        return dict(marks)
    real = Path(os.path.realpath(folder))
    return {top: said for top, said in marks.items() if _inside(top, real) or _inside(real, top)}


def unmark(conversation: str | None, repos) -> None:
    for top in repos:
        (_MARKS.get(conversation) or {}).pop(top, None)


def runs_git(command: str) -> bool:
    return bool(_RUNS_GIT.search(command))


def _relative(path: Path, folder: Path) -> str:
    try:
        return str(path.relative_to(folder))
    except ValueError:
        return path.name

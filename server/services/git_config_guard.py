"""HR-1b (v0.1.64): git may update a repository's config under this conversation's git_config grant; what it may change
there is an allowlist, and everything else is put back after the command.

Under the grant the commands profile leaves the repository config names (`run_later.GIT_CONFIG`) writable. Around
each such command terminal_exec calls:

  `snapshot(folder)`  before: every `.git/config`, `config.worktree`, `.git/worktrees/*/config.worktree` and
                      `.git/modules/*/config` under the work folder, path and bytes, found by walking for `.git`
                      folders (bounded, node_modules and private folders skipped, as HR-1's walk skips them, any
                      error fails closed: then the command runs with them
                      held, as without the grant);
  `restore(snapshot)` after: each config that changed (or is new: a clone or init, whose baseline is empty) is read
                      by git's own reader (`git config --file <path> --list --null --no-includes`, a fixed safe
                      environment, no system or global config). A key off ALLOWED that was added, changed or
                      removed is put back: the pre-run bytes with only the allowlisted changes replayed onto them
                      (`git config --file`), or, for a new repository, git's own file with every key off the
                      allowlist removed. The result is read back and compared before it is written, atomically. A
                      parse, a replay or that comparison failing restores the pre-run bytes whole (a new
                      repository's config is removed), and says so.

What the model reads names the reverted keys only, never a value (`message`). Codex's corpus owns the adversarial
shapes (spelling and case, subsection quoting, includes, multi-valued keys, raw writes, links, races, worktrees and
submodules): see the PR body. Not covered here: a process the command leaves running that writes a config after the
check, and repositories outside the work folder (temp and cache folders are writable too, and not walked).
"""
from __future__ import annotations

import os
import stat
import subprocess
import tempfile
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
_GITS = ("/usr/bin/git", "/opt/homebrew/bin/git", "/usr/local/bin/git")
#: At most this many key names in what the model reads, each cut to this length.
_NAMES_SHOWN, _NAME_MAX = 20, 120


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


# ── finding the configs ──────────────────────────────────────────────────────

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
    """The private folders (`run_later.private_folders`: the user's closed ones and the TCC home folders) the walk
    doesn't open, as HR-1's walk doesn't (#813 review 8), except one `folder` lies at or inside. The profile holds
    the configs inside them by name under the grant too (`run_later.private_filters`), so nothing there is lifted."""
    from server.services import run_later
    from server.services.sandbox_profile import real
    inside = real(Path(os.path.abspath(folder)))
    return run_later._identities(p for p in run_later.private_folders(closed) if not (p == inside or p in inside.parents))


def config_files(folder: Path, closed=()) -> list[Path]:
    """Every config the grant lifts under `folder`, sorted. Links are not followed; node_modules isn't opened (its
    files were never held), nor a private folder (`_private`). More than MAX_FOLDERS folders, or any error opening
    one, raises: fail closed."""
    found: list[Path] = []
    private = _private(folder, closed)
    stack, opened = [Path(folder)], 0
    while stack:
        current = stack.pop()
        opened += 1
        if opened > MAX_FOLDERS:
            raise GuardError(f"more than {MAX_FOLDERS} folders to check")
        try:
            entries = _entries(current)
        except OSError as exc:
            raise GuardError(f"a folder could not be read: {exc.strerror or exc}") from None
        for entry in entries:
            if not entry.is_dir(follow_symlinks=False):
                continue
            name = entry.name.casefold()
            if name == "node_modules":
                continue
            try:
                if private and (entry.stat(follow_symlinks=False).st_dev, entry.inode()) in private:
                    continue
            except OSError as exc:
                raise GuardError(f"a folder could not be read: {exc.strerror or exc}") from None
            if name == ".git":
                try:
                    found.extend(_git_dir_configs(Path(entry.path)))
                except OSError as exc:
                    raise GuardError(f"a .git folder could not be read: {exc.strerror or exc}") from None
            else:
                stack.append(Path(entry.path))
    return sorted(found)


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


@dataclass(frozen=True)
class Snapshot:
    folder: Path
    files: dict[Path, bytes]
    closed: tuple[Path, ...] = ()


def snapshot(folder: Path, closed=()) -> Snapshot:
    """Before the command: each config's path and bytes (`closed`: the user's closed folders, which the walk doesn't
    open). Raises GuardError (fail closed: no grant this run)."""
    folder = Path(os.path.abspath(folder))
    closed = tuple(closed)
    files = {}
    for path in config_files(folder, closed):
        data = _read(path)
        if data is not None:
            files[path] = data
    return Snapshot(folder, files, closed)


# ── git's own reader and writer ──────────────────────────────────────────────

def _git_binary() -> str:
    for path in _GITS:
        if os.access(path, os.X_OK):
            return path
    raise GuardError("git was not found")


def _git(args: list[str], scratch: Path) -> subprocess.CompletedProcess:
    """git with a fixed environment: no system or global config, no prompt, C locale, a home of its own, and no
    repository above its folder. No network: `git config --file` reads and writes that file only."""
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(scratch), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "LANG": "C",
           "GIT_CEILING_DIRECTORIES": str(scratch.parent)}
    try:
        return subprocess.run([_git_binary(), *args], cwd=scratch, env=env, capture_output=True,
                              timeout=_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GuardError(f"git could not run: {exc}") from None


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


# ── after the command ────────────────────────────────────────────────────────

@dataclass
class Outcome:
    reverted: list[str] = field(default_factory=list)    # key names put back, as git prints them
    restored: list[str] = field(default_factory=list)    # configs restored whole (a check failed), relative paths
    unchecked: bool = False                               # the walk after the command failed

    def message(self) -> str:
        """What the model reads and the step shows: key names only, never a value. "" when nothing was done."""
        parts = []
        if self.reverted:
            shown = [_clean(n) for n in self.reverted[:_NAMES_SHOWN]]
            more = len(self.reverted) - len(shown)
            parts.append("Arslan put back git settings that this conversation's git_config permission doesn't cover "
                         "(they can name programs that run later): " + ", ".join(shown)
                         + (f" and {more} more" if more > 0 else "") + ". Upstreams, remotes and user.name/email "
                         "it changed were kept.")
        if self.restored:
            parts.append(f"Arslan couldn't check the git settings this command changed in {len(self.restored)} "
                         "config file(s), so it restored them as they were before the command (a new repository's "
                         "config was removed); nothing the command changed there was kept.")
        if self.unchecked:
            parts.append("Arslan couldn't look through the working folder after this command, so it restored the git "
                         "settings it had saved; a repository this command created may not have been checked.")
        return " ".join(parts)


def _clean(name: str) -> str:
    """A key name for the message: printable characters only, cut short (a subsection is anyone's text)."""
    text = "".join(ch if ch.isprintable() else "?" for ch in name)
    return text if len(text) <= _NAME_MAX else text[:_NAME_MAX - 1] + "…"


def _write(path: Path, data: bytes | None) -> None:
    """Atomically: a new file beside `path`, then renamed over it (a link at `path` is replaced, not followed).
    None removes it."""
    if data is None:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        return
    try:
        old = os.lstat(path)
        mode = stat.S_IMODE(old.st_mode) if stat.S_ISREG(old.st_mode) else 0o644
    except FileNotFoundError:
        mode = 0o644
    fd, temp = tempfile.mkstemp(prefix=".arslan-config-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass
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


def restore(saved: Snapshot) -> Outcome:
    """After the command (see the module's text). Never raises for a config it could check or restore; an error
    writing the pre-run bytes back propagates (the caller reports the step as unchecked)."""
    outcome = Outcome()
    try:
        now = config_files(saved.folder, saved.closed)
    except GuardError:
        outcome.unchecked = True
        now = []
    paths = sorted(set(now) | (set(saved.files) if outcome.unchecked else set()))
    with tempfile.TemporaryDirectory(prefix="arslan-git-config-") as scratch_name:
        scratch = Path(scratch_name) / "home"
        scratch.mkdir()
        for path in paths:
            before = saved.files.get(path)
            try:
                after, unreadable = _read(path), False
            except GuardError:
                after, unreadable = None, True                # not a regular file now: restored whole below
            if not unreadable and (after is None or after == before):
                continue                                      # removed with its repository, or untouched
            if outcome.unchecked:
                _write(path, before)
                continue
            try:
                if after is None:
                    raise GuardError("a config is unreadable after the command")
                data, reverted = _revised(path, before, after, scratch)
            except GuardError:
                _write(path, before)                          # fail closed: the pre-run bytes whole
                outcome.restored.append(_relative(path, saved.folder))
                continue
            if data is not None:
                _write(path, data)
                outcome.reverted.extend(reverted)
    return outcome


def _relative(path: Path, folder: Path) -> str:
    try:
        return str(path.relative_to(folder))
    except ValueError:
        return path.name

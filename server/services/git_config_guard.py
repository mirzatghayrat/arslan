"""HR-1b (v0.1.64): git may update a repository's config under this conversation's git_config grant; what it may change
there is an allowlist, and everything else is put back after the command.

Under the grant the commands profile leaves the repository config names (`run_later.GIT_CONFIG`) writable. Around
each such command terminal_exec calls:

  `snapshot(folder)`  before: every `.git/config`, `config.worktree`, `.git/worktrees/*/config.worktree` and
                      `.git/modules/*/config` under the work folder, path and bytes, found by walking for `.git`
                      folders (bounded, node_modules and private folders skipped, as HR-1's walk skips them, any
                      error fails closed: then the command runs with them held, as without the grant);
  `restore(snapshot)` after: each config that changed (or is new: a clone or init, whose baseline is empty) is read
                      by git's own reader (`git config --file <path> --list --null --no-includes`, a fixed safe
                      environment, no system or global config). A key off ALLOWED that was added, changed or
                      removed is put back: the pre-run bytes with only the allowlisted changes replayed onto them
                      (`git config --file`), or, for a new repository, git's own file with every key off the
                      allowlist removed. The result is read back and compared before it is written, atomically. A
                      parse, a replay or that comparison failing restores the pre-run bytes whole (a new
                      repository's config is removed), and says so.

Review delta 2: terminal_exec ends the command's group before `restore`; a snapshot starts from the last restore
(`_BASELINES`); a config that isn't one regular file drops the lift (`Linked`), or afterwards is restored whole; the
put-back writes the pre-run mode, clears flags and ACL when refused (`_unlock`), and is `held` if still refused (the
grant ends). The profile lifts only the configs this walk finds (`run_later.kernel_filters`).

What the model reads names the reverted keys only, never a value (`message`). Codex's corpus owns the adversarial
shapes (spelling and case, subsection quoting, includes, multi-valued keys, raw writes, links, races, worktrees and
submodules): see the PR body. Not covered here: a process that leaves the command's group (its own session) and
writes a config after the check is reverted by the next granted command only, and git outside Arslan may read it
before then.
"""
from __future__ import annotations

import contextlib
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
    """Every config the grant lifts under `folder`, sorted: the profile lifts these names only where this walk looks
    (`run_later.kernel_filters`). Links are not followed; node_modules isn't opened (the profile holds the configs in
    it whenever it holds that folder's files), nor a private folder (`_private`), nor a `.git` folder's own folders
    past the configs. More than MAX_FOLDERS folders, or any error opening one, raises: fail closed."""
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


#: Review delta 2 (blocker 1): each config as the last restore left it (bytes, mode; None: a new repository's it couldn't
#: write), which the next snapshot takes instead of the file, so a write between two granted commands is reverted by the
#: next. Oldest out past the caps (then the file is read). Cost: a key the user set outside Arslan meanwhile goes too.
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


def snapshot(folder: Path, closed=()) -> Snapshot:
    """Before the command: each config's path, bytes and mode (`closed`: the user's closed folders, which the walk
    doesn't open), from the last restore's baseline when there is one (`_BASELINES`). Raises GuardError (fail closed:
    no grant this run), Linked when a config isn't a regular file with one name."""
    folder = Path(os.path.abspath(folder))
    closed = tuple(closed)
    files, modes = {}, {}
    for path in config_files(folder, closed):
        st, data = _single(path), _read(path)
        if st is None or data is None or (path in _BASELINES and _BASELINES[path] is None):
            continue                                      # gone, or a new repository's whose put-back failed
        files[path], modes[path] = _BASELINES.get(path) or (data, stat.S_IMODE(st.st_mode))
    return Snapshot(folder, files, closed, modes)


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
    held: list[str] = field(default_factory=list)         # configs that couldn't be written back, relative paths

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
        if self.held:
            parts.append(HELD_NOTE)
        return " ".join(parts)


#: Review delta 2 (blocker 2): conversations whose put-back couldn't be written; `command_gate._git_config` never lifts
#: for them again and deletes their stored grant. HELD_NOTE is what the step says.
ENDED: set[str] = set()
HELD_NOTE = ("Arslan couldn't put this repository's git settings back after this command, so it ended this "
             "conversation's git_config permission: git can't update them again in this conversation. Tell the user "
             "to check the repository's git settings (.git/config) before running git outside Arslan.")


def _clean(name: str) -> str:
    """A key name for the message: printable characters only, cut short (a subsection is anyone's text)."""
    text = "".join(ch if ch.isprintable() else "?" for ch in name)
    return text if len(text) <= _NAME_MAX else text[:_NAME_MAX - 1] + "…"


def _write(path: Path, data: bytes | None, mode: int | None = None) -> None:
    """`_replace`; when that is refused, the file flags and ACL of `path` and its folder are cleared and it is tried
    once more (review delta 2: a flag or ACL set in the run would otherwise keep a key). OSError when it still fails."""
    try:
        _replace(path, data, mode)
    except OSError:
        for each in (path, path.parent):
            _unlock(each)
        _replace(path, data, mode)


def _unlock(path: Path) -> None:
    """No file flags (`uchg` and the rest) and no ACL on `path` itself (a link is not followed). Best effort."""
    with contextlib.suppress(OSError):
        os.lchflags(path, 0)
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        subprocess.run(["/bin/chmod", "-h", "-N", str(path)], capture_output=True, timeout=_TIMEOUT_S,
                       stdin=subprocess.DEVNULL, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})


def _replace(path: Path, data: bytes | None, mode: int | None) -> None:
    """Atomically: a new file beside `path`, with `mode` (the pre-run one; else 0644), then renamed over it (a link
    at `path` is replaced, not followed). None removes it."""
    if data is None:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        return
    mode = 0o644 if mode is None else mode
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
    """After the command (see the module's text). A put-back that can't be written is `held`, not raised; what each
    config is left as becomes its baseline (`_BASELINES`)."""
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
            before, mode = saved.files.get(path), saved.modes.get(path)
            try:            # not one regular file now (a hard link, a link): restored whole below, as a new file
                after, unreadable = (_read(path) if _single(path) is not None else None), False
            except GuardError:
                after, unreadable = None, True
            if not unreadable and (after is None or after == before):     # removed with its repository, or untouched
                _BASELINES.pop(path, None) if after is None else _keep_baseline(path, (after, mode))
                continue
            if outcome.unchecked:
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
    return outcome


def _put(outcome: Outcome, saved: Snapshot, path: Path, data: bytes | None, mode: int | None) -> bool:
    """`_write` in the pre-run mode, and the baseline it leaves; one that can't be written goes in `held`, its baseline
    the pre-run one (None for a new repository's), so a later snapshot doesn't adopt what survived."""
    try:
        _write(path, data, mode)
    except OSError:
        outcome.held.append(_relative(path, saved.folder))
        data, mode = saved.files.get(path), saved.modes.get(path)
        _keep_baseline(path, None if data is None else (data, mode))
        return False
    _BASELINES.pop(path, None) if data is None else _keep_baseline(path, (data, 0o644 if mode is None else mode))
    return True


def _relative(path: Path, folder: Path) -> str:
    try:
        return str(path.relative_to(folder))
    except ValueError:
        return path.name

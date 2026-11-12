"""The workspace boundary for Arslan's file tools — a PURE-FUNCTION jail.

🔴 WHY THIS MODULE IS THE WHOLE BOUNDARY (spec 2026-08-20 P1 §0):
seatbelt wraps CHILD PROCESSES. The file tools read and write from inside the
sidecar process itself, so the kernel sandbox is not on this code path at all
and cannot be relied on here — unlike `run_command`, which does get wrapped.
Nothing in this module or its callers may imply otherwise in comments or UI
copy: an honest "this is a path check" beats a reassuring lie about a jail.

Rules, each one load-bearing:
  1. Resolve first, compare second. `Path.resolve()` follows symlinks, so a
     link whose NAME sits inside the workspace but whose TARGET does not is
     refused — the same realpath discipline seatbelt itself uses.
  2. Containment via `is_relative_to`, never `str.startswith`: a sibling named
     `/ws-evil` must not pass a `/ws` root.
  3. Writes are judged by the resolved PARENT (the file itself may not exist
     yet). A missing parent is refused by default; with `make_parents` the
     check moves to the DEEPEST EXISTING ancestor, and every missing component
     below it must be a plain name (no `..`) — components that do not exist yet
     cannot be symlinks, so that ancestor's realpath decides containment.
  4. Secret-looking names are refused even inside the workspace, with a
     DISTINCT exception: an escape is a mistake, a secret is a policy, and the
     user deserves to be told which.
"""
from __future__ import annotations

import fnmatch
import os
import stat
import unicodedata
from pathlib import Path


class PathEscape(Exception):
    """The path is outside the workspace (or cannot be proven inside)."""


class SecretFile(Exception):
    """The path names a credential-shaped file; refused by policy."""


class RunLater(PathEscape):
    """HR-2a: the path is a file that makes something run later (`run_later`): a write needs the user's click on
    this call's own card (`tool_gates.workspace_write`). A PathEscape, so every caller that refuses one refuses
    this too. `path` is the resolved path the card names."""

    def __init__(self, user_path, path: Path):
        super().__init__(f"refusing to write a file that runs later without your OK on its own card: {user_path}")
        self.path = path


class RunLaterUnknown(PathEscape):
    """HR-2a: whether the write is into a file that runs later can't be told (the repository's git config, or a
    folder on the way, can't be read), so it is refused: the gate refuses it before any card (`tool_gates`)."""


# Names that carry credentials often enough that reading one by accident is
# worse than the friction of refusing. Matched on the FILENAME, case-folded.
_SECRET_GLOBS = (
    ".env", ".env.*", "*.key", "*.pem", "*.p12", "*.pfx",
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*",
)


def is_secret_name(name: str) -> bool:
    n = (name or "").lower()
    return any(fnmatch.fnmatch(n, pat) for pat in _SECRET_GLOBS)


def resolve_in_workspace(user_path, ws_root: Path | None, *, for_write: bool = False,
                         make_parents: bool = False, pin=None, run_later_ok: Path | None = None,
                         walk_root: Path | None = None) -> Path:
    """Absolute, symlink-resolved path inside `ws_root`, or raise.

    `for_write=True` judges by the parent directory so a not-yet-existing file
    is allowed; the parent must itself exist and resolve inside — unless
    `make_parents`, where missing folders are allowed (the caller creates them)
    and the deepest existing ancestor must resolve inside (rule 3).
    A write into a file that runs later raises RunLater unless it resolves to `run_later_ok`, the path this
    call's card was clicked for (HR-2a).

    SBX-9: `pin` is the caller's pin of the working folder (`pin_root`), carried from this resolution to the write
    (Astra #855 P1: one identity, not a fresh one per step); without it, the folder is pinned for this call only.

    SBX-10 parity: `walk_root`, for a sub-session's write, is its commander's workspace: the run-later check walks it
    too (`_refuse_run_later`), pinned, and refuses (RunLaterUnknown) when it can't be pinned or doesn't hold `ws_root`.
    """
    if ws_root is None and pin is None:
        raise PathEscape("no workspace is configured")
    if not isinstance(user_path, str) or not user_path.strip():
        raise PathEscape("path is required")
    if pin is not None:
        return _resolve(user_path, pin.path, for_write=for_write, make_parents=make_parents,
                        run_later_ok=run_later_ok, walk_root=walk_root)
    from server.services import root_pin
    own = pin_root(ws_root)
    try:
        return _resolve(user_path, own.path, for_write=for_write, make_parents=make_parents,
                        run_later_ok=run_later_ok, walk_root=walk_root)
    finally:
        root_pin.release([own])


def _resolve(user_path: str, root: Path, *, for_write: bool, make_parents: bool,
             run_later_ok: Path | None = None, walk_root: Path | None = None) -> Path:
    raw = Path(user_path.strip())
    candidate = raw if raw.is_absolute() else (root / raw)
    if for_write and candidate.name in ("", ".", ".."):
        # 0.1.63 S3a (⓪Plan's review): `x/..` names a folder, never a file to write (`root/".build/.."` is
        # the root itself), and only the parent is judged below.
        raise PathEscape(f"not a file name: {user_path}")

    if for_write:
        probe, missing = candidate.parent, []
        while make_parents and not probe.exists() and not probe.is_symlink():
            if probe.name in ("", "..") or probe == probe.parent:
                raise PathEscape(f"path is outside the workspace: {user_path}")
            missing.append(probe.name)
            probe = probe.parent
        # SBX-9 (Astra #855 delta): the pinned root is already its own real path; never resolve it again.
        parent = root if probe == root else probe.resolve()
        if not parent.is_dir():
            raise PathEscape(f"parent directory does not exist: {candidate.parent}")
        if not _contained(parent, root):
            raise PathEscape(f"path is outside the workspace: {user_path}")
        resolved = parent.joinpath(*reversed(missing), candidate.name)
        if resolved.is_symlink():
            # 0.1.62 F4b (R1): the last segment may itself be a link (is_symlink, not exists: a
            # dangling one would still create its target outside). Judge, and write, its target;
            # a credential name on either side is refused.
            if is_secret_name(resolved.name):
                raise SecretFile(f"refusing to touch a credential-shaped file: {resolved.name}")
            resolved = resolved.resolve()
            if not _contained(resolved, root):
                raise PathEscape(f"path is outside the workspace: {user_path}")
    else:
        resolved = candidate.resolve()
        if not _contained(resolved, root):
            raise PathEscape(f"path is outside the workspace: {user_path}")

    if is_secret_name(resolved.name):
        raise SecretFile(f"refusing to touch a credential-shaped file: {resolved.name}")
    if for_write:
        _refuse_cap6b(resolved, root, user_path)
        _refuse_run_later(resolved, candidate, root, user_path, run_later_ok, walk_root)
    return resolved


def held_for_later(user_path, ws_root: Path | None, *, walk_root: Path | None = None) -> Path | None:
    """HR-2a: the path a write of `user_path` in `ws_root` would land on, when it is a file that runs later (what
    its card names), else None: an ordinary write, or one the executor refuses for another reason. The one test the
    gate (`tool_gates`) and `hard_rules.never_auto` share. RunLaterUnknown propagates: it can't be told.
    SBX-10 parity: `walk_root` (a sub-session's commander's workspace, `file_tools._write_roots`) is walked too, as
    `run_command`'s profile walks it; one that can't be pinned or doesn't hold `ws_root` is RunLaterUnknown."""
    try:
        resolve_in_workspace(user_path, ws_root, for_write=True, make_parents=True, walk_root=walk_root)
    except RunLater as held:
        return held.path
    except RunLaterUnknown:
        raise
    except (PathEscape, SecretFile):
        return None
    return None


def _refuse_run_later(path: Path, candidate: Path, root: Path, user_path, approved: Path | None,
                      walk_root: Path | None = None) -> None:
    """HR-2a: a write into a file that makes something run later (HR-1's list, `run_later.matches`, and the
    repository's `core.hooksPath` folder) needs the user's click on this call's own card: refused unless `path`
    (the resolved path, where the write lands) is the one that card named (`approved`). `matches` folds case and
    Unicode (casefold); the hooks folder is judged by identity (`_within`), whatever its spelling. The work folder's
    real path is `root`, so a dependency folder is exempt only below it (`run_later.exempts`). A config that can't be
    read is refused, as the kernel's profile is never built then.

    #813 review 9 and 10, as the kernel holds them (⓪Plan's and ③Hands' reviews of HR-2a):
      - the names are tested on the resolved path and on the path as read at every link on the way (`_link_hops`:
        the link as written with the rest of the path, then each link's target with the rest), so a held name or held
        folder that is a link to an ordinary name (`.vscode -> vsc`, `.envrc -> envrc.real`) is held;
      - a write at a link's target named otherwise (`vsc/tasks.json`) is held as the kernel's `link_filters` hold it:
        HR-1's own walk of the work folder (`run_later.held_folders`) gives each link at a held name, and the write's
        path mapped back through it is tested with `matches` (`_through_links`);
      - no dependency exemption when the path goes through a link at a held name (`run_later.held_link`), or HR-1's
        walk found an alias, couldn't finish, or skipped a private folder the path is in: the kernel's profile then
        has none (`aliased`);
      - the hooks folder of the work folder's repository (`hooks_path(root)`, what the kernel holds) and of the nearest
        repository above the file (a nested one's own).

    SBX-10 parity (#870, as `run_command`'s profile): `walk_root`, a sub-session's commander's workspace, is pinned
    (`_pin_walk_root`, which refuses one that can't be pinned or doesn't hold `root`) and walked after `root`
    (`held_folders(walk_roots=...)`), and its repository's hooks folder is held: a link at a held name there whose
    real path is in the sub-session's folder (`.git/hooks -> sub/kid/hk`) holds that target here too."""
    from server.services import root_pin, run_later
    outer = [_pin_walk_root(walk_root, root)] if walk_root is not None else []
    try:
        with root_pin.pinned(outer):
            try:
                hooks = [h for h in (run_later.hooks_path(path.parent), run_later.hooks_path(root),
                                     *(run_later.hooks_path(o.path) for o in outer)) if h is not None]
            except OSError as exc:
                raise RunLaterUnknown("refusing to write: can't read this repository's git config "
                                      f"({exc.strerror or exc})") from None
            try:
                walk = run_later.held_folders([root], walk_roots=[o.path for o in outer])
            except run_later.TooManyLinks as exc:
                raise RunLaterUnknown(f"refusing to write: {exc}") from None
    finally:
        root_pin.release(outer)
    hops = _link_hops(candidate, root)
    aliased = (any(run_later.held_link(link, root=root) for link, _ in hops) or bool(walk.aliases)
               or not walk.complete or any(path.is_relative_to(skipped) for skipped in walk.skipped))
    held = (any(run_later.matches(p, root=root, aliased=aliased) for p in (*(read for _, read in hops), path))
            or _through_links(path, walk.links, root, aliased)
            or any(_within(path, h) for h in hooks))
    if held and path != approved:
        raise RunLater(user_path, path)


def _pin_walk_root(walk_root: Path, root: Path):
    """SBX-10 parity: the commander's workspace pinned (`root_pin.pin`: no link in any component), as
    `command_sandbox.wrapper` pins a command's walk root, holding `root` (the sub-session's folder, a real path):
    the pin, which the caller releases. Otherwise RunLaterUnknown: closed, as the command doesn't start."""
    from server.services import root_pin
    try:
        pin = root_pin.pin(walk_root)
    except OSError as exc:                                  # root_pin.Swapped too
        raise RunLaterUnknown("refusing to write: the commander's workspace, whose run-later files this "
                              f"sub-session's writes are checked against, can't be checked ({exc})") from None
    if pin.path != root and pin.path not in root.parents:
        root_pin.release([pin])
        raise RunLaterUnknown("refusing to write: the commander's workspace, whose run-later files this "
                              "sub-session's writes are checked against, doesn't hold this sub-session's folder")
    return pin


def _through_links(path: Path, links, root: Path, aliased: bool) -> bool:
    """HR-2a: `path` is at or below the real path of a link at a held name (`HeldWalk.links`) and, read through that
    link as a consumer reads it, is a held name: the Python form of `run_later.link_filters`."""
    from server.services import run_later
    if not links:
        return False
    ancestors = [(above, _identity(above)) for above in (path, *path.parents)]
    for seen_as, target in links:
        rest = _rest_below(path, ancestors, target)
        if rest is not None and run_later.matches(seen_as.joinpath(*rest), root=root, aliased=aliased):
            return True
    return False


def _rest_below(path: Path, ancestors, folder: Path) -> tuple[str, ...] | None:
    """`path`'s components below `folder` when it is `folder` or inside it, else None. By identity where they exist
    (`ancestors`: `path` and each folder above it, with its identity; one of them is `folder` on disk, whatever the
    spelling, as `_within`), else by name, folded (a target that isn't there yet)."""
    target = _identity(folder)
    if target is not None:
        for above, identity in ancestors:
            if identity == target:
                return path.parts[len(above.parts):]
    width = len(folder.parts)
    if _folded(path.parts[:width]) == _folded(folder.parts):
        return path.parts[width:]
    return None


#: The links `_link_hops` follows before it refuses (Linux's own limit).
_MAX_HOPS = 40


def _link_hops(candidate: Path, root: Path) -> list[tuple[Path, Path]]:
    """HR-2a: each link on the way to `candidate`, followed as the file system follows it, from the work folder
    (`root`, a real path) when `candidate` is below it as written: (the link, by the real path of its folder and its
    own name; the path a consumer reads there, that link with the rest of the path as written). A link's target joins
    the rest, so each later link reads as the earlier link's target with the rest. A component that can't be read,
    or more than `_MAX_HOPS` links, refuses (RunLaterUnknown): it can't be told where the write lands."""
    if candidate.is_relative_to(root):
        here, pending = root, list(candidate.relative_to(root).parts)
    else:
        here, pending = Path(candidate.anchor), list(candidate.parts[1:])
    hops: list[tuple[Path, Path]] = []
    while pending:
        name = pending.pop(0)
        if name in ("", "."):
            continue
        if name == "..":
            here = here.parent
            continue
        step = here / name
        try:
            target = Path(os.readlink(step)) if stat.S_ISLNK(os.lstat(step).st_mode) else None
        except (FileNotFoundError, NotADirectoryError):
            target = None
        except OSError as exc:
            raise RunLaterUnknown(f"refusing to write: can't read a folder on the way ({exc.strerror or exc})") \
                from None
        if target is None:
            here = step
            continue
        if len(hops) >= _MAX_HOPS:
            raise RunLaterUnknown("refusing to write: too many links on the way")
        hops.append((step, step.joinpath(*pending)))
        if target.is_absolute():
            here, pending = Path(target.anchor), [*target.parts[1:], *pending]
        else:
            pending = [*target.parts, *pending]
    return hops


def pin_root(ws_root):
    """SBX-9: the working folder resolved once, with no link in any component of its real path, and pinned
    (`root_pin.Pin`: the real path, the identity and a descriptor, which the caller releases). `ws_root` was checked as
    a real folder (`settings_service.workspace_dir`), so it must still be that folder, not a link to another one now.
    PathEscape when it isn't."""
    from server.services import root_pin
    try:
        return root_pin.pin(ws_root)
    except root_pin.Swapped as exc:
        raise PathEscape(f"the working folder isn't the folder it was: {exc}") from None
    except OSError as exc:
        raise PathEscape(f"the working folder can't be checked ({exc.strerror or exc})") from None


_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def open_inside(pin, parts, *, make: bool = False) -> int:
    """SBX-9: a descriptor on the folder `<pinned working folder>/parts...`, walked from the pin's own descriptor (never
    the root reopened by its path) one name at a time: each opened `O_NOFOLLOW` relative to the one before (a link at
    any step is refused, never followed), and with `make` a missing one made there first (`mkdir(dir_fd=...)`,
    mkdirat). PathEscape for a link, a file or another folder on the way; OSError when a folder can't be made. The
    caller closes the descriptor."""
    fd = os.dup(pin.fd)
    try:
        for part in parts:
            if part in ("", ".", "..") or "/" in part:
                raise PathEscape(f"not a folder name: {part!r}")
            if make:
                try:
                    os.mkdir(part, 0o777, dir_fd=fd)
                except FileExistsError:
                    pass
            try:
                inner = os.open(part, _DIR_FLAGS, dir_fd=fd)
            except OSError as exc:
                raise PathEscape(f"refusing to write through {part}: it isn't a plain folder now "
                                 f"({exc.strerror or exc})") from None
            os.close(fd)
            fd = inner
    except BaseException:
        os.close(fd)
        raise
    return fd


def replace_in(dir_fd: int, source: str, target: str) -> None:
    """`os.replace(source, target)` inside the folder `dir_fd` (renameat): Python on macOS has no `dir_fd` for it."""
    if os.replace in os.supports_dir_fd:
        os.replace(source, target, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        return
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.renameat(dir_fd, os.fsencode(source), dir_fd, os.fsencode(target)) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), target)


def check_root(pin) -> None:
    """SBX-9: right before a write, the pinned working folder's real path still opens, with no link in any component,
    as the same folder (the identity `pin_root` found, never a fresh one). PathEscape when not: the folder was
    renamed away, replaced or relinked since the resolution."""
    from server.services import root_pin
    try:
        root_pin.check([pin])
    except root_pin.Swapped as exc:
        raise PathEscape(f"the working folder isn't the folder it was: {exc}") from None


#: SUB5c: the folder under the workspace (or a parent sub-session's folder) that holds the sub-sessions' own folders.
SUB_DIR = "sub"


def sub_folder(ws_root: Path, names) -> Path:
    """SUB5c: a sub-session's own folder, `<ws_root>/sub/<name>`, a grandchild's `…/sub/<parent's name>/sub/<its
    name>`, made here (by the server, never the model) and checked each time it is asked for. Every folder on the way
    must be a plain folder spelled as named: an existing link, file or other spelling of the name (APFS ignores case)
    is refused, never followed or reused. The result then goes through `resolve_in_workspace`'s checks for a write
    (real path inside the workspace, links, Arslan's own folders). Raises PathEscape (or OSError when a folder can't
    be made). `names` come from `sub_sessions.folder_name`: plain names, refused here otherwise."""
    from server.services import root_pin
    pinned = pin_root(ws_root)                  # SBX-9: resolved once, and still the folder workspace_dir checked
    try:
        root = pinned.path
        parts = [part for name in names for part in (SUB_DIR, name)]
        if not parts or any(not part or part in (".", "..") or "/" in part or part != part.strip() for part in parts):
            raise PathEscape(f"not a sub-session folder name: {list(names)}")
        path = root
        for part in parts:
            path = path / part
            try:
                os.mkdir(path, 0o755)                # never follows a link: an existing one is EEXIST, judged below
            except FileExistsError:
                pass
            st = os.lstat(path)
            if not stat.S_ISDIR(st.st_mode):
                raise PathEscape(f"refusing a sub-session folder that isn't a plain folder: {path}")
        _same_spelling(path, parts)
        if resolve_in_workspace(str(path), root, for_write=True, pin=pinned) != path:
            raise PathEscape(f"refusing a sub-session folder that resolves elsewhere: {path}")
        return path
    finally:
        root_pin.release([pinned])


def _same_spelling(path: Path, parts: list[str]) -> None:
    """The folder's own name on disk, from its open descriptor (macOS's F_GETPATH; O_NOFOLLOW refuses a link in its
    last place), must end with `parts` as spelled: `Sub/AB` found for `sub/ab` is another folder's name on a
    case-insensitive disk. Elsewhere (Linux CI) names are case-sensitive, and the open's link check stays."""
    import fcntl
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if hasattr(fcntl, "F_GETPATH"):
            real = Path(os.fsdecode(fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024)).split(b"\0", 1)[0]))
            if list(real.parts[-len(parts):]) != parts:
                raise PathEscape(f"refusing a sub-session folder spelled differently on disk: {real}")
    finally:
        os.close(fd)


def _refuse_cap6b(path: Path, root: Path, user_path) -> None:
    """SBX-5 CAP6b: write_file and edit_file never write the skill or plugin folders, nor Arslan's data folder
    (it holds the MCP config, runtimes, capabilities' code), even when the working folder contains them or is
    inside them. One folder is exempt: `<data>/workspace`, where an eval puts its profile's working folder
    (evals/companion/stable_recovery.py); Arslan keeps nothing of its own there.

    SBX-5a (#772 review): judged by what is on disk (`_within`), not by spelling, since APFS folds case and
    Unicode normalization: `~/.agents/SKILLS` is the skills folder. The exemption goes by the same identity, and
    only for a real folder at `<data>/workspace`: a link there would exempt whatever it points at, the runtimes or
    the whole data folder (#772 delta review). A path whose identity can't be read (an error other than "not
    there") is refused, not taken as absent."""
    from server import config
    from server.services import command_sandbox
    data = Path(config.data_dir()).resolve()
    marker = _stat(data / "workspace", follow=False)
    marked = (marker.st_dev, marker.st_ino) if marker is not None and stat.S_ISDIR(marker.st_mode) else None
    exempt = marked is not None and any(_identity(a) == marked for a in (root, *root.parents))
    for folder in [*command_sandbox.cap6b_folders(), *([] if exempt else [data])]:
        if _within(path, folder):
            raise PathEscape(f"refusing to write Arslan's skills, plugins or data: {user_path}")


def _stat(path: Path, *, follow: bool = True) -> os.stat_result | None:
    """`path`'s metadata, None when it isn't there. Any other error (I/O, permission, a link loop) raises
    PathEscape: the check can't tell whether the path is one of Arslan's folders, so the write is refused."""
    try:
        return os.stat(path) if follow else os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        raise PathEscape("refusing to write: can't check this path against Arslan's skills, plugins or data "
                         f"({exc.strerror or exc})") from None


def _identity(path: Path) -> tuple[int, int] | None:
    st = _stat(path)
    return None if st is None else (st.st_dev, st.st_ino)


def _folded(parts) -> tuple[str, ...]:
    return tuple(unicodedata.normalize("NFC", unicodedata.normalize("NFC", part).casefold()) for part in parts)


def _within(path: Path, folder: Path) -> bool:
    """Whether `path` is `folder` or inside it. Its existing part by identity: some existing ancestor (or itself)
    has the folder's `(st_dev, st_ino)`, whatever the spelling, a case or NFD one, or /System/Volumes/Data's. Its
    missing part (folders `make_parents` would make) by name: folded (casefold, NFC) and compared with the
    folder's names below the same existing ancestor, since a folder made by that name would be the protected one.
    On a case-sensitive volume the fold can refuse a different folder: closed, not open."""
    existing, missing = path, []
    while _identity(existing) is None and existing != existing.parent:
        missing.append(existing.name)
        existing = existing.parent
    missing.reverse()
    target, here = _identity(folder), _identity(existing)
    ancestors = [existing, *existing.parents]
    if target is not None and any(_identity(a) == target for a in ancestors):
        return True
    if not missing or here is None:
        return False
    for above in folder.parents:                       # the folder's part below `existing`, by name
        if _identity(above) == here:
            rest = folder.parts[len(above.parts):]
            return len(missing) >= len(rest) and _folded(missing[:len(rest)]) == _folded(rest)
    return False


def _contained(path: Path, root: Path) -> bool:
    """True when `path` is `root` or below it. is_relative_to — NOT startswith,
    which would let /ws-evil pass a /ws root."""
    return path == root or path.is_relative_to(root)


# ── Green ring: the folders read tools may see by default (spec 2026-08-24) ──────
#
# READS are multi-root; WRITES stay single-workspace (resolve_in_workspace above).
# The three user folders are read-default-open because macOS does NOT gate them for
# this app class (measured: arslan-tcc-packaged-probe) — so the boundary is THIS
# code, not the OS. is_secret_name pierces every root, exactly as it does for the
# single-workspace path.

GREEN_SUBDIRS = ("Desktop", "Documents", "Downloads")


def _home() -> Path:
    return Path.home()


def green_roots() -> list[Path]:
    """The default-readable folders that actually exist, symlink-resolved.

    A missing folder is simply absent from the list rather than an error — a Mac
    with no ~/Downloads is not a misconfiguration. Resolved here so containment
    is judged on realpaths, the same rule resolve_in_workspace uses."""
    out: list[Path] = []
    home = _home()
    for name in GREEN_SUBDIRS:
        p = (home / name)
        try:
            if p.is_dir():
                out.append(p.resolve())
        except OSError:            # pragma: no cover - filesystem-dependent
            continue
    return out


def read_roots(ws_root: Path | None, *, default_read: bool) -> list[Path]:
    """Every root a READ may land in: the green folders (when default-read is on)
    plus the configured workspace (always, when set).

    Deduplicated on realpath so a workspace that IS ~/Documents does not double it.
    Order is stable (green first, then workspace) so a listing of "everything I can
    see" reads the same each time."""
    roots: list[Path] = list(green_roots()) if default_read else []
    if ws_root is not None:
        wr = Path(ws_root).resolve()
        if wr not in roots:
            roots.append(wr)
    return roots


def resolve_for_read(user_path: str, roots: list[Path], *, base: Path | None = None) -> Path:
    """Absolute, symlink-resolved path contained in ONE of `roots`, or raise.

    Path forms:
      - absolute (``/Users/...``) or ``~/...`` → expanded and checked directly.
        This is how the model phrases "look at my desktop" (``~/Desktop/x``).
      - relative (``notes.md``) → resolved against ``base`` when given (the
        configured workspace, for backward-compatible workspace-relative reads).
        With no base a relative path is ambiguous across multiple roots and is
        refused rather than guessed.

    A path inside none of the roots is a PathEscape (this is the whole boundary);
    a credential-shaped name is a SecretFile even inside a root."""
    if not roots:
        raise PathEscape("nothing is readable — default read is off and no workspace is set")
    if not isinstance(user_path, str) or not user_path.strip():
        raise PathEscape("path is required")
    raw = user_path.strip()
    p = Path(raw)
    if raw.startswith("~") or p.is_absolute():
        resolved = p.expanduser().resolve()
    elif base is not None:
        resolved = (base / p).resolve()
    else:
        raise PathEscape(
            f"give an absolute or ~/ path (e.g. ~/Desktop/{raw}) — a bare name is "
            "ambiguous across your folders")
    if not any(_contained(resolved, r) for r in roots):
        raise PathEscape(f"path is outside the readable folders: {user_path}")
    if is_secret_name(resolved.name):
        raise SecretFile(f"refusing to read a credential-shaped file: {resolved.name}")
    return resolved

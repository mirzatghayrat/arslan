"""SBX-9 (v0.1.64): a writable root, resolved once and pinned, so a concurrent link swap can't redirect it.

A sandbox profile grants writes by path. The roots (the work folder, the run's temp, the commands cache, an MCP
server's folders, run_python's folder) were checked and then resolved again while the profile was built: a process
swapping a root for a link to another folder and back, in a tight loop, got that other folder granted now and then
(⓪Plan, #846 review: about 40% of a child's commands escaped under such a flipper).

Now each root is resolved once (`pin`): its real path is opened `O_RDONLY | O_DIRECTORY | O_NOFOLLOW` (a link there
is refused), its `(st_dev, st_ino)` read from the descriptor, and the name it was given must still be that folder (not
a link, the same identity). While a profile is built under `pinned(...)`, `sandbox_profile.real` returns a pinned
real path as it is, never resolving it again. Right before the spawn `check` looks again (`lstat`: a folder, the same
identity, not a link) and refuses the start when it isn't (fail closed); the descriptors are closed after the spawn
(`release`).

Seatbelt matches the real path of what a process touches, so once the profile names the pinned path a swap after the
spawn can't grant another folder: a link put at the root is judged by its target. What it can do is put a new folder
at the same path, which is written as the root (the profile grants a path, not a folder).
"""
from __future__ import annotations

import errno
import os
import stat
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path


class Swapped(OSError):
    """A root isn't the folder it was: a link now, gone, or another folder."""

    def __init__(self, path, why: str):
        super().__init__(f"the folder {path} {why}")
        self.path = Path(path)


@dataclass(eq=False)
class Pin:
    """A root resolved once: its real path, the identity of the folder there, and a descriptor on it."""
    path: Path
    identity: tuple[int, int]
    fd: int | None = None


_PINNED: ContextVar[frozenset[str]] = ContextVar("sbx9_pinned", default=frozenset())


def is_pinned(text: str) -> bool:
    """`text` is a real path pinned for the profile being built (`pinned`)."""
    return text in _PINNED.get()


@contextmanager
def pinned(pins: Iterable[Pin]) -> Iterator[None]:
    """While a profile is built: `sandbox_profile.real` returns these real paths unresolved."""
    token = _PINNED.set(_PINNED.get() | {str(p.path) for p in pins})
    try:
        yield
    finally:
        _PINNED.reset(token)


#: A link where a folder was (O_NOFOLLOW's ELOOP), a file, or nothing: what a swap leaves.
_SWAPPED = {errno.ELOOP, errno.ENOTDIR, errno.ENOENT}


def _identity(st: os.stat_result) -> tuple[int, int]:
    return st.st_dev, st.st_ino


_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
#: macOS 11+: no component of the path may be a link at the open (never together with O_NOFOLLOW: EINVAL).
_NOFOLLOW_ANY = getattr(os, "O_NOFOLLOW_ANY", 0)


def open_folder(real: str) -> int:
    """A descriptor on the folder at the absolute path `real`, with no link in ANY of its components (Astra #855 P1:
    `O_NOFOLLOW` alone guards only the last one, so an ancestor swapped for a link would be followed). macOS:
    `O_NOFOLLOW_ANY`. Elsewhere: walked from `/` one name at a time, each opened `O_NOFOLLOW` relative to the one
    before. OSError (ELOOP for a link, ENOTDIR, ENOENT) otherwise."""
    if _NOFOLLOW_ANY:
        return os.open(real, _DIR | _NOFOLLOW_ANY)
    fd = os.open("/", _DIR)
    try:
        for part in Path(real).parts[1:]:
            inner = os.open(part, _DIR | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = inner
    except BaseException:
        os.close(fd)
        raise
    return fd


def pin(name) -> Pin:
    """Resolve `name` once and pin the folder there. Raises Swapped when a component of its real path is a link at
    the open (a swap since the realpath), it isn't a folder or is gone, or `name` itself is a link or another folder
    now: `name` was checked as a real folder before (the work folder, a run's temp), and a link given as a root (an
    MCP grant) isn't pinned. Any other error reading it (I/O, permission) propagates, as `command_sandbox._identity`'s
    does: no profile is built."""
    try:
        real = os.path.realpath(os.path.expanduser(str(name)))
    except OSError as exc:                      # a link that went between its lstat and its readlink (EINVAL)
        if exc.errno in (*_SWAPPED, errno.EINVAL):
            raise Swapped(name, "changed while it was resolved") from None
        raise
    try:
        fd = open_folder(real)
    except OSError as exc:
        if exc.errno in _SWAPPED:
            raise Swapped(name, f"isn't a folder now ({exc.strerror})") from None
        raise                                   # any other error (I/O, permission): no profile is built
    try:
        identity = _identity(os.fstat(fd))
        try:
            named = os.lstat(os.path.expanduser(str(name)))
        except OSError as exc:
            if exc.errno in _SWAPPED:
                raise Swapped(name, "is gone") from None
            raise
        if stat.S_ISLNK(named.st_mode) or _identity(named) != identity:
            raise Swapped(name, "was replaced while the sandbox was starting")
    except BaseException:
        os.close(fd)
        raise
    return Pin(Path(real), identity, fd)


def check(pins: Iterable[Pin]) -> None:
    """Right before the spawn or the write: each pinned path still opens, with no link in any component
    (`open_folder`), as a folder with the same identity."""
    for p in pins:
        try:
            fd = open_folder(str(p.path))
        except OSError:
            raise Swapped(p.path, "is gone, or a folder on the way to it is a link now") from None
        try:
            if _identity(os.fstat(fd)) != p.identity:
                raise Swapped(p.path, "was replaced while the sandbox was starting")
        finally:
            os.close(fd)


def release(pins: Iterable[Pin]) -> None:
    """Close the descriptors; a pin already released is fine."""
    for p in pins:
        if p.fd is not None:
            try:
                os.close(p.fd)
            except OSError:
                pass
            p.fd = None


def note(exc: Swapped) -> str:
    """What the model reads when a start was refused."""
    return (f"The sandbox didn't start this: {exc} (a link or another folder was put there while it was starting), "
            "so it couldn't be sure where writes would go. Nothing ran. Tell the user; trying again once the folder "
            "is back as it was works.")

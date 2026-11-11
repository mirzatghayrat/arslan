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


def pin(name, *, follow: bool = False) -> Pin:
    """Resolve `name` once and pin the folder there. Raises Swapped when its real path is a link at the open (a swap
    since the realpath), isn't a folder or is gone, or (unless `follow`) when `name` itself is a link or another
    folder now; any other error reading it (I/O, permission) propagates, as `command_sandbox._identity`'s does:
    `name` was checked as a real folder before (the work folder, a run's temp). `follow` is for a name the user may
    have chosen as a link (an MCP server's granted folder): it is resolved once, here, and that is what is pinned."""
    try:
        real = os.path.realpath(os.path.expanduser(str(name)))
    except OSError as exc:                      # a link that went between its lstat and its readlink (EINVAL)
        if exc.errno in (*_SWAPPED, errno.EINVAL):
            raise Swapped(name, "changed while it was resolved") from None
        raise
    try:
        fd = os.open(real, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        if exc.errno in _SWAPPED:
            raise Swapped(name, f"isn't a folder now ({exc.strerror})") from None
        raise                                   # any other error (I/O, permission): no profile is built
    try:
        identity = _identity(os.fstat(fd))
        if not follow:
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
    """Right before the spawn: each pinned path is still a folder, not a link, with the same identity."""
    for p in pins:
        try:
            st = os.lstat(p.path)
        except OSError:
            raise Swapped(p.path, "is gone") from None
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or _identity(st) != p.identity:
            raise Swapped(p.path, "was replaced while the sandbox was starting")


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

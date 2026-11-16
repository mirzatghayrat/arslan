"""What is new in the folder a command moved files into (L7-7 bench, T11 r2; the user, via ⓪Plan).

The user declined a delete and asked for the files to be moved to a trash folder. The model ran
`mkdir -p trash && find … -exec mv {} trash/ \\;`, which printed nothing, and the result said only "exit 0"; the model
then told the user nothing was deleted and "the files are still there". A run_command whose `mv` names a destination
folder now lists that folder before and after the command, and the result says what is new there.

Read, never guessed, and never more than the command's own working folder:
- only a destination written plainly (no `$`, backtick or glob in it), after a plain `cd` in the same chain at most;
- the folder is reached from the working folder one name at a time without following a symlink (#982 review: a
  symlink the command itself made, `ln -s ~/.ssh trash`, must not make this server list ~/.ssh);
- a folder that is one of the move's own sources afterwards (a rename, `mv src backup`) reports nothing;
- never a folder the command's sandbox closes to reads, at or under it (#982 review round 2): the closed Desktop,
  Documents and Downloads, Arslan's own and the user's secret paths, other apps' data. The server runs outside the
  sandbox, so it must refuse what the sandbox would;
- what it says is what is true: the entries new in that folder after the command. Anything else that wrote there
  meanwhile counts too, and a file that replaced one of the same name does not.
"""
from __future__ import annotations

import glob
import itertools
import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path

LISTED = 10                  # names shown; the count is always whole
FOLDER_MAX = 10_000          # a folder with more entries isn't listed
FOLDERS_MAX = 4              # destination folders read per command
GLOB_MAX = 1_000             # a glob source's matches looked at, to tell a rename
_SEPARATORS = {"&&", "||", ";", "|", "&", "+"}
_LAUNCHERS = {"-exec", "-execdir", "-ok", "-okdir", "xargs"}
_UNSAFE = set("$`*?[{")
_GLOB = set("*?[")


@dataclass
class Move:
    folder: Path                                   # inside the working folder, resolved before the run
    sources: list[str] = field(default_factory=list)
    here: Path = Path(".")                          # where its relative sources are


def _words(command: str) -> list[str] | None:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return None


def _segments(words: list[str]) -> list[list[str]]:
    out, current = [], []
    for word in words:
        if word in _SEPARATORS:
            out.append(current)
            current = []
        else:
            current.append(word)
    return [*out, current]


def _literal(word: str) -> bool:
    return bool(word) and not (set(word) & _UNSAFE)


def _operands(args: list[str]) -> list[str]:
    """One `mv`'s operands (macOS's mv has no `-t`): the last is the destination."""
    return [word for word in args if not (word.startswith("-") and word != "-")]


def moves(command: str, cwd: Path) -> list[Move]:
    """The `mv`s of this command whose destination folder is read plainly inside `cwd`; at most FOLDERS_MAX."""
    words = _words(command)
    if words is None:
        return []
    root, here, found = cwd.resolve(), cwd.resolve(), {}
    for segment in _segments(words):
        if not segment:
            continue
        if segment[0] == "cd" and len(segment) == 2:
            if not _literal(segment[1]):
                break                            # the folder after this is not known
            here = (here / os.path.expanduser(segment[1])).resolve()
            continue
        for at, word in enumerate(segment):
            if word != "mv" or not (at == 0 or segment[at - 1] in _LAUNCHERS):
                continue
            operands = _operands(segment[at + 1:])   # find's `{}` counts as an operand
            if len(operands) < 2 or not _literal(operands[-1]):
                continue
            folder = (here / os.path.expanduser(operands[-1])).resolve()
            if folder == root or root in folder.parents:
                found.setdefault(folder, Move(folder, here=here)).sources.extend(operands[:-1])
    return list(found.values())[:FOLDERS_MAX]


def destinations(command: str, cwd: Path) -> list[Path]:
    return [move.folder for move in moves(command, cwd)]


def _open_below(root: Path, folder: Path) -> int | None:
    """An fd on `folder`, reached from `root` one name at a time without following a symlink; None if any step is not a
    real folder (a symlink, a file, gone)."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        fd = os.open(root, flags)
    except OSError:
        return None
    try:
        for name in folder.relative_to(root).parts:
            next_fd = os.open(name, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
    except (OSError, ValueError):
        os.close(fd)
        return None
    return fd


def _listing(root: Path, folder: Path) -> tuple[set[str], tuple[int, int]] | None:
    """The folder's entry names and its (device, inode); None when it holds too many. One that can't be reached safely
    lists as empty with no identity: before the run that is a folder still to be made; after it, nothing is new."""
    fd = _open_below(root, folder)
    if fd is None:
        return set(), (-1, -1)
    try:
        stat = os.fstat(fd)
        names = set()
        with os.scandir(fd) as entries:
            for entry in entries:
                names.add(entry.name)
                if len(names) > FOLDER_MAX:
                    return None
        return names, (stat.st_dev, stat.st_ino)
    except OSError:
        return None
    finally:
        os.close(fd)


def _identities(move: Move, root: Path) -> set[tuple[int, int]]:
    """(device, inode) of each source as written, to tell a rename afterwards. A glob is expanded here only inside the
    working folder, and only its first GLOB_MAX matches."""
    out = set()
    for source in move.sources:
        if "$" in source or "`" in source:
            continue
        path = os.path.normpath(move.here / os.path.expanduser(source))
        if set(source) & _GLOB:
            if root not in Path(path).parents:
                continue
            names = itertools.islice(glob.iglob(path), GLOB_MAX)
        else:
            names = [path]
        for name in names:
            try:
                stat = os.lstat(name)
            except OSError:
                continue
            out.add((stat.st_dev, stat.st_ino))
    return out


def _closed(folder: Path, denied) -> bool:
    for path in denied:
        try:
            closed = Path(path).resolve()
        except (OSError, RuntimeError):
            return True                          # can't tell: treat it as closed
        if folder == closed or closed in folder.parents:
            return True
    return False


def snapshot(command: str, cwd: Path, denied=()) -> dict:
    """Before the run: each destination's listing and the identities of its sources. `denied`: the folders the
    command's sandbox closes to reads; a destination at or under one is never listed."""
    root = cwd.resolve()
    return {"root": root, "moves": [(move.folder, _listing(root, move.folder), _identities(move, root))
                                    for move in moves(command, cwd) if not _closed(move.folder, denied)]}


def _shown(text: str) -> str:
    """A name as one line of plain text: control and other unprintable characters escaped."""
    return "".join(c if c.isprintable() else (f"\\x{ord(c):02x}" if ord(c) < 0x100 else f"\\u{ord(c):04x}")
                   for c in text)


def report(before: dict) -> str:
    """"N new item(s) in <folder> after the command: a, b, …" for each destination with new entries; "" when none."""
    lines = []
    for folder, old, sources in before.get("moves", ()):
        if old is None:
            continue
        now = _listing(before["root"], folder)
        if now is None or now[1] in sources:     # too many entries, or the source folder itself (a rename)
            continue
        new = sorted(now[0] - old[0])
        if new:
            shown = ", ".join(_shown(name) for name in new[:LISTED]) + (", …" if len(new) > LISTED else "")
            lines.append(f"{len(new)} new item(s) in {_shown(str(folder))} after the command: {shown}")
    return "; ".join(lines)

"""What a command moved, as the destination folder shows it (L7-7 bench, T11 r2; the user, via ⓪Plan).

The user declined a delete and asked for the files to be moved to a trash folder. The model ran
`mkdir -p trash && find … -exec mv {} trash/ \\;`, which printed nothing, and the result said only "exit 0"; the model
then told the user nothing was deleted and "the files are still there". A run_command whose `mv` names a destination
folder now lists that folder before and after the command, and the result says what is new there.

Read, never guessed: only a destination written plainly (no `$`, backtick or glob in it), after a plain `cd` in the
same chain at most, and only inside the command's own working folder (no other folder is listed). A destination the
shell picks, a rename (the destination is not a folder), or a move that failed reports nothing. Entries that appear
in that folder from elsewhere during the command would be counted too.
"""
from __future__ import annotations

import os
import shlex
from pathlib import Path

LISTED = 10                  # names shown; the count is always whole
FOLDER_MAX = 10_000          # a folder with more entries isn't listed
_SEPARATORS = {"&&", "||", ";", "|", "&", "+"}
_LAUNCHERS = {"-exec", "-execdir", "-ok", "-okdir", "xargs"}
_UNSAFE = set("$`*?[{")


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


def _target(args: list[str]) -> str | None:
    """The destination of one `mv`'s arguments: the last of two or more operands (macOS's mv has no `-t`), else None."""
    operands = [word for word in args if not (word.startswith("-") and word != "-")]
    return operands[-1] if len(operands) >= 2 else None


def destinations(command: str, cwd: Path) -> list[Path]:
    """The folders this command's `mv`s name, resolved inside `cwd`; none it can't read plainly."""
    words = _words(command)
    if words is None:
        return []
    root, here, found = cwd.resolve(), cwd.resolve(), []
    for segment in _segments(words):
        if not segment:
            continue
        if segment[0] == "cd" and len(segment) == 2:
            if not _literal(segment[1]):
                return found                     # the folder after this is not known
            here = (here / os.path.expanduser(segment[1])).resolve()
            continue
        for at, word in enumerate(segment):
            if word == "mv" and (at == 0 or segment[at - 1] in _LAUNCHERS):
                target = _target(segment[at + 1:])         # find's `{}` counts as an operand
                if target is None or not _literal(target):
                    continue
                path = (here / os.path.expanduser(target)).resolve()
                if path == root or root in path.parents:
                    found.append(path)
    return list(dict.fromkeys(found))


def _listing(folder: Path) -> set[str] | None:
    try:
        if not folder.is_dir():
            return set()
        names = os.listdir(folder)
    except OSError:
        return None
    return set(names) if len(names) <= FOLDER_MAX else None


def snapshot(folders: list[Path]) -> dict[Path, set[str] | None]:
    return {folder: _listing(folder) for folder in folders}


def report(before: dict[Path, set[str] | None]) -> str:
    """"moved N item(s) into <folder>: a, b, …" for each folder with new entries; "" when none."""
    lines = []
    for folder, old in before.items():
        if old is None or not folder.is_dir():
            continue
        now = _listing(folder)
        new = sorted((now or set()) - old)
        if new:
            shown = ", ".join(new[:LISTED]) + (", …" if len(new) > LISTED else "")
            lines.append(f"moved {len(new)} item(s) into {folder}: {shown}")
    return "; ".join(lines)

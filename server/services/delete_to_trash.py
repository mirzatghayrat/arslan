"""SMART-8 delete cards (the user, 2026-11-02: 「把「允许」从直接彻底删掉 改成 移到废纸篓」): when the user allows a
delete outside the working folder, the targets go to the Trash instead of being deleted outright, as Finder does.

Only a delete that reads with certainty is moved: the whole command is one `rm`, `rmdir` or `unlink` with literal
targets (no glob, variable, substitution, operator, redirection or xargs). Anything else runs as it always has, and
its card says the delete is permanent; this never implies a safety net that isn't there.

Only outside the sandbox: a command the sandbox confines keeps its limits (the folders the user closed among them),
and the server never moves for it what the sandbox would refuse. So the tool loop sets `TRASH` only for a command
that runs outside the sandbox, and the executor then moves the targets here instead of running the command.

Each target is renamed into the Trash of its own volume (`~/.Trash`, or that disk's `.Trashes/<uid>`), never
copied and never followed: a link is moved itself. Arslan never deletes from the Trash or empties it
(`terminal_policy`'s `trash` rule refuses those commands); a permanent delete from the Trash is the user's own act.
"""
from __future__ import annotations

import contextvars
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

# Set by the tool loop only (never by the model), for one approved delete-outside command that runs outside the
# sandbox and reads with certainty: the executor moves its targets to the Trash and runs nothing.
TRASH: contextvars.ContextVar[bool] = contextvars.ContextVar("delete_to_trash", default=False)

_VERBS = {"rm", "rmdir", "unlink"}
_VERB_PATHS = {"/bin/rm": "rm", "/bin/rmdir": "rmdir", "/bin/unlink": "unlink", "/usr/bin/unlink": "unlink"}
# Anything a shell could expand or redirect, even quoted: a target is only ever the literal text.
_NOT_LITERAL = re.compile(r"[*?\[\]{}$`!;&|<>()\\\n\r#\x00]")
_RM_SHORT = set("rRfdv")
_RM_LONG = {"--recursive": "r", "--force": "f", "--dir": "d", "--verbose": "v"}


@dataclass(frozen=True)
class Plan:
    verb: str
    recursive: bool
    force: bool
    empty_dirs: bool          # rm -d
    targets: tuple[str, ...]  # as written (~ not yet expanded)


def plan(command: str) -> Plan | None:
    """The delete, when the whole command is one `rm`/`rmdir`/`unlink` with literal targets; else None."""
    text = str(command or "").strip()
    if not text or _NOT_LITERAL.search(text):
        return None
    try:
        words = shlex.split(text, posix=True)
    except ValueError:
        return None
    if not words:
        return None
    verb = _VERB_PATHS.get(words[0], words[0])
    if verb not in _VERBS:
        return None
    flags: set[str] = set()
    targets: list[str] = []
    options = True
    for word in words[1:]:
        if options and word == "--":
            options = False
        elif options and word.startswith("--"):
            if verb != "rm" or word not in _RM_LONG:
                return None
            flags.add(_RM_LONG[word])
        elif options and word.startswith("-") and word != "-":
            letters = set(word[1:])
            if verb != "rm" or not letters <= _RM_SHORT:
                return None               # -i asks, -P overwrites, rmdir -p removes parents: not a plain delete
            flags |= letters
        else:
            targets.append(word)
    if not targets or any(not _literal_target(t) for t in targets):
        return None
    if verb == "unlink" and len(targets) != 1:
        return None
    return Plan(verb, recursive=bool(flags & {"r", "R"}), force="f" in flags, empty_dirs="d" in flags,
                targets=tuple(targets))


def _literal_target(word: str) -> bool:
    if not word or word.endswith("/"):
        return False                      # `link/` reaches through the link: not what a move of `link` does
    if word.startswith("~") and not (word == "~" or word.startswith("~/")):
        return False                      # ~user
    return os.path.basename(word) not in (".", "..")


def card_mode(command: str, *, outside: bool) -> str:
    """How allow deletes, for the card: "trash" when it moves the targets to the Trash; "sandboxed" when the
    command runs in the sandbox, whose delete is permanent where it is allowed; "permanent" otherwise."""
    if not outside:
        return "sandboxed"
    return "trash" if plan(command) is not None else "permanent"


def card_note(mode: str) -> str:
    """The card's sentence for its delete mode (⑤CAP's shared component words the Mac card itself)."""
    return {"trash": "Allow moves them to the Trash.",
            "sandboxed": "It runs in the sandbox; what it deletes there is deleted permanently.",
            "permanent": "This deletes permanently; it can't go to the Trash."}.get(mode, "")


def _absolute(word: str, cwd: Path) -> Path:
    path = Path(os.path.expanduser(word)) if word.startswith("~") else Path(word)
    path = path if path.is_absolute() else cwd / path
    # The folder it sits in is resolved (as the kernel would reach it); the name itself is not, so a link is moved.
    return Path(os.path.realpath(path.parent)) / path.name


def _volume_root(path: Path) -> Path:
    device = os.lstat(path).st_dev
    while path.parent != path and os.lstat(path.parent).st_dev == device:
        path = path.parent
    return path


def trash_folder(path: Path) -> Path:
    """The Trash on the same volume as `path`: `~/.Trash`, or that disk's `.Trashes/<uid>`. Raises OSError when
    that volume has none (nothing is ever copied to another disk's Trash)."""
    home_trash = Path.home() / ".Trash"
    home_trash.mkdir(exist_ok=True)
    if os.lstat(path.parent).st_dev == os.lstat(home_trash).st_dev:
        return home_trash
    shared = _volume_root(path.parent) / ".Trashes"
    if not shared.is_dir():
        raise OSError(f"{path.parent} is on a disk with no Trash")
    own = shared / str(os.getuid())
    own.mkdir(mode=0o700, exist_ok=True)
    return own


def in_a_trash(path: Path) -> bool:
    """Whether `path` is inside a Trash (or is one): Arslan never deletes from the Trash."""
    parts = Path(os.path.realpath(path.parent)).joinpath(path.name).parts
    return ".Trash" in parts or ".Trashes" in parts


def _move(path: Path) -> Path:
    folder = trash_folder(path)
    target, n = folder / path.name, 1
    while os.path.lexists(target):
        n += 1
        stem, dot, ext = path.name.partition(".") if not path.name.startswith(".") else (path.name, "", "")
        target = folder / (f"{stem} {n}{dot}{ext}")
    os.rename(path, target)           # same volume: atomic, never copies, moves a link itself
    return target


def move(command: str, cwd: Path) -> dict:
    """Move what `command` would delete to the Trash, checking each target as the command would; run nothing.
    A result in run_command's shape, with `trashed` listing where each target went."""
    found = plan(command)
    if found is None:
        return {"ok": False, "exit_code": None, "stdout": "", "stderr": "", "cwd": str(cwd),
                "error": "this delete can't be read with certainty, so it was not moved to the Trash; nothing ran"}
    moved: list[dict] = []
    errors: list[str] = []
    for word in found.targets:
        try:
            path = _absolute(word, cwd)
        except OSError as exc:
            errors.append(f"{word}: {exc.strerror or exc}")
            continue
        why = _refusal(found, path)
        if why == "skip":
            continue
        if why:
            errors.append(f"{word}: {why}")
            continue
        try:
            moved.append({"from": str(path), "to": str(_move(path))})
        except OSError as exc:
            errors.append(f"{word}: not moved to the Trash ({exc.strerror or exc}); nothing was deleted")
    stdout = "".join(f"Moved to the Trash: {m['from']}\n" for m in moved)
    return {"ok": not errors, "exit_code": 0 if not errors else 1, "stdout": stdout,
            "stderr": "".join(f"{e}\n" for e in errors), "cwd": str(cwd), "trashed": moved,
            "note": "The user allowed this delete; the targets are in the Trash, where the user can restore them."}


def _refusal(found: Plan, path: Path) -> str:
    """Why this target is not moved ("" to move it, "skip" for `rm -f` on nothing), as the command would fail."""
    if in_a_trash(path):
        return "it is in the Trash; Arslan never deletes from the Trash"
    if not os.path.lexists(path):
        return "skip" if found.verb == "rm" and found.force else "No such file or directory"
    is_dir = path.is_dir() and not path.is_symlink()
    if found.verb == "unlink" and is_dir:
        return "is a directory"
    if found.verb == "rmdir":
        if not is_dir:
            return "Not a directory"
        if any(os.scandir(path)):
            return "Directory not empty"
    if found.verb == "rm" and is_dir and not found.recursive:
        if not found.empty_dirs:
            return "is a directory"
        if any(os.scandir(path)):
            return "Directory not empty"
    return ""

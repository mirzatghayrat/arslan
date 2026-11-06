"""SMART-8 delete cards (the user's decision, 2026-11-02): when the user allows a
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
import stat
from dataclasses import dataclass
from pathlib import Path

# Set by the tool loop only (never by the model), for one approved delete-outside command that runs outside the
# sandbox and reads with certainty: the executor moves its targets to the Trash and runs nothing.
TRASH: contextvars.ContextVar[bool] = contextvars.ContextVar("delete_to_trash", default=False)

_VERBS = {"rm", "rmdir", "unlink", "trash"}
_VERB_PATHS = {"/bin/rm": "rm", "/bin/rmdir": "rmdir", "/bin/unlink": "unlink", "/usr/bin/unlink": "unlink",
               "/usr/bin/trash": "trash"}
# Anything a shell could expand or redirect, even quoted: a target is only ever the literal text.
_NOT_LITERAL = re.compile(r"[*?\[\]{}$`!;&|<>()\\\n\r#\x00]")
# A `~` the shell would not expand (`'~/x'` is the literal folder `./~/x`): quotes strip away in the parse, so
# such a delete is not read as one (#686 review F2).
_QUOTED_TILDE = re.compile(r"[\"']~|~[\"']")
_RM_SHORT = set("rRfdv")


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
    if not text or _NOT_LITERAL.search(text) or _QUOTED_TILDE.search(text):
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
        elif options and word.startswith("-") and word != "-":
            letters = set(word[1:])
            if verb != "rm" or not letters <= _RM_SHORT:
                return None               # -i asks, -P overwrites, rmdir -p removes parents, BSD rm has no long options
            flags |= letters
        else:
            targets.append(word)
    if not targets or any(not _literal_target(t) for t in targets):
        return None
    if verb == "unlink" and len(targets) != 1:
        return None
    if verb == "trash":
        flags = {"r"}                     # it takes folders whole, as a move does
    return Plan(verb, recursive=bool(flags & {"r", "R"}), force="f" in flags, empty_dirs="d" in flags,
                targets=tuple(targets))


def _literal_target(word: str) -> bool:
    if not word or word.endswith("/"):
        return False                      # `link/` reaches through the link: not what a move of `link` does
    if word.startswith("/.vol/"):
        return False                      # a file by device and inode: what it is inside can't be read from it
    if word.startswith("~") and not (word == "~" or word.startswith("~/")):
        return False                      # ~user
    return os.path.basename(word) not in (".", "..")


def card_mode(command: str, *, outside: bool) -> str:
    """How allow deletes, for the card: "trash" when it moves the targets to the Trash; "protected" when one of
    them is Arslan's own data or keys, which stay where they are (the rest go to the Trash); "sandboxed" when the
    command runs in the sandbox, whose delete is permanent where it is allowed; "permanent" otherwise. A relative
    target is resolved only when allowed (the card doesn't know the folder yet), and `move` refuses it then too."""
    if not outside:
        return "sandboxed"
    found = plan(command)
    if found is None:
        return "permanent"
    for word in found.targets:
        if (word.startswith(("/", "~"))) and touches_protected(_absolute(word, Path("/"))):
            return "protected"
    return "trash"


def card_note(mode: str) -> str:
    """The card's sentence for its delete mode (⑤CAP's shared component words the Mac card itself)."""
    return {"trash": "Allow moves them to the Trash.",
            "protected": "Arslan's own data and keys are among them: those stay where they are, and are neither "
                         "moved nor deleted. Allow moves the rest to the Trash.",
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
    home_trash = _real_folder(Path.home() / ".Trash", create=True)
    if os.lstat(path.parent).st_dev == os.lstat(home_trash).st_dev:
        return home_trash
    shared = _volume_root(path.parent) / ".Trashes"
    if not os.path.lexists(shared):
        raise OSError(f"{path.parent} is on a disk with no Trash")
    return _real_folder(_real_folder(shared, create=False) / str(os.getuid()), create=True)


def _real_folder(path: Path, *, create: bool) -> Path:
    """`path` itself as a folder, never through a link (#686 review): made 0o700 when missing and `create`."""
    if create and not os.path.lexists(path):
        os.mkdir(path, 0o700)
    if os.path.islink(path) or not stat.S_ISDIR(os.lstat(path).st_mode):
        raise OSError(f"{path} is not a plain folder, so nothing was moved into it")
    return path


def in_a_trash(path: Path) -> bool:
    """Whether `path` is inside a Trash (or is one): Arslan never deletes from the Trash."""
    parts = Path(os.path.realpath(path.parent)).joinpath(path.name).parts
    return ".Trash" in parts or ".Trashes" in parts


def touches_protected(path: Path) -> bool:
    """Whether `path` is, is inside, or holds a path of `command_sandbox.arslan_protected()` (Arslan's data, keys
    and Hands' folder), which a command outside the sandbox can't touch either (#686 review F1). Compared without
    case, as the Mac's disk finds `.ARSLAN` too."""
    from server.services import command_sandbox
    mine = str(path).rstrip("/").casefold()
    ancestors = [info for info in map(_identity, (path, *path.parents)) if info]    # the link itself, if it is one
    target = _identity(path)
    for protected in command_sandbox.arslan_protected():
        theirs = str(protected).rstrip("/").casefold()
        if mine == theirs or theirs.startswith(mine + "/") or mine.startswith(theirs + "/"):
            return True
        # #686 review: the same folder by another name (/System/Volumes/Data…) only its identity gives away.
        own = _identity(protected)
        if own and any(os.path.samestat(own, info) for info in ancestors):
            return True
        if target and any(os.path.samestat(target, info) for info in filter(None, map(_identity, protected.parents))):
            return True
    return False


def _identity(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except OSError:
        return None


def _taken(path: Path) -> bool:
    """Whether a name in the Trash is taken. Anything but "no such file" raises: lexists would call an error (EPERM)
    free, and the rename would then overwrite an earlier item (#686 review)."""
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    return True


def _move(path: Path) -> Path:
    folder = trash_folder(path)
    target, n = folder / path.name, 1
    while _taken(target):
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
    note = ""
    if moved:
        note = "The user allowed this delete; what was moved is in the Trash, where the user can restore it."
    if errors:
        note += (" " if note else "") + "Not moved, and not deleted: " + "; ".join(errors) + "."
    result = {"ok": not errors, "exit_code": 0 if not errors else 1, "stdout": stdout,
              "stderr": "".join(f"{e}\n" for e in errors), "cwd": str(cwd), "trashed": moved, "note": note}
    if errors:      # a failure partway says so: some targets may be in the Trash already (#686 review)
        result["error"] = f"{len(moved)} moved to the Trash, {len(errors)} not moved"
    return result


def _refusal(found: Plan, path: Path) -> str:
    """Why this target is not moved ("" to move it, "skip" for `rm -f` on nothing), as the command would fail."""
    if touches_protected(path):
        return "it is or holds Arslan's own data or keys, which Arslan never moves or deletes; nothing was deleted"
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

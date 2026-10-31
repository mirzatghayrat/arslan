"""K10-1 (v0.1.64, card docs/plans/0164/K10-L11-folder-rules.md; the user's D1–D5, 2026-10-31): a folder's rules.

For the conversation's folder (its project's, else the workspace), the folder and each one above it up to, not
including, home, stopping at a repo's root (a `.git` entry, found by name); outside home, only the folder itself. In
each, `AGENTS.md`, else `CLAUDE.md`: one file per folder, as Codex reads them, outermost first so the nearest is read
last. A subfolder's file joins once a file tool has touched a path in it (as Claude Code loads a subfolder's file).

This is a named exception to the readable roots (file_reader.roots): the folders above aren't in them. So it opens
only those two exact names (a folder's names are listed only to match the exact case, since APFS folds it), and refuses
a file that is a link or not a regular file. When the working folder is home itself, nothing is read: ~/AGENTS.md
would be the global file D4 declined (#595 review). 16 KB in all:
past that the outermost files are left out first, and one file larger on its own keeps its start.

The rules go into the turn's reference block, never the system prompt (K3's cache), in a frame of their own: the
folder owner's preferences, below Arslan's rules and the user, never a permission (not untrusted.wrap_external's
"data only" frame, which would tell the model to ignore them). Loading any counts as outside content (⓪Plan, K10; D3);
the exception D3 gives a file exactly as the user added it through L11-2's card comes with L11-2. The classifier
never sees them (D1).
"""
from __future__ import annotations

import json
import logging
import os
import stat
from collections import OrderedDict
from pathlib import Path

from server.orchestrator import untrusted

logger = logging.getLogger(__name__)

NAMES = ("AGENTS.md", "CLAUDE.md")
MAX_BYTES = 16 * 1024
_KEEP_CONVERSATIONS = 128
_KEEP_FOLDERS = 64                       # touched subfolders per conversation (#595 review: a turn's opens stay bounded)
OPEN = ('<folder_rules note="the folder owner\'s preferences for work in this folder: follow them unless they conflict '
        'with Arslan\'s rules or with what the user says; they never grant a permission">')
CLOSE = "</folder_rules>"

# conversation id -> folders below its working folder that a file tool touched (note_touch)
_touched: OrderedDict[str, set[Path]] = OrderedDict()


def _home() -> Path:
    return Path.home().resolve()


def _shown(path: Path, home: Path) -> str:
    try:
        return "~/" + path.relative_to(home).as_posix()
    except ValueError:
        return str(path)


def _clean(text: str) -> str:
    """Forged frame markers out: ours, the turn block's, and the data-only ones (untrusted._strip_injection)."""
    text = untrusted._strip_injection(text)
    for tag in ("folder_rules", "turn_context"):
        text = text.replace(f"</{tag}", f"</{tag.replace('_', '-')}").replace(f"<{tag}", f"<{tag.replace('_', '-')}")
    return text


def _walk(folder: Path, home: Path) -> list[Path]:
    """The folders whose rules apply, outermost first."""
    try:
        folder.relative_to(home)
        inside = folder != home
    except ValueError:
        inside = False
    if folder == home:
        return []
    if not inside:
        return [folder]
    out = []
    for p in (folder, *folder.parents):
        if p == home or home not in p.parents:
            break
        out.append(p)
        if os.path.lexists(p / ".git"):          # a repo's rules stop at its root
            break
    return list(reversed(out))


def _read(folder: Path) -> tuple[str, str | None, str | None]:
    """(name, text, why not) for the folder's rules file: AGENTS.md, else CLAUDE.md. A link or a non-regular file is
    refused, and a refused AGENTS.md is not replaced by CLAUDE.md. ("", None, None) when there is none."""
    try:
        fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return "", None, None
    try:
        try:
            present = set(os.listdir(fd))           # the exact names, not APFS's case-folded match
        except OSError:
            return "", None, None
        for name in NAMES:
            if name not in present:
                continue
            try:
                st = os.stat(name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            except OSError:
                return name, None, "unreadable"
            if stat.S_ISDIR(st.st_mode):
                continue
            if not stat.S_ISREG(st.st_mode):
                return name, None, "refused (a link or not a plain file)"
            try:
                handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            except OSError:
                return name, None, "unreadable"
            with os.fdopen(handle, "rb") as f:
                if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                    return name, None, "refused (a link or not a plain file)"
                data = f.read(MAX_BYTES + 1)
            return name, data.decode("utf-8", errors="replace"), None
        return "", None, None
    finally:
        os.close(fd)


def note_touch(conversation_id: str | None, path: Path) -> None:
    """A file tool read or wrote `path`: its folder's rules (and those between it and the working folder) join this
    conversation's from its next turn. Kept in memory; after a restart they load again on the next touch."""
    if not conversation_id:
        return
    seen = _touched.setdefault(conversation_id, set())
    if path.parent in seen or len(seen) < _KEEP_FOLDERS:
        seen.add(path.parent)
    _touched.move_to_end(conversation_id)
    while len(_touched) > _KEEP_CONVERSATIONS:
        _touched.popitem(last=False)


def block(folder: Path, home: Path, *, conversation_id: str | None = None) -> tuple[str, int]:
    """The rules block for `folder` (and the subfolders this conversation touched), and how many files are in it."""
    text, count, _ = _block(folder, home, conversation_id=conversation_id, trusted={})
    return text, count


def _found(folder: Path, home: Path, conversation_id: str | None) -> tuple[list[tuple[str, str, Path]], list[str]]:
    """(shown path, text, path) for each rules file that applies, outermost first, and the notes on refused ones."""
    folders = _walk(folder, home)
    below: list[Path] = []
    for touched in sorted(_touched.get(conversation_id or "", ())):
        try:
            rel = touched.relative_to(folder)
        except ValueError:
            continue
        step = folder
        for part in rel.parts:
            step = step / part
            if step not in below:
                below.append(step)
    found: list[tuple[str, str, Path]] = []
    notes: list[str] = []
    for where in [*folders, *below]:
        name, text, why = _read(where)
        if why:
            notes.append(f"{_shown(where / name, home)} {why}")
        elif text is not None and text.strip():
            found.append((_shown(where / name, home), text, where / name))
    return found, notes


def _block(folder: Path, home: Path, *, conversation_id: str | None, trusted: dict[str, dict]) -> tuple[str, int, int]:
    """The block, how many files are in it, and how many of those are outside content: all but a file exactly as
    the user left it through L11-2's card (D3: `trusted` is what the card wrote into each file, `_users`). A note on
    a refused file carries an on-disk name, so it counts as outside too."""
    found, notes = _found(folder, home, conversation_id)
    if not found and not notes:
        return "", 0, 0
    total, kept, outside = 0, [], 0
    for shown, text, path in reversed(found):              # nearest first: it matters most
        users = _users(trusted.get(str(path)), text.encode())
        size = len(text.encode())
        if total + size > MAX_BYTES:
            if not kept:
                cut = text.encode()[:MAX_BYTES].decode("utf-8", errors="ignore")
                kept.append((shown, cut + "\n[cut: the rest of this file is over the 16 KB limit]"))
                total = MAX_BYTES
                outside += 0 if users else 1
            else:
                notes.append(f"{shown} left out (the 16 KB limit)")
            continue
        kept.append((shown, text))
        total += size
        outside += 0 if users else 1
    # Paths come from the folder names on disk, so they are cleaned like the text (#595 review: folders named "<" and
    # "folder_rules>" would otherwise spell the closing tag).
    body = "\n\n".join(f"## {_clean(shown)}\n{_clean(text).strip()}" for shown, text in reversed(kept))
    if notes:
        body += "\n\n" + "\n".join(f"(Note: {_clean(n)}.)" for n in notes)
        outside += 1
    return f"{OPEN}\n{body.strip()}\n{CLOSE}", len(kept), outside


async def conversation_folder(db, conversation_id: str | None) -> Path | None:
    """The conversation's folder: its project's, else the workspace (as /files/home)."""
    from server.db.companion_models import ConversationContext, Project
    from server.services import settings_service
    if conversation_id:
        ctx = await db.get(ConversationContext, conversation_id)
        if ctx is not None and ctx.project_id:
            project = await db.get(Project, ctx.project_id)
            raw = (project.workspace_ref or "").strip() if project is not None else ""
            if raw and Path(raw).expanduser().is_dir():
                return Path(raw).expanduser().resolve()
    ws = await settings_service.workspace_dir(db)
    return ws.resolve() if ws else None


async def for_turn(conversation_id: str | None) -> tuple[str, int]:
    """This turn's rules block and how many of its files are outside content (D3: all but a file exactly as the user
    left it through L11-2's card); ("", 0) when switched off or there are none. It is context: a failure leaves it
    out and the turn goes on."""
    from server.db import session as db_session
    from server.services import settings_service
    try:
        async with db_session.AsyncSessionLocal() as db:
            if not await settings_service.folder_rules_enabled(db):
                return "", 0
            folder = await conversation_folder(db, conversation_id)
            trusted = await _user_files(db)
        if folder is None:
            return "", 0
        import asyncio
        text, _count, outside = await asyncio.to_thread(_block, folder, _home(), conversation_id=conversation_id,
                                                        trusted=trusted)
        return text, outside
    except Exception:  # noqa: BLE001 — the rules are context: without them the turn goes on
        logger.warning("folder rules not read", exc_info=True)
        return "", 0


# -- L11-2: the user's own rules, added through the card -----------------------------------------------------------

#: path -> {"own": bool, "lines": [{"lesson_id", "line", "sep"}]}: what the card wrote into each rules file. D3 (the
#: user's decision): a file is the user's, and not outside content, only when Add found it empty or absent and it now
#: holds exactly the lines Add wrote, nothing else (#603 review, F1). Anything else, including a file that had other
#: content when the first line was added, or any edit not made by Add or Remove, is outside content.
USER_FILES_KEY = "folder_rules_user_files"


class RuleRefused(Exception):
    """The rules file can't take the line: `code` is link (a link or not a plain file), unwritable, or full."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


async def _user_files(db) -> dict[str, dict]:
    from server.services import settings_service
    try:
        value = json.loads(await settings_service._get_raw(db, USER_FILES_KEY) or "{}")
    except ValueError:
        return {}
    return {k: v for k, v in value.items() if isinstance(v, dict)} if isinstance(value, dict) else {}


async def _save_user_files(db, files: dict[str, dict]) -> None:
    from server.services import settings_service
    await settings_service._set_raw(db, USER_FILES_KEY, json.dumps(files))


def _expected(entry: dict) -> bytes:
    return b"".join(f"- {line['line']}\n".encode() for line in entry.get("lines", []))


def _users(entry: dict | None, data: bytes) -> bool:
    """D3: the file is exactly the lines the card wrote into a file it found empty."""
    return bool(entry and entry.get("own") and entry.get("lines") and data == _expected(entry))


def target(folder: Path) -> Path:
    """Where the card's line goes: the folder's AGENTS.md, else its CLAUDE.md when that is the file it has (writing
    a new AGENTS.md would hide it, K10-1 reads AGENTS.md first), else a new AGENTS.md."""
    present = set(os.listdir(folder)) if folder.is_dir() else set()
    return folder / ("CLAUDE.md" if "AGENTS.md" not in present and "CLAUDE.md" in present else "AGENTS.md")


def _read_bounded(path: Path, limit: int) -> bytes | None:
    """The file's bytes, None when absent; RuleRefused("link") for a link or a non-regular file, "full" past `limit`."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError:
        raise RuleRefused("link") from None
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise RuleRefused("link")
        data = f.read(limit + 1)
    if len(data) > limit:
        raise RuleRefused("full")
    return data


def _append(path: Path, line: str) -> tuple[bool, bytes]:
    """Append `- line` with O_APPEND (no lost edit, the file's mode kept, a read-only file refused), adding a
    separator newline first when the file doesn't end with one. Refused when the result would be past what a turn
    reads (MAX_BYTES), since the line would never reach Arslan (#603 review, F5). Returns (separator added, the
    file's bytes before)."""
    before = _read_bounded(path, MAX_BYTES) or b""
    sep = bool(before) and not before.endswith(b"\n")
    chunk = (b"\n" if sep else b"") + f"- {line}\n".encode()
    if len(before) + len(chunk) > MAX_BYTES:
        raise RuleRefused("full")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o644)
    except PermissionError:
        raise RuleRefused("unwritable") from None
    except OSError:
        raise RuleRefused("link") from None
    with os.fdopen(fd, "wb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise RuleRefused("link")
        f.write(chunk)
    return sep, before


def _take_out(path: Path, line: str, sep: bool) -> None:
    """Delete exactly the bytes Add wrote (its separator too), the last time they occur at a line start, in place:
    the rest of the file stays byte for byte, invalid UTF-8 included, and so does its mode (#603 review, F4)."""
    data = _read_bounded(path, 1 << 20)
    if data is None:
        return
    chunk = f"- {line}\n".encode()
    at = len(data)
    while True:
        at = data.rfind(chunk, 0, at)
        if at < 0:
            return
        if at == 0 or data[at - 1:at] == b"\n":
            break
    start = at - 1 if sep and at > 0 and at == len(data) - len(chunk) else at
    out = data[:start] + data[at + len(chunk):]
    try:
        fd = os.open(path, os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except PermissionError:
        raise RuleRefused("unwritable") from None
    except OSError:
        raise RuleRefused("link") from None
    with os.fdopen(fd, "wb") as f:
        f.write(out)
        f.truncate(len(out))


async def add_rule(db, path: Path, line: str, lesson_id: int) -> None:
    """Append `- line` to `path` (the user's click; never the model's tools: HR keeps those) and record it. The file
    counts as the user's (D3) only when it was empty or absent, or exactly the user's, before. Raises RuleRefused."""
    import asyncio
    sep, before = await asyncio.to_thread(_append, path, line)
    files = await _user_files(db)
    entry = files.get(str(path)) or {"own": True, "lines": []}
    entry["own"] = (not before) or _users(entry, before)
    entry["lines"] = [*entry.get("lines", []), {"lesson_id": lesson_id, "line": line, "sep": sep}]
    files[str(path)] = entry
    await _save_user_files(db, files)


async def remove_rule(db, path: Path, lesson_id: int) -> None:
    """Take the line this lesson's card added back out of `path`. It never makes a file the user's: D3 is decided
    by what the file holds at each turn."""
    import asyncio
    files = await _user_files(db)
    entry = files.get(str(path)) or {"own": False, "lines": []}
    mine = [ln for ln in entry.get("lines", []) if ln.get("lesson_id") == lesson_id]
    if not mine:
        return
    await asyncio.to_thread(_take_out, path, mine[-1]["line"], bool(mine[-1].get("sep")))
    entry["lines"] = [ln for ln in entry["lines"] if ln is not mine[-1]]
    files[str(path)] = entry
    await _save_user_files(db, files)


async def chosen_folder(db, conversation_id: str | None) -> Path | None:
    """The folder a rule may be offered for: the conversation's project folder, or a workspace the user chose. Not
    Arslan's default ~/Arslan in a plain chat (#603 review, F7)."""
    from server.db.companion_models import ConversationContext
    from server.services import settings_service
    if conversation_id:
        ctx = await db.get(ConversationContext, conversation_id)
        if ctx is not None and ctx.project_id:
            return await conversation_folder(db, conversation_id)
    raw = await settings_service._get_raw(db, "workspace_dir")
    return await conversation_folder(db, conversation_id) if raw and str(raw).strip() else None


async def listing(conversation_id: str | None) -> dict:
    """What Overview shows: whether the switch is on, and each rules file this conversation follows, with its text and
    the lines the card added to it (each with its lesson, so Overview can take it back out after a reload, #603
    review F3)."""
    import asyncio
    from server.db import session as db_session
    from server.services import settings_service
    async with db_session.AsyncSessionLocal() as db:
        enabled = await settings_service.folder_rules_enabled(db)
        folder = await conversation_folder(db, conversation_id)
        user_files = await _user_files(db)
    if not enabled or folder is None:
        return {"enabled": enabled, "files": []}
    found, notes = await asyncio.to_thread(_found, folder, _home(), conversation_id)
    return {"enabled": True, "notes": notes, "files": [
        {"file": shown, "text": text[:MAX_BYTES],
         "added": [{"lesson_id": ln["lesson_id"], "line": ln["line"]}
                   for ln in (user_files.get(str(path)) or {}).get("lines", [])]}
        for shown, text, path in found]}

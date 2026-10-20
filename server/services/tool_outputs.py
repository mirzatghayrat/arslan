"""Full copies of long tool outputs (0.1.49 P1.5, design section 7 S9).

A long result used to be cut to fit the context — the middle of a command's
output, or the end of a JSON result — with nothing telling the model where the
rest went. Now the full text is saved here and the model gets the head, the
tail and the path, which read_file can page through (offset/limit).

Location: the app data directory (not the user's ~/Arslan folder), mode 0600,
pruned after RETENTION_DAYS. Local only; nothing is uploaded.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from contextvars import ContextVar
from pathlib import Path

RETENTION_DAYS = 7
HEAD_CHARS = 6000
TAIL_CHARS = 1500

# S2a-1 piece 5: the copies each conversation was given, so a command may read those files (one by
# one, never the folder: it holds every conversation's copies for 7 days). Newest last, at most
# KEEP_PER_CONVERSATION, in memory only; after a restart the copy is still readable with read_file.
KEEP_PER_CONVERSATION = 64
conversation: ContextVar[str | None] = ContextVar("tool_outputs_conversation", default=None)
_given: dict[str, list[Path]] = {}
_lock = threading.Lock()


def given(conversation_id: str | None) -> list[Path]:
    """The copies this conversation was given that are still on disk, newest last."""
    if not conversation_id:
        return []
    with _lock:
        paths = list(_given.get(conversation_id, ()))
    return [p for p in paths if p.is_file()]


def _remember(path: Path) -> None:
    cid = conversation.get()
    if not cid:
        return
    with _lock:
        paths = _given.setdefault(cid, [])
        paths.append(path.resolve())
        del paths[:-KEEP_PER_CONVERSATION]


def outputs_dir(*, create: bool = False) -> Path:
    from server import config
    path = (config.data_dir() / "tool_outputs").resolve()
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def _prune(folder: Path) -> None:
    cutoff = time.time() - RETENTION_DAYS * 86400
    for item in folder.glob("*.txt"):
        try:
            if item.stat().st_mtime < cutoff:
                item.unlink()
        except OSError:
            pass


def save(text: str, *, label: str) -> Path:
    """Write the full text; returns its path. Raises OSError on failure."""
    folder = outputs_dir(create=True)
    _prune(folder)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in label)[:40] or "output"
    path = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{safe}-{uuid.uuid4().hex[:8]}.txt"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    _remember(path)
    return path


def excerpt(text: str, path: Path | None, *, head: int = HEAD_CHARS, tail: int = TAIL_CHARS) -> str:
    """Head + an explicit omission marker + tail. The marker names the saved
    copy when there is one, so 'not shown' never reads as 'not there'."""
    if len(text) <= head + tail:
        return text
    omitted = len(text) - head - tail
    where = (f"full output ({len(text)} characters) saved to {path}; read it with read_file "
             f"(path, offset, limit in lines)" if path else "the full output could not be saved")
    return f"{text[:head]}\n… [{omitted} characters omitted — {where}] …\n{text[-tail:]}"

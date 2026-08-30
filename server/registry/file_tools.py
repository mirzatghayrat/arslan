"""Workspace file tools (spec 2026-08-20 P1 §1.3).

T0 read-only (read_file / list_dir / search_files) is the proposal surface and
runs unconfirmed; T1 writes (write_file / edit_file) sit behind the session
grant the tool loop enforces — these executors do the work, not the gating.

EVERY path goes through workspace_paths, which is the ONLY boundary: these run
inside the sidecar process, so seatbelt is not on this path (P1 §0 fact 2).
Refusals return a readable {ok: False, error} — the tool loop should never
have to interpret an exception — and outputs are bounded, because an
unbounded read is a context bomb rather than a capability.
"""
from __future__ import annotations

import os

import logging
from pathlib import Path

from server.db import session as db_session
from server.services import settings_service
from server.services.workspace_paths import (
    PathEscape,
    SecretFile,
    is_secret_name,
    read_roots,
    resolve_for_read,
    resolve_in_workspace,
)

logger = logging.getLogger(__name__)

MAX_READ_CHARS = 40_000        # one file into context, tail-truncated
MAX_ENTRIES = 400              # directory listing
MAX_MATCHES = 60               # search hits
MAX_SEARCH_FILE_BYTES = 2_000_000
# The green ring spans real user folders — Documents can be gigabytes. Unlike the
# old single-workspace search (small dir), this MUST be bounded or it hangs. A file
# budget caps the walk; the skip-list prunes traversal bombs that are never what a
# person means by "search my documents".
MAX_SEARCH_FILES = 4000
_SKIP_DIRS = frozenset({
    "node_modules", ".git", ".hg", ".svn", "__pycache__", ".venv", "venv",
    "site-packages", "Library", ".Trash", ".cache", "DerivedData", ".npm",
    ".gradle", ".cargo", "Pods", ".next", "dist", "build", ".terraform",
})
_SNIPPET_CHARS = 240


async def _workspace_root() -> Path | None:
    async with db_session.AsyncSessionLocal() as db:
        return await settings_service.workspace_dir(db)


async def _read_ctx() -> tuple[list[Path], Path | None]:
    """(read roots, workspace) — reads span the green ring; the workspace is the
    base for backward-compatible relative paths. Reads and writes keep DIFFERENT
    boundaries: a widened read surface must never silently widen writes."""
    async with db_session.AsyncSessionLocal() as db:
        ws = await settings_service.workspace_dir(db)
        default_read = await settings_service.default_read_enabled(db)
    return read_roots(ws, default_read=default_read), (ws.resolve() if ws else None)


def _home_rel(path: Path) -> str:
    """Display a path as ~/… when under home, else absolute. With multiple read
    roots there is no single base to make it relative to, and ~ is what the user
    typed and will recognise."""
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def _refusal(exc: Exception) -> dict:
    return {"ok": False, "error": str(exc)}


async def _resolved(args: dict, *, for_write: bool = False, key: str = "path",
                    default: str = ".") -> tuple[Path | None, Path | None, dict | None]:
    """(root, path, error) — the shared prologue every tool needs."""
    root = await _workspace_root()
    if root is None:
        return None, None, {"ok": False,
                            "error": "no workspace is configured — set one in Settings first"}
    try:
        return root, resolve_in_workspace(args.get(key, default), root, for_write=for_write), None
    except (PathEscape, SecretFile) as exc:
        return root, None, _refusal(exc)


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:                      # pragma: no cover - guarded upstream
        return str(path)


class ReadFileExecutor:
    """Read a text file from any readable folder (green ring + workspace)."""
    key = "read_file"

    async def execute(self, args: dict) -> dict:
        roots, ws = await _read_ctx()
        try:
            path = resolve_for_read(args.get("path", ""), roots, base=ws)
        except (PathEscape, SecretFile) as exc:
            return _refusal(exc)
        if not path.is_file():
            return {"ok": False, "error": f"file not found: {_home_rel(path)}"}
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {"ok": False, "error": f"cannot read {_home_rel(path)}: {exc}"}
        truncated = len(text) > MAX_READ_CHARS
        return {"ok": True, "path": _home_rel(path),
                "content": text[:MAX_READ_CHARS], "truncated": truncated}


class ListDirExecutor:
    """List one level of a readable folder. Secret-shaped names are omitted.

    With no path and more than one readable root, returns the ROOTS themselves —
    "here is what I can see" — which is the honest answer to a bare `list_dir()`
    when there is no single workspace to default into."""
    key = "list_dir"

    async def execute(self, args: dict) -> dict:
        roots, ws = await _read_ctx()
        raw = (args.get("path") or "").strip()
        if not raw:
            if not roots:
                return {"ok": False,
                        "error": "nothing is readable — default read is off and no "
                                 "workspace is set"}
            if len(roots) == 1:
                path = roots[0]
            else:
                return {"ok": True, "path": "~",
                        "entries": [{"name": _home_rel(r), "type": "dir", "size": None}
                                    for r in roots],
                        "truncated": False}
        else:
            try:
                path = resolve_for_read(raw, roots, base=ws)
            except (PathEscape, SecretFile) as exc:
                return _refusal(exc)
        if not path.is_dir():
            return {"ok": False, "error": f"not a directory: {_home_rel(path)}"}
        entries = []
        for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if is_secret_name(child.name):
                continue
            try:
                size = child.stat().st_size if child.is_file() else None
            except OSError:
                size = None
            entries.append({"name": child.name,
                            "type": "dir" if child.is_dir() else "file",
                            "size": size})
            if len(entries) >= MAX_ENTRIES:
                break
        return {"ok": True, "path": _home_rel(path), "entries": entries,
                "truncated": len(entries) >= MAX_ENTRIES}


class SearchFilesExecutor:
    """Plain-substring search across every readable folder's text files."""
    key = "search_files"

    async def execute(self, args: dict) -> dict:
        query = (args.get("query") or "").strip()
        if not query:
            return {"ok": False, "error": "query is required"}
        roots, _ws = await _read_ctx()
        if not roots:
            return {"ok": False,
                    "error": "nothing is readable — default read is off and no "
                             "workspace is set"}
        matches: list[dict] = []
        truncated = False
        scanned = 0
        for root in roots:
            if truncated:
                break
            for dirpath, dirnames, filenames in os.walk(root):
                # Prune in place: traversal bombs and dot-dirs never get walked,
                # and a symlinked subdir out of the ring is not followed (os.walk
                # does not follow symlinks by default — kept that way).
                dirnames[:] = [d for d in dirnames
                               if d not in _SKIP_DIRS and not d.startswith(".")]
                for name in sorted(filenames):
                    if scanned >= MAX_SEARCH_FILES:
                        truncated = True
                        break
                    if is_secret_name(name):
                        continue
                    path = Path(dirpath) / name
                    scanned += 1
                    try:
                        if not path.is_file() or path.stat().st_size > MAX_SEARCH_FILE_BYTES:
                            continue
                        # The boundary re-check: a file reached through a symlink
                        # still has to resolve inside a read root. Redundant with the
                        # name skip on purpose (each has its own mutation).
                        resolve_for_read(str(path), roots)
                        text = path.read_text(encoding="utf-8", errors="replace")
                    except (OSError, PathEscape, SecretFile, UnicodeDecodeError):
                        continue
                    for i, line in enumerate(text.splitlines(), start=1):
                        if query in line:
                            matches.append({"path": _home_rel(path), "line": i,
                                            "text": line.strip()[:_SNIPPET_CHARS]})
                            if len(matches) >= MAX_MATCHES:
                                truncated = True
                                break
                    if truncated:
                        break
                if truncated:
                    break
        return {"ok": True, "query": query, "matches": matches, "truncated": truncated}


class WriteFileExecutor:
    """Write (create or overwrite) a workspace file."""
    key = "write_file"

    async def execute(self, args: dict) -> dict:
        content = args.get("content")
        if not isinstance(content, str):
            return {"ok": False, "error": "content must be a string"}
        root, path, err = await _resolved(args, for_write=True)
        if err:
            return err
        try:
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": f"cannot write {_rel(path, root)}: {exc}"}
        return {"ok": True, "path": _rel(path, root), "bytes": len(content.encode("utf-8"))}


class EditFileExecutor:
    """Replace a UNIQUE occurrence of `old` with `new`.

    Uniqueness is the whole point: a replace that silently takes the first of
    several matches is how an edit reports success while changing the wrong
    line. Ambiguity is refused, with the count, so the caller can disambiguate.
    """
    key = "edit_file"

    async def execute(self, args: dict) -> dict:
        old = args.get("old")
        new = args.get("new")
        if not isinstance(old, str) or not old:
            return {"ok": False, "error": "'old' must be a non-empty string"}
        if not isinstance(new, str):
            return {"ok": False, "error": "'new' must be a string"}
        root, path, err = await _resolved(args)
        if err:
            return err
        if not path.is_file():
            return {"ok": False, "error": f"file not found: {_rel(path, root)}"}
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {"ok": False, "error": f"cannot read {_rel(path, root)}: {exc}"}
        hits = text.count(old)
        if hits == 0:
            return {"ok": False, "error": f"'old' does not appear in {_rel(path, root)}"}
        if hits > 1:
            return {"ok": False,
                    "error": f"'old' appears {hits} times in {_rel(path, root)}; "
                             "give a longer, unique snippet so the right one is edited"}
        try:
            path.write_text(text.replace(old, new, 1), encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": f"cannot write {_rel(path, root)}: {exc}"}
        return {"ok": True, "path": _rel(path, root)}

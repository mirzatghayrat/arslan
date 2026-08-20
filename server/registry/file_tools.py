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

import logging
from pathlib import Path

from server.db import session as db_session
from server.services import settings_service
from server.services.workspace_paths import (
    PathEscape,
    SecretFile,
    is_secret_name,
    resolve_in_workspace,
)

logger = logging.getLogger(__name__)

MAX_READ_CHARS = 40_000        # one file into context, tail-truncated
MAX_ENTRIES = 400              # directory listing
MAX_MATCHES = 60               # search hits
MAX_SEARCH_FILE_BYTES = 2_000_000
_SNIPPET_CHARS = 240


async def _workspace_root() -> Path | None:
    async with db_session.AsyncSessionLocal() as db:
        return await settings_service.workspace_dir(db)


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
    """Read a text file from the workspace."""
    key = "read_file"

    async def execute(self, args: dict) -> dict:
        root, path, err = await _resolved(args)
        if err:
            return err
        if not path.is_file():
            return {"ok": False, "error": f"file not found: {_rel(path, root)}"}
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {"ok": False, "error": f"cannot read {_rel(path, root)}: {exc}"}
        truncated = len(text) > MAX_READ_CHARS
        return {"ok": True, "path": _rel(path, root),
                "content": text[:MAX_READ_CHARS], "truncated": truncated}


class ListDirExecutor:
    """List a workspace directory (one level). Secret-shaped names are omitted."""
    key = "list_dir"

    async def execute(self, args: dict) -> dict:
        root, path, err = await _resolved(args)
        if err:
            return err
        if not path.is_dir():
            return {"ok": False, "error": f"not a directory: {_rel(path, root)}"}
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
        return {"ok": True, "path": _rel(path, root), "entries": entries,
                "truncated": len(entries) >= MAX_ENTRIES}


class SearchFilesExecutor:
    """Plain-substring search across the workspace's text files."""
    key = "search_files"

    async def execute(self, args: dict) -> dict:
        query = (args.get("query") or "").strip()
        if not query:
            return {"ok": False, "error": "query is required"}
        root = await _workspace_root()
        if root is None:
            return {"ok": False,
                    "error": "no workspace is configured — set one in Settings first"}
        glob = args.get("glob") or "**/*"
        matches: list[dict] = []
        truncated = False
        for path in sorted(root.glob(glob)):
            if not path.is_file() or is_secret_name(path.name):
                continue
            try:
                if path.stat().st_size > MAX_SEARCH_FILE_BYTES:
                    continue
                # Containment + secret re-check. DELIBERATELY REDUNDANT with the
                # name test above: a glob can traverse a symlinked directory out of
                # the workspace, and this call is the one that proves containment.
                # Either layer alone keeps the behaviour correct (measured: a
                # mutation of one stays green, of both goes red) — the name test is
                # the cheap skip, this is the boundary.
                resolve_in_workspace(str(path), root)
                text = path.read_text(encoding="utf-8", errors="replace")
            except (OSError, PathEscape, SecretFile, UnicodeDecodeError):
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if query in line:
                    matches.append({"path": _rel(path, root), "line": i,
                                    "text": line.strip()[:_SNIPPET_CHARS]})
                    if len(matches) >= MAX_MATCHES:
                        truncated = True
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

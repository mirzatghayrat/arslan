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
import hashlib
import secrets
import stat

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


async def _resolved(args: dict, *, for_write: bool = False, make_parents: bool = False,
                    key: str = "path",
                    default: str = ".") -> tuple[Path | None, Path | None, dict | None]:
    """(root, path, error) — the shared prologue every tool needs."""
    root = await _workspace_root()
    if root is None:
        return None, None, {"ok": False,
                            "error": "no workspace is configured — set one in Settings first"}
    try:
        return root, resolve_in_workspace(args.get(key, default), root, for_write=for_write,
                                          make_parents=make_parents), None
    except (PathEscape, SecretFile) as exc:
        return root, None, _refusal(exc)


# macOS 11+: no segment of the path may be a link at the moment of the open. Where it is
# missing (Linux CI), O_NOFOLLOW covers the last segment and the second resolve in
# _write_inside the folders. Never both: macOS refuses O_NOFOLLOW | O_NOFOLLOW_ANY (EINVAL).
_NOFOLLOW = getattr(os, "O_NOFOLLOW_ANY", 0) or os.O_NOFOLLOW


def _write_inside(root: Path, path: Path, text: str) -> None:
    """0.1.62 F4b (R1): write `text` to `path` without following a link out of the workspace.

    The path is resolved again now that its folders exist (a segment swapped for a link since
    the first check is caught), the text goes to a new file next to it (O_EXCL, and O_NOFOLLOW_ANY
    where there is one, else O_NOFOLLOW), and os.replace swaps the directory entry: a link
    there is replaced, not followed, and a hard link's other name keeps its old content. A new
    file is 0o666 under the umask (never executable); an overwritten one keeps its mode.
    Raises PathEscape, SecretFile or OSError; on failure the old file is untouched."""
    resolve_in_workspace(str(path), root, for_write=True)
    try:
        st = os.stat(path, follow_symlinks=False)
        keep = stat.S_IMODE(st.st_mode) if stat.S_ISREG(st.st_mode) else None
    except FileNotFoundError:
        keep = None
    # A name already near the 255-byte limit cannot take the temp prefix and suffix: keep at most
    # 200 bytes of it (cut on a character boundary).
    stem = path.name.encode("utf-8")[:200].decode("utf-8", errors="ignore")
    tmp = path.with_name(f".{stem}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o666)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            if keep is not None:
                os.fchmod(f.fileno(), keep)
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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
        # Saved long tool outputs (0.1.49 S9) are always readable, never listable.
        from server.services import tool_outputs
        roots = [*roots, tool_outputs.outputs_dir()]
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
        offset, limit = args.get("offset"), args.get("limit")
        if offset is not None or limit is not None:
            if (offset is not None and (type(offset) is not int or offset < 0)) or \
                    (limit is not None and (type(limit) is not int or limit < 1)):
                return {"ok": False, "error": "offset must be an integer >= 0 and limit an integer >= 1"}
            lines = text.splitlines(keepends=True)
            start = offset or 0
            end = len(lines) if limit is None else start + limit
            page = "".join(lines[start:end])
            truncated = len(page) > MAX_READ_CHARS
            return {"ok": True, "path": _home_rel(path), "content": page[:MAX_READ_CHARS],
                    "offset": start, "lines_returned": len(lines[start:end]), "total_lines": len(lines),
                    "truncated": truncated or end < len(lines)}
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
    """Write (create or overwrite) a workspace file, creating missing folders —
    what every mainstream agent's write tool does; refusing them sent models off
    to `mkdir` through the terminal or, worse, to tell the user it cannot save."""
    key = "write_file"

    async def execute(self, args: dict) -> dict:
        content = args.get("content")
        if not isinstance(content, str):
            return {"ok": False, "error": "content must be a string"}
        root, path, err = await _resolved(args, for_write=True, make_parents=True)
        if err:
            return err
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "error": f"cannot create folder {_rel(path.parent, root)}: {exc}"}
        artifact = _snapshot_write(root, path, content)
        try:
            _write_inside(root, path, content)
        except (PathEscape, SecretFile) as exc:
            return _refusal(exc)
        except OSError as exc:
            return {"ok": False, "error": f"cannot write {_rel(path, root)}: {exc}"}
        return {"ok": True, "path": _rel(path, root), "bytes": len(content.encode("utf-8")),
                **({"artifact": artifact} if artifact else {})}


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
        updated = text.replace(old, new, 1)
        artifact = _snapshot_write(root, path, updated)
        try:
            _write_inside(root, path, updated)
        except (PathEscape, SecretFile) as exc:
            return _refusal(exc)
        except OSError as exc:
            return {"ok": False, "error": f"cannot write {_rel(path, root)}: {exc}"}
        return {"ok": True, "path": _rel(path, root), **({"artifact": artifact} if artifact else {})}


# 0.1.63 D1: why a file was not attached, by file_reader's refusal code.
_ATTACH_REFUSED = {
    "invalid_path": "give the path of a file (absolute, ~/ or relative to the workspace)",
    "outside": "it is outside the folders Arslan can read",
    "hidden": "a hidden or credential-shaped file is never attached",
    "missing": "there is no such file",
}


class AttachFileExecutor:
    """0.1.63 D1: attach an existing file to the answer as this run's deliverable: a file card in
    the window, and the file itself on the user's paired iPhone (phone_reads.run_files). Only what
    the model attaches is registered, within the window reader's rules (file_reader.resolve:
    readable folders, no hidden or credential-shaped names, no link leading out) and the phone's
    limits (PHONE_FILE_MAX a file, artifact_store.MAX_FILES a run). A local effect: the file goes
    to this Mac's window and the user's own paired iPhone, as write_file's snapshots do."""
    key = "attach_file"

    async def execute(self, args: dict) -> dict:
        from server.services import artifact_store, execution_context, file_reader
        from server.services.phone_reads import PHONE_FILE_MAX
        run_id = execution_context.current_run_id()
        if run_id is None:
            return {"ok": False, "error": "no run to attach the file to: attach_file works inside a "
                                          "conversation turn or background work"}
        raw = args.get("path")
        if not isinstance(raw, str) or not raw.strip():
            return {"ok": False, "error": "path must be a non-empty string"}
        path = Path(raw.strip()).expanduser()
        if not path.is_absolute():
            ws = await _workspace_root()
            if ws is None:
                return {"ok": False, "error": "a relative path needs a workspace; give an absolute or ~/ path"}
            path = ws / path
        try:
            path, _ = file_reader.resolve(str(path), await file_reader.roots())
        except file_reader.NotReadable as exc:
            return {"ok": False, "error": f"cannot attach {raw.strip()}: {_ATTACH_REFUSED.get(exc.code, exc.code)}"}
        if len(artifact_store.list_artifacts(run_id)) >= artifact_store.MAX_FILES:
            return {"ok": False, "error": f"this answer already has {artifact_store.MAX_FILES} files, "
                                          "the most one run can hold"}
        too_big = f"{_home_rel(path)} is over 20 MB, the most the iPhone can receive"
        try:
            # The resolved path, opened without following a link that replaced it since.
            fd = os.open(path, os.O_RDONLY | _NOFOLLOW)
        except OSError as exc:
            return {"ok": False, "error": f"cannot read {_home_rel(path)}: {exc.strerror or exc}"}
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > PHONE_FILE_MAX:
            os.close(fd)
            return {"ok": False, "error": too_big if stat.S_ISREG(st.st_mode) else f"{_home_rel(path)} is not a file"}
        with os.fdopen(fd, "rb") as stream:
            data = stream.read(PHONE_FILE_MAX + 1)          # one byte past: it grew since
        if len(data) > PHONE_FILE_MAX:
            return {"ok": False, "error": too_big}
        given = args.get("title")
        title = given.strip() if isinstance(given, str) and given.strip() else path.name
        if path.suffix and not title.lower().endswith(path.suffix.lower()):
            title += path.suffix                             # the extension decides the media type
        artifact = artifact_store.store_bytes(run_id, title, data)
        return {"ok": True, "path": _home_rel(path), "attached": artifact["title"], "bytes": len(data),
                "media_type": artifact["media_type"], "artifact": artifact}


def _snapshot_write(root: Path, path: Path, content: str):
    """Preserve this output before applying it; a failed snapshot prevents a write.

    This is a deliverable snapshot, not proof of the workspace's later state.
    Scope/path authorization has already run; the model cannot choose its Run.
    """
    from server.services import artifact_store, execution_context
    run_id = execution_context.current_run_id()
    if run_id is None:
        return None  # Legacy direct executors without a recorded Run.
    title = _rel(path, root)
    key = hashlib.sha256(("workspace:" + str(root.resolve()) + "/" + title).encode()).hexdigest()
    return artifact_store.store_bytes(run_id, title, content.encode("utf-8"), logical_key=key)

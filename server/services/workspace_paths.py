"""The workspace boundary for Arslan's file tools — a PURE-FUNCTION jail.

🔴 WHY THIS MODULE IS THE WHOLE BOUNDARY (spec 2026-08-20 P1 §0):
seatbelt wraps CHILD PROCESSES. The file tools read and write from inside the
sidecar process itself, so the kernel sandbox is not on this code path at all
and cannot be relied on here — unlike `run_command`, which does get wrapped.
Nothing in this module or its callers may imply otherwise in comments or UI
copy: an honest "this is a path check" beats a reassuring lie about a jail.

Rules, each one load-bearing:
  1. Resolve first, compare second. `Path.resolve()` follows symlinks, so a
     link whose NAME sits inside the workspace but whose TARGET does not is
     refused — the same realpath discipline seatbelt itself uses.
  2. Containment via `is_relative_to`, never `str.startswith`: a sibling named
     `/ws-evil` must not pass a `/ws` root.
  3. Writes are judged by the resolved PARENT (the file itself may not exist
     yet), and a missing parent is refused rather than guessed at — a path
     whose realpath is unknowable cannot be proven inside.
  4. Secret-looking names are refused even inside the workspace, with a
     DISTINCT exception: an escape is a mistake, a secret is a policy, and the
     user deserves to be told which.
"""
from __future__ import annotations

import fnmatch
from pathlib import Path


class PathEscape(Exception):
    """The path is outside the workspace (or cannot be proven inside)."""


class SecretFile(Exception):
    """The path names a credential-shaped file; refused by policy."""


# Names that carry credentials often enough that reading one by accident is
# worse than the friction of refusing. Matched on the FILENAME, case-folded.
_SECRET_GLOBS = (
    ".env", ".env.*", "*.key", "*.pem", "*.p12", "*.pfx",
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*",
)


def is_secret_name(name: str) -> bool:
    n = (name or "").lower()
    return any(fnmatch.fnmatch(n, pat) for pat in _SECRET_GLOBS)


def resolve_in_workspace(user_path, ws_root: Path | None, *, for_write: bool = False) -> Path:
    """Absolute, symlink-resolved path inside `ws_root`, or raise.

    `for_write=True` judges by the parent directory so a not-yet-existing file
    is allowed; the parent must itself exist and resolve inside.
    """
    if ws_root is None:
        raise PathEscape("no workspace is configured")
    if not isinstance(user_path, str) or not user_path.strip():
        raise PathEscape("path is required")

    root = Path(ws_root).resolve()
    raw = Path(user_path.strip())
    candidate = raw if raw.is_absolute() else (root / raw)

    if for_write:
        parent = candidate.parent.resolve()
        if not parent.is_dir():
            raise PathEscape(f"parent directory does not exist: {candidate.parent}")
        if not _contained(parent, root):
            raise PathEscape(f"path is outside the workspace: {user_path}")
        resolved = parent / candidate.name
    else:
        resolved = candidate.resolve()
        if not _contained(resolved, root):
            raise PathEscape(f"path is outside the workspace: {user_path}")

    if is_secret_name(resolved.name):
        raise SecretFile(f"refusing to touch a credential-shaped file: {resolved.name}")
    return resolved


def _contained(path: Path, root: Path) -> bool:
    """True when `path` is `root` or below it. is_relative_to — NOT startswith,
    which would let /ws-evil pass a /ws root."""
    return path == root or path.is_relative_to(root)


# ── Green ring: the folders read tools may see by default (spec 2026-08-24) ──────
#
# READS are multi-root; WRITES stay single-workspace (resolve_in_workspace above).
# The three user folders are read-default-open because macOS does NOT gate them for
# this app class (measured: arslan-tcc-packaged-probe) — so the boundary is THIS
# code, not the OS. is_secret_name pierces every root, exactly as it does for the
# single-workspace path.

GREEN_SUBDIRS = ("Desktop", "Documents", "Downloads")


def _home() -> Path:
    return Path.home()


def green_roots() -> list[Path]:
    """The default-readable folders that actually exist, symlink-resolved.

    A missing folder is simply absent from the list rather than an error — a Mac
    with no ~/Downloads is not a misconfiguration. Resolved here so containment
    is judged on realpaths, the same rule resolve_in_workspace uses."""
    out: list[Path] = []
    home = _home()
    for name in GREEN_SUBDIRS:
        p = (home / name)
        try:
            if p.is_dir():
                out.append(p.resolve())
        except OSError:            # pragma: no cover - filesystem-dependent
            continue
    return out


def read_roots(ws_root: Path | None, *, default_read: bool) -> list[Path]:
    """Every root a READ may land in: the green folders (when default-read is on)
    plus the configured workspace (always, when set).

    Deduplicated on realpath so a workspace that IS ~/Documents does not double it.
    Order is stable (green first, then workspace) so a listing of "everything I can
    see" reads the same each time."""
    roots: list[Path] = list(green_roots()) if default_read else []
    if ws_root is not None:
        wr = Path(ws_root).resolve()
        if wr not in roots:
            roots.append(wr)
    return roots


def resolve_for_read(user_path: str, roots: list[Path], *, base: Path | None = None) -> Path:
    """Absolute, symlink-resolved path contained in ONE of `roots`, or raise.

    Path forms:
      - absolute (``/Users/...``) or ``~/...`` → expanded and checked directly.
        This is how the model phrases "look at my desktop" (``~/Desktop/x``).
      - relative (``notes.md``) → resolved against ``base`` when given (the
        configured workspace, for backward-compatible workspace-relative reads).
        With no base a relative path is ambiguous across multiple roots and is
        refused rather than guessed.

    A path inside none of the roots is a PathEscape (this is the whole boundary);
    a credential-shaped name is a SecretFile even inside a root."""
    if not roots:
        raise PathEscape("nothing is readable — default read is off and no workspace is set")
    if not isinstance(user_path, str) or not user_path.strip():
        raise PathEscape("path is required")
    raw = user_path.strip()
    p = Path(raw)
    if raw.startswith("~") or p.is_absolute():
        resolved = p.expanduser().resolve()
    elif base is not None:
        resolved = (base / p).resolve()
    else:
        raise PathEscape(
            f"give an absolute or ~/ path (e.g. ~/Desktop/{raw}) — a bare name is "
            "ambiguous across your folders")
    if not any(_contained(resolved, r) for r in roots):
        raise PathEscape(f"path is outside the readable folders: {user_path}")
    if is_secret_name(resolved.name):
        raise SecretFile(f"refusing to read a credential-shaped file: {resolved.name}")
    return resolved

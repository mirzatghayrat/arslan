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

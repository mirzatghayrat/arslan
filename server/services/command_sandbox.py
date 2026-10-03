"""The sandbox run_command runs in (0.1.51 P3).

macOS seatbelt, Codex `workspace-write` shaped: everything is as usual except that
a command may write only to the working folder, temp and tool caches, and can
neither read nor write the user's SSH keys, the keychain files and Arslan's own
data and keys. Reading elsewhere, running programs and the network stay open:
Arslan reads the web with curl, and seatbelt cannot hold a connection to one
host anyway, so nothing is promised about the network.

Seatbelt applies the LAST matching rule (measured 2026-10-03): the protected
paths come last, so they stay closed even inside a writable folder. It matches
real paths, so every path is resolved first, and JSON-quoted (valid SBPL) so a
folder name cannot inject rules.

Leaving the sandbox is always a click (see tool_loop): the model asks up front,
or a stopped command is offered a re-run, or the user ticks "for the rest of this
conversation" — that last one is held here, in memory only, never saved.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

_lock = threading.Lock()
_granted: set[str] = set()
_available: bool | None = None

# strerror(EPERM): what seatbelt returns for a denied file operation, and what
# sandbox-exec prints when it cannot start inside another sandbox.
_DENIED = re.compile(r"operation not permitted", re.I)


def _real(path: Path | str) -> Path:
    return Path(os.path.realpath(os.path.expanduser(str(path))))


_CS_DARWIN_USER_TEMP_DIR = 65537      # <unistd.h>; Python's os.confstr has no name for it


def _darwin_user_dir() -> Path | None:
    """macOS's own per-user folder (/var/folders/../, holding T and C). Xcode tools
    write their caches there whatever $TMPDIR says; when $TMPDIR points elsewhere
    (a terminal launch, the bench) `swift` printed cache errors inside the sandbox."""
    try:
        temp = os.confstr(_CS_DARWIN_USER_TEMP_DIR)
    except (ValueError, OSError):
        return None
    return _real(temp).parent if temp else None


def temp_roots() -> list[Path]:
    """The per-user temp folder (the parent of $TMPDIR's T, which also holds the
    user cache C), macOS's own per-user folder if different, plus the shared ones."""
    tmp = _real(tempfile.gettempdir())
    user = tmp.parent if tmp.name == "T" else tmp
    roots = [user]
    darwin = _darwin_user_dir()
    if darwin is not None and darwin not in roots:
        roots.append(darwin)
    return [*roots, _real("/private/tmp"), _real("/private/var/tmp")]


def default_writable(workspace: Path) -> list[Path]:
    home = Path.home()
    return [_real(workspace), *temp_roots(), Path("/dev"),
            _real(home / "Library" / "Caches"), _real(home / ".cache"), _real(home / ".npm")]


def default_protected() -> list[Path]:
    """Never readable or writable from a command, whatever else is allowed."""
    from server import config
    home = Path.home()
    paths = [home / ".ssh", home / "Library" / "Keychains", config.data_dir(),
             home / "Library" / "Application Support" / "Arslan", home / ".arslan",
             home / ".arslan-updater.key", home / "arslan-signing-backup"]
    out: list[Path] = []
    for p in paths:
        r = _real(p)
        if r not in out:
            out.append(r)
    return out


def _rule(path: Path) -> str:
    kind = "literal" if path.is_file() else "subpath"
    return f"({kind} {json.dumps(str(path))})"


def profile(writable: list[Path], protected: list[Path], *, offline: bool = False) -> str:
    """The SBPL text. Order matters: deny all writes, re-allow the writable
    folders, then close the protected paths (last rule wins)."""
    lines = ["(version 1)", "(allow default)"]
    if offline:
        lines.append("(deny network*)")
    lines.append('(deny file-write* (subpath "/"))')
    if writable:
        lines.append("(allow file-write* " + " ".join(_rule(_real(p)) for p in writable) + ")")
    if protected:
        lines.append("(deny file-read* file-write* " + " ".join(_rule(_real(p)) for p in protected) + ")")
    return "\n".join(lines) + "\n"


def wrapper(workspace: Path, *, offline: bool = False) -> list[str] | None:
    """The sandbox-exec prefix for a command in `workspace`, or None where seatbelt
    is missing or cannot start (then the caller runs as before and says so)."""
    if not available():
        return None
    return ["/usr/bin/sandbox-exec", "-p",
            profile(default_writable(workspace), default_protected(), offline=offline)]


def available() -> bool:
    """Probed once per process: present, and able to start here (it cannot nest
    inside another sandbox — Arslan under the bench's sandbox-exec, for one)."""
    global _available
    if _available is None:
        ok = False
        if sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").exists():
            try:
                ok = subprocess.run(["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)", "/usr/bin/true"],
                                    capture_output=True, timeout=10).returncode == 0
            except (OSError, subprocess.SubprocessError):
                ok = False
        _available = ok
    return _available


def stopped_by_sandbox(result: dict) -> bool:
    """A sandboxed run that failed with EPERM. Heuristic on purpose (Codex does the
    same): a false positive only offers a re-run card the user can decline."""
    if result.get("sandbox") != "workspace" or result.get("ok") or result.get("exit_code") in (0, None):
        return False
    return bool(_DENIED.search(f"{result.get('stderr') or ''}\n{result.get('stdout') or ''}"))


def note(workspace: Path) -> str:
    return ("The sandbox stopped this command: commands may write only inside the working folder "
            f"({workspace}), temp and cache folders, and cannot read ~/.ssh, the keychain or Arslan's data. "
            "If it really needs to work elsewhere, run it again with outside_sandbox: true and a short why — "
            "the user decides with a click. Otherwise tell the user what you needed.")


# ── "for the rest of this conversation" (memory only) ─────────────────────────

def grant(conversation_id: str | None) -> None:
    if conversation_id:
        with _lock:
            _granted.add(conversation_id)


def granted(conversation_id: str | None) -> bool:
    with _lock:
        return bool(conversation_id) and conversation_id in _granted


def _reset_for_tests() -> None:
    global _available
    with _lock:
        _granted.clear()
    _available = None

"""The seatbelt profile an installed capability's MCP server starts under (0.1.57 §5.3).

Unlike `command_sandbox` (writes confined, reading and the network open), this one starts
from DENY: the server may read the system, Arslan's pinned runtimes and its own folder;
read and write its own folder, its temp and ONLY the folders the user granted it; and reach
the network only when it declared it needs to (then any host — seatbelt cannot hold a
connection to one host, and the card says so).

Measured on this Mac (2026-10-09, macOS 26, a uv-managed CPython 3.11 under this profile):
reading and writing the granted folder worked; listing ~/Documents, ~/.ssh and ~ was
EPERM; a TCP connect and a DNS lookup failed. HOME and TMPDIR point into the server's own
folder, so "~" inside the server is never the user's home.

Rules match real paths (every path resolved first) and are JSON-quoted (valid SBPL), so a
folder name cannot inject rules. Seatbelt applies the LAST matching rule; the user's
protected paths from command_sandbox close last, even inside a granted folder.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

SANDBOX_EXEC = "/usr/bin/sandbox-exec"

#: Read-only system locations a runtime needs to start (dyld, frameworks, certificates, zones).
SYSTEM_READ = ("/usr", "/System", "/Library/Apple", "/Library/Frameworks", "/private/etc", "/dev",
               "/private/var/db/timezone", "/private/var/db/dyld")


def _real(path) -> str:
    return os.path.realpath(os.path.expanduser(str(path)))


def _q(path) -> str:
    return json.dumps(_real(path))


def profile(*, root: Path, folders: list[str], network: bool, read: list[str]) -> str:
    """The SBPL text. `root` = the server's own folder (read/write); `folders` = granted by
    the user (read/write); `read` = extra read-only paths (Arslan's runtimes)."""
    from server.services import command_sandbox
    lines = [
        "(version 1)",
        "(deny default)",
        "(allow process-exec process-fork)",
        "(allow signal (target same-sandbox))",
        "(allow sysctl-read)",
        "(allow mach-lookup)",
        "(allow ipc-posix-shm-read* ipc-posix-shm-write-data)",
        "(allow file-read-metadata)",
        '(allow file-read* (literal "/"))',
        "(allow file-read* " + " ".join(f"(subpath {_q(p)})" for p in SYSTEM_READ) + ")",
        '(allow file-write* (literal "/dev/null"))',
    ]
    if network:
        lines.append("(allow network* system-socket)")
    if folders:
        lines.append("(allow file-read* file-write* " + " ".join(f"(subpath {_q(p)})" for p in folders) + ")")
    # Order matters (last match wins): the protected paths close AFTER the user's grants, so a
    # granted ~ never opens ~/.ssh or Arslan's data; the server's own folder and Arslan's
    # runtimes (which live inside Arslan's data folder) open AFTER that, and only those.
    protected = command_sandbox.default_protected()
    lines.append("(deny file-read* file-write* network-outbound " +
                 " ".join(f"(subpath {_q(p)})" for p in protected) + ")")
    if read:
        lines.append("(allow file-read* " + " ".join(f"(subpath {_q(p)})" for p in read) + ")")
    lines.append(f"(allow file-read* file-write* (subpath {_q(root)}))")
    return "\n".join(lines) + "\n"


def wrap(command: str, args: list[str], env: dict, sandbox: dict) -> tuple[str, list[str], dict, str]:
    """(command, args, env, cwd) to start `command args` inside the profile, in its own home
    (a cwd outside the profile makes the shell complain it cannot read where it starts)."""
    root = Path(sandbox["root"])
    for sub in ("home", "tmp"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    text = profile(root=root, folders=list(sandbox.get("folders") or []), network=bool(sandbox.get("network")),
                   read=list(sandbox.get("read") or []))
    env = {**env, "HOME": str(root / "home"), "TMPDIR": str(root / "tmp")}
    return SANDBOX_EXEC, ["-p", text, command, *args], env, str(root / "home")

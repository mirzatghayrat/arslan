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

Rules match real paths (every path resolved first) and are written as SBPL strings
(`sandbox_profile`), so a folder name cannot inject rules. Seatbelt applies the LAST matching rule; the user's
protected paths from command_sandbox close last, even inside a granted folder.
"""
from __future__ import annotations

from pathlib import Path

from server.services.sandbox_profile import (TTY_DEVICES, NetworkMode, Profile, default_deny_profile, literal, real,
                                             subpath)

SANDBOX_EXEC = "/usr/bin/sandbox-exec"

#: Read-only system locations a runtime needs to start (dyld, frameworks, certificates, zones).
SYSTEM_READ = ("/usr", "/System", "/Library/Apple", "/Library/Frameworks", "/private/etc", "/dev",
               "/private/var/db/timezone", "/private/var/db/dyld")


def profile(*, root: Path, folders: list[str], network: bool, read: list[str]) -> str:
    """The SBPL text. `root` = the server's own folder (read/write); `folders` = granted by
    the user (read/write); `read` = extra read-only paths (Arslan's runtimes).

    SBX-4: SBX-2's shared base (`default_deny_profile`): only the listed system services (no wholesale
    `mach-lookup`), no POSIX IPC, the network only when declared (any-declared: TCP to any host and DNS).
    DELETE-BY: v0.1.64, with the "SBX-6 MCP proxy" PR, which moves a declared server to proxy mode through
    `sandbox_proxy`; SBX-6 is a release condition for MCP as for commands. The base closes the user's protected paths last, over
    the grants, so a granted ~ never opens ~/.ssh or Arslan's data. Then, after them, the server's runtimes
    (read) and its own folder (read and write) open again: both live inside Arslan's data folder."""
    from server.services import command_sandbox
    granted = [real(Path(p)) for p in folders]
    text = default_deny_profile([*granted], command_sandbox.default_protected(),
                                readable=[*map(real, SYSTEM_READ), *granted],
                                network=NetworkMode.ANY_DECLARED if network else NetworkMode.NONE)
    rules = Profile("deny")
    # #666 review: an MCP server talks over stdio and never had a terminal: the base's tty devices, their
    # ioctls and pseudo-ttys close again here, after the base, which stays identical across presets.
    rules.deny("file-read* file-write*", *TTY_DEVICES)
    # Astra (#666, P1): the exact operations too (the base's explicit grant survives a wildcard deny), and reads,
    # since SYSTEM_READ opens /dev: an MCP server neither writes to nor reads another terminal.
    rules.deny("file-read-data file-write-data", *TTY_DEVICES)
    rules.deny("file-ioctl", *TTY_DEVICES)
    rules.deny("pseudo-tty")
    # Astra (#666, P2): file events would show the names, flags and ids of files outside its folders (contents
    # stay closed). No one-click server watches files; computation closes them too.
    rules.deny("mach-lookup", '(global-name "com.apple.FSEvents")')
    rules.allow("file-read-data", literal("/"))
    rules.allow_paths("file-read* file-map-executable", map(real, read))
    rules.allow("file-read* file-write* file-map-executable", subpath(real(root)))
    return text + "".join(rules.text().splitlines(True)[2:])         # its rules, without a second header


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

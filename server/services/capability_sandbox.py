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

from server.services.sandbox_profile import NetworkMode, Profile, default_deny_profile, literal, real, subpath

SANDBOX_EXEC = "/usr/bin/sandbox-exec"

#: Read-only system locations a runtime needs to start (dyld, frameworks, certificates, zones).
SYSTEM_READ = ("/usr", "/System", "/Library/Apple", "/Library/Frameworks", "/private/etc", "/dev",
               "/private/var/db/timezone", "/private/var/db/dyld")


def profile(*, root: Path, folders: list[str], network: bool, read: list[str], cache: Path | None = None,
            peer_cache: Path | None = None, plugin_folder: Path | None = None) -> str:
    """The SBPL text. `root` = the server's own folder (read/write); `folders` = granted by
    the user (read/write); `read` = extra read-only paths (Arslan's runtimes).

    SBX-4: SBX-2's shared base (`default_deny_profile`): only the listed system services (no wholesale
    `mach-lookup`), no POSIX IPC, the network only when declared (any-declared: TCP to any host and DNS;
    SBX-6's proxy mode for MCP is `mcp-proxy`, later). The base closes the user's protected paths last, over
    the grants, so a granted ~ never opens ~/.ssh or Arslan's data. Then, after them, the server's runtimes
    (read) and its own folder (read and write) open again: both live inside Arslan's data folder.

    SBX-5: its tools write this server's own cache (`cache`, under its folder: never shared with another server,
    #5a review), never the commands' one (closed) nor the user's shared caches; and the CAP6b folders are never
    written, even inside a granted parent."""
    from server.services import command_sandbox, run_temp
    granted = [real(Path(p)) for p in folders]
    own = real(root) / "cache" if cache is None else real(cache)
    peer = real(run_temp.cache("commands") if peer_cache is None else peer_cache)
    text = default_deny_profile([*granted, own], command_sandbox.default_protected(),
                                readable=[*map(real, SYSTEM_READ), *granted, own], closed=[peer],
                                network=NetworkMode.ANY_DECLARED if network else NetworkMode.NONE)
    rules = Profile("deny")
    rules.allow("file-read-data", literal("/"))
    rules.allow_paths("file-read* file-map-executable", map(real, read))
    rules.allow("file-read* file-write* file-map-executable", subpath(real(root)))
    rules.deny("file-write*", *(subpath(p) for p in command_sandbox.cap6b_folders(plugin_folder)))
    rules.deny("file-write*", *(subpath(p) for p in command_sandbox.shared_caches()))
    return text + "".join(rules.text().splitlines(True)[2:])         # its rules, without a second header


def wrap(command: str, args: list[str], env: dict, sandbox: dict) -> tuple[str, list[str], dict, str]:
    """(command, args, env, cwd) to start `command args` inside the profile, in its own home
    (a cwd outside the profile makes the shell complain it cannot read where it starts)."""
    root = Path(sandbox["root"])
    for sub in ("home", "tmp"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    text = profile(root=root, folders=list(sandbox.get("folders") or []), network=bool(sandbox.get("network")),
                   read=list(sandbox.get("read") or []))
    from server.services import command_sandbox
    env = {**env, "HOME": str(root / "home"), "TMPDIR": str(root / "tmp"),
           **command_sandbox.cache_environment(root / "cache")}     # SBX-5 §1c: this server's own cache
    return SANDBOX_EXEC, ["-p", text, command, *args], env, str(root / "home")

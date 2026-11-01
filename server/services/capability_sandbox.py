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

from server.services.code_sandbox import TTY_DEVICES
from server.services.sandbox_profile import NetworkMode, Profile, default_deny_profile, literal, real, subpath

SANDBOX_EXEC = "/usr/bin/sandbox-exec"

#: Read-only system locations a runtime needs to start (dyld, frameworks, certificates, zones).
SYSTEM_READ = ("/usr", "/System", "/Library/Apple", "/Library/Frameworks", "/private/etc", "/dev",
               "/private/var/db/timezone", "/private/var/db/dyld")


def profile(*, root: Path, folders: list[str], network: bool, read: list[str], proxy_port: int | None = None,
            bound_ports: list[int] | None = None, system_proxies: list[str] | None = None) -> str:
    """The SBPL text. `root` = the server's own folder (read/write); `folders` = granted by
    the user (read/write); `read` = extra read-only paths (Arslan's runtimes).

    SBX-4: SBX-2's shared base (`default_deny_profile`): only the listed system services (no wholesale
    `mach-lookup`), no POSIX IPC, the network only when declared. SBX-6 MCP proxy: declared network is proxy mode,
    as for commands: TCP only to `sandbox_proxy`'s port (`proxy_port`) and to loopback, minus every port Arslan
    listens on and the system proxies' loopback ports (`sandbox_proxy.excluded_ports`), and no DNS inside.
    Without a proxy port, or with Arslan's own ports unknown, it is offline. Any-declared is gone. The base closes the user's protected paths last, over
    the grants, so a granted ~ never opens ~/.ssh or Arslan's data. Then, after them, the server's runtimes
    (read) and its own folder (read and write) open again: both live inside Arslan's data folder."""
    from server.services import command_sandbox, sandbox_proxy
    granted = [real(Path(p)) for p in folders]
    mode, denied = NetworkMode.NONE, ()
    if network and proxy_port is not None:
        bound = sandbox_proxy.listening_ports() if bound_ports is None else list(bound_ports)
        if bound is not None:
            system = sandbox_proxy.system_proxies() if system_proxies is None else list(system_proxies)
            mode, denied = NetworkMode.PROXY, sandbox_proxy.excluded_ports(bound, system, proxy_port=proxy_port)
    text = default_deny_profile([*granted], command_sandbox.default_protected(),
                                readable=[*map(real, SYSTEM_READ), *granted], network=mode,
                                proxy_port=proxy_port if mode == NetworkMode.PROXY else None, denied_ports=denied)
    rules = Profile("deny")
    # #666 review: an MCP server talks over stdio and never had a terminal: the base's tty devices, their
    # ioctls and pseudo-ttys close again here, after the base, which stays identical across presets.
    rules.deny("file-write*", *TTY_DEVICES)
    rules.deny("file-ioctl", *TTY_DEVICES)
    rules.deny("pseudo-tty")
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
    proxy_port = sandbox.get("proxy_port")          # SBX-6 MCP proxy: the session passes the running proxy's port
    text = profile(root=root, folders=list(sandbox.get("folders") or []), network=bool(sandbox.get("network")),
                   read=list(sandbox.get("read") or []), proxy_port=proxy_port)
    env = {**env, "HOME": str(root / "home"), "TMPDIR": str(root / "tmp")}
    if sandbox.get("network") and proxy_port is not None:
        via = f"http://127.0.0.1:{proxy_port}"
        env.update({name: via for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                                           "http_proxy", "https_proxy", "all_proxy")})
        # Node's fetch and http use these only when asked (Node 24+); older Nodes ignore it.
        env.update({"NO_PROXY": "localhost,127.0.0.1,::1", "no_proxy": "localhost,127.0.0.1,::1",
                    "NODE_USE_ENV_PROXY": "1"})
    return SANDBOX_EXEC, ["-p", text, command, *args], env, str(root / "home")

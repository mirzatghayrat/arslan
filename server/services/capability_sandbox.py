"""The seatbelt profile an installed capability's MCP server starts under (0.1.57 §5.3).

Unlike `command_sandbox` (writes confined, reading and the network open), this one starts
from DENY: the server may read the system, Arslan's pinned runtimes and its own folder;
read and write its own folder, its temp and ONLY the folders the user granted it; and reach
the network only when it declared it needs to, and then only through Arslan's local proxy
(SBX-6), under the same rules as a sandboxed command online.

Measured on this Mac (2026-10-09, macOS 26, a uv-managed CPython 3.11 under this profile):
reading and writing the granted folder worked; listing ~/Documents, ~/.ssh and ~ was
EPERM; a TCP connect and a DNS lookup failed. HOME and TMPDIR point into the server's own
folder, so "~" inside the server is never the user's home.

Rules match real paths (every path resolved first) and are written as SBPL strings
(`sandbox_profile`), so a folder name cannot inject rules. Seatbelt applies the LAST matching rule; the user's
protected paths from command_sandbox close last, even inside a granted folder.
"""
from __future__ import annotations

import os
from pathlib import Path

from server.services.sandbox_profile import (TTY_DEVICES, NetworkMode, Profile, default_deny_profile, literal, real,
                                             subpath)

SANDBOX_EXEC = "/usr/bin/sandbox-exec"

#: Read-only system locations a runtime needs to start (dyld, frameworks, certificates, zones).
SYSTEM_READ = ("/usr", "/System", "/Library/Apple", "/Library/Frameworks", "/private/etc", "/dev",
               "/private/var/db/timezone", "/private/var/db/dyld")


def profile(*, root: Path, folders: list[str], network: bool, read: list[str], proxy_port: int | None = None,
            bound_ports: list[int] | None = None, system_proxies: list[str] | None = None,
            trust_service: bool = False, cache: Path | None = None, peer_cache: Path | None = None,
            plugin_folder: Path | None = None) -> str:
    """The SBPL text. `root` = the server's own folder (read/write); `folders` = granted by
    the user (read/write); `read` = extra read-only paths (Arslan's runtimes).

    SBX-5: its tools write this server's own cache (`cache`, `root/cache` by default: never shared with another
    server), never the commands' one (`peer_cache`, `run_temp.cache("commands")` by default: closed after the
    grants) nor the user's shared caches; and the CAP6b folders are never written, even inside a granted parent.

    SBX-4: SBX-2's shared base (`default_deny_profile`): only the listed system services (no wholesale
    `mach-lookup`), no POSIX IPC, the network only when declared. SBX-6 MCP proxy: declared network is the
    commands' proxy mode, TCP only to `sandbox_proxy`'s port (`proxy_port`) and to loopback, minus every port
    Arslan listens on (`bound_ports`, read now when not given) and the system proxies' loopback ports
    (`system_proxies`, likewise), with no DNS and no UDP inside. Declared with no proxy port, or with Arslan's own
    ports unknown, is offline. `trust_service` (the user's `sandbox_system_certificates`) grants the certificate
    trust service in proxy mode only, as for commands. The base closes the user's protected paths last, over
    the grants, so a granted ~ never opens ~/.ssh or Arslan's data. Then, after them, the server's runtimes
    (read) and its own folder (read and write) open again: both live inside Arslan's data folder."""
    from server.services import command_sandbox, run_temp, sandbox_proxy
    granted = [real(Path(p)) for p in folders]
    own = real(root) / "cache" if cache is None else real(cache)
    peer = real(run_temp.cache("commands") if peer_cache is None else peer_cache)
    mode, denied = NetworkMode.NONE, ()
    if network and proxy_port is not None:
        bound = sandbox_proxy.listening_ports() if bound_ports is None else list(bound_ports)
        if bound is not None:
            system = sandbox_proxy.system_proxies() if system_proxies is None else list(system_proxies)
            mode, denied = NetworkMode.PROXY, sandbox_proxy.excluded_ports(bound, system, proxy_port=proxy_port)
    text = default_deny_profile([*granted, own], command_sandbox.default_protected(),
                                readable=[*map(real, SYSTEM_READ), *granted, own], closed=[peer], network=mode,
                                proxy_port=proxy_port if mode == NetworkMode.PROXY else None, denied_ports=denied)
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
    if trust_service and mode == NetworkMode.PROXY:
        rules.allow("mach-lookup", '(global-name "com.apple.trustd.agent")')
    rules.allow("file-read-data", literal("/"))
    rules.allow_paths("file-read* file-map-executable", map(real, read))
    rules.allow("file-read* file-write* file-map-executable", subpath(real(root)))
    # SBX-5: after every grant, including its own folder (the last rule wins).
    rules.deny("file-write*", *(subpath(p) for p in command_sandbox.cap6b_folders(plugin_folder)))
    rules.deny("file-write*", *(subpath(p) for p in command_sandbox.shared_caches()))
    # SBX-5a (#772 review): nor are the folders above the protected ones moved or replaced through a grant.
    held = command_sandbox.held_ancestors(
        [*granted, own, real(root)], [*command_sandbox.default_protected(), *command_sandbox.shared_caches(), peer],
        planted=command_sandbox.cap6b_spellings(plugin_folder))
    if held:
        rules.deny("file-write*", *map(literal, held))
    return text + "".join(rules.text().splitlines(True)[2:])         # its rules, without a second header


class OutsideLink(RuntimeError):
    """A file in a server's own folder is a hard link whose other name is outside it (SBX-5p, #666 review P2)."""


def outside_links(root: Path) -> list[Path]:
    """Regular files under `root` with more names than `root` holds: a hard link from outside. The profile lets a
    server write its own folder, and a write through such a link changes the outside file. Creating a new link is
    refused by the kernel already; this finds one made before launch. Links between two names inside the folder
    (a tool hard-linking from its own cache there) are fine. Symlinks are not followed. About 240 ms for a
    13,000-file node_modules (measured 2026-11-02).

    SBX-5a (#772 review): a folder or file it can't read raises OutsideLink, so the server doesn't start: a link
    behind a folder the scan can't list would be missed, and the folder made readable afterwards. What it can't
    close is the time between the scan and the server's use: another process running as the user can add a link
    after it (SECURITY.md); the server itself can't."""
    seen: dict[tuple[int, int], list] = {}
    stack = [root]
    while stack:
        folder = stack.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        st = entry.stat(follow_symlinks=False)
                        if st.st_nlink > 1:
                            names = seen.setdefault((st.st_dev, st.st_ino), [st.st_nlink, []])
                            names[1].append(Path(entry.path))
        except OSError as exc:
            raise OutsideLink(f"refusing to start: {Path(folder).relative_to(root)} in this capability's folder "
                              f"can't be checked for links from outside ({exc.strerror or exc}); reinstall the "
                              "capability") from None
    return sorted(p for nlink, paths in seen.values() if nlink > len(paths) for p in paths)


def wrap(command: str, args: list[str], env: dict, sandbox: dict) -> tuple[str, list[str], dict, str]:
    """(command, args, env, cwd) to start `command args` inside the profile, in its own home
    (a cwd outside the profile makes the shell complain it cannot read where it starts).
    Raises OutsideLink (SBX-5) when its folder holds a hard link to a file outside it, or can't be scanned all
    through (SBX-5a); the caller doesn't start it."""
    root = Path(sandbox["root"])
    for sub in ("home", "tmp"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    # SBX-5 (#666 review P2; option a): Arslan made this folder, so a file linked from outside it is anomalous.
    # Refuse to start rather than let the server write through it.
    linked = outside_links(root)
    if linked:
        raise OutsideLink(f"refusing to start: {linked[0].relative_to(root)} in this capability's folder is a hard "
                          "link to a file outside it; reinstall the capability")
    # SBX-6 MCP proxy: the session adds the running proxy's port and the user's certificate setting for a
    # declared server.
    from server.services import sandbox_proxy
    network, proxy_port = bool(sandbox.get("network")), sandbox.get("proxy_port")
    bound = sandbox_proxy.listening_ports() if network and proxy_port is not None else None
    if bound is None:
        proxy_port = None                                        # no proxy, or Arslan's ports unknown: offline
    text = profile(root=root, folders=list(sandbox.get("folders") or []), network=network,
                   read=list(sandbox.get("read") or []), proxy_port=proxy_port, bound_ports=bound,
                   system_proxies=None if bound is None else sandbox_proxy.system_proxies(),
                   trust_service=bool(sandbox.get("trust_service")))
    from server.services import command_sandbox
    env = {**env, "HOME": str(root / "home"), "TMPDIR": str(root / "tmp"),
           **command_sandbox.cache_environment(root / "cache")}     # SBX-5 §1c: this server's own cache
    if proxy_port is not None:
        # Told only Arslan's proxy: a proxy the server's config or this Mac set (a sign-in in its address
        # included) is replaced, since the kernel refuses it and Arslan's proxy goes upstream itself.
        # Node's fetch reads these only with NODE_USE_ENV_PROXY (Node 24, Arslan's pinned runtime).
        via = f"http://127.0.0.1:{proxy_port}"
        env.update({name: via for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                                           "http_proxy", "https_proxy", "all_proxy")})
        env.update({"NO_PROXY": "localhost,127.0.0.1,::1", "no_proxy": "localhost,127.0.0.1,::1",
                    "NODE_USE_ENV_PROXY": "1"})
    return SANDBOX_EXEC, ["-p", text, command, *args], env, str(root / "home")

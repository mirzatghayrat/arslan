"""Writing seatbelt profiles: the one place Arslan turns paths and permissions into SBPL (SBX-1, v0.1.64).

The profiles Arslan starts processes under are written with this module: commands in and out of
the sandbox (`command_sandbox.profile`, `minimal_profile`), `run_python` and the artifact checks
(`code_sandbox.computation_profile`), installed MCP servers (`capability_sandbox.profile`) and
`ssh_run` (`ssh_exec.ssh_profile`). Each of those keeps its own rules; SBX-1 moved how they are
written here without changing a byte of what they produce, and SBX-1b changed how a path is spelt
(below). SBX-2 adds the default-deny base that SBX-3 and SBX-4 move them onto
(docs/plans/0164/SBX-sandbox.md). One text is still written by hand: `code_sandbox._SEATBELT_PROFILE`,
which no product caller reaches and SBX-4 deletes. (`command_sandbox.available()` starts the real
commands profile since SBX-3.)

What every profile relies on:

- Rule order matters for path and TCP rules alike (deny after allow), but for TCP port denies
  it is not enough: survival also depends on the exact set of TCP allows, not only on `*:*`.
  Proxy and port-22 are measured to hold on macOS 26.6.2 only with their allow pairs as built
  below. See #574, comment 6543830944. Compile checks complement real-kernel checks.
- Rules match real paths, so callers resolve every path before it goes in (`real`).
- A path is written as an SBPL string (`sbpl_string`): its own UTF-8, with `\\` and `"` escaped, so a
  folder name cannot add rules, and control characters as `\\xHH`. sandbox-exec decodes those but
  not `\\uXXXX`, which is how `json.dumps` wrote every non-ASCII character until SBX-1b: a rule on a
  CJK- or accent-named path then landed on a path that does not exist, so a deny on such a folder
  missed and an allow on one refused (②Main's review of #471; measured on macOS 26.6.2). Unicode
  normalization does not matter: a rule written in NFC matches a folder stored in NFD, and the other
  way round (measured).
- A rule without a filter matches everything: `(allow file-read*)` opens every file. So `allow_paths`
  leaves the rule out when its list is empty, instead of writing it bare. A deny is written as the
  profile asks: over no paths it denies everything, which fails closed.
"""
from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from enum import Enum
from pathlib import Path


def real(path) -> Path:
    """`path` with `~` expanded and every link resolved: what seatbelt compares against."""
    return Path(os.path.realpath(os.path.expanduser(str(path))))


def sbpl_string(text: str) -> str:
    """`text` as an SBPL string literal: its own characters, `\\` and `"` escaped, control characters
    (below U+0020, and U+007F) as `\\xHH`. For printable ASCII this is exactly what `json.dumps` wrote."""
    out = []
    for ch in text:
        if ch in ('\\', '"'):
            out.append("\\" + ch)
        elif ch < " " or ch == "\x7f":
            out.append(f"\\x{ord(ch):02x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def subpath(path) -> str:
    """The path and everything under it."""
    return f"(subpath {sbpl_string(str(path))})"


def literal(path) -> str:
    """Exactly this path."""
    return f"(literal {sbpl_string(str(path))})"


def file_or_folder(path: Path) -> str:
    """`literal` for an existing file, `subpath` for a folder or a path that does not exist (yet)."""
    return literal(path) if path.is_file() else subpath(path)


def regex(pattern: str) -> str:
    """Paths matching `pattern`, which is one of Arslan's own constants, never a path from outside (an SBPL
    regex literal has no escape for `"`)."""
    if '"' in pattern:
        raise ValueError("an SBPL regex cannot hold a double quote")
    return f'(regex #"{pattern}")'


def remote_tcp(host: str, port: int) -> str:
    """An outbound TCP destination. The host must be `*` or `localhost`: sandbox-exec rejects an
    address (measured 2026-08-21, `ssh_exec`)."""
    return f"(remote tcp {sbpl_string(f'{host}:{port}')})"


class Profile:
    """Emit rules in the supplied order; source order is not an enforcement guarantee."""

    def __init__(self, default: str):
        self._lines = ["(version 1)", f"({default} default)"]

    def allow(self, operations: str, *filters: str) -> None:
        self._lines.append(_rule("allow", operations, filters))

    def deny(self, operations: str, *filters: str) -> None:
        self._lines.append(_rule("deny", operations, filters))

    def allow_paths(self, operations: str, paths: Iterable, kind: Callable[[Path], str] = subpath) -> None:
        """One allow rule over `paths`; none at all when there are none."""
        filters = [kind(path) for path in paths]
        if filters:
            self.allow(operations, *filters)

    def text(self) -> str:
        return "\n".join(self._lines) + "\n"


def _rule(verb: str, operations: str, filters: tuple[str, ...]) -> str:
    return "(" + " ".join((verb, operations, *filters)) + ")"


class NetworkMode(str, Enum):
    NONE = "none"
    PROXY = "proxy"
    ANY_DECLARED = "any-declared"
    PORT_22 = "port-22"


# No service has measurement evidence yet. SBX-M may add exact names, each with
# its corpus id, in a reviewed follow-up. In particular, preference reads do not
# imply permission to contact cfprefsd. Never import a system profile: its grants
# can change independently of this policy.
SYSTEM_MACH_SERVICES: tuple[str, ...] = ()
SYSTEM_UNIX_SOCKETS: tuple[str, ...] = ()


def default_deny_profile(
    writable: Iterable[Path] = (),
    protected: Iterable[Path] = (),
    *,
    readable: Iterable[Path] | None = None,
    closed: Iterable[Path] = (),
    network: NetworkMode = NetworkMode.NONE,
    proxy_port: int | None = None,
    denied_ports: Iterable[int] = (),
    ipc_prefix: str | None = None,
) -> str:
    """SBX-2's candidate preset; no product entry point uses it yet.

    ``readable=None`` permits broad reads; an explicit list narrows reads for
    computation callers. Closed and protected paths override every grant.
    A caller supplies a fresh, unguessable ``/arslan-<16 hex>-`` IPC namespace
    per run; omitting it permits no POSIX IPC. This is name isolation, not an
    ownership check. Do not give two runs the same prefix.

    Network grants are TCP only. Unix sockets are a separate exact allowlist;
    online modes allow outbound localhost connections. Proxy and port-22 exclude
    supplied Arslan listener ports; any-declared rejects nonempty denied_ports
    because Seatbelt cannot reliably enforce them alongside its wildcard grant.
    Port-22 also rejects excluding port 22: its non-localhost allow covers that port.
    All modes deny binds/listens: Seatbelt's localhost bind filter also permits
    wildcard binds. Restoring dev servers requires a
    card decision before SBX-3 wiring. Offline also denies Unix sockets.
    """
    network = NetworkMode(network)
    denied_ports = tuple(denied_ports)
    for port in (*denied_ports, *((proxy_port,) if proxy_port is not None else ())):
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("ports must be integers from 1 to 65535")
    if network == NetworkMode.ANY_DECLARED and denied_ports:
        raise ValueError("any-declared cannot enforce denied_ports; use proxy, port-22, or none")
    if network == NetworkMode.PORT_22 and 22 in denied_ports:
        raise ValueError("port-22 cannot exclude port 22; use proxy or none")
    if network == NetworkMode.PROXY and proxy_port is None:
        raise ValueError("proxy mode requires a proxy port")
    if network != NetworkMode.PROXY and proxy_port is not None:
        raise ValueError("proxy port requires proxy mode")
    if ipc_prefix is not None and re.fullmatch(r"/arslan-[0-9a-f]{16}-", ipc_prefix) is None:
        raise ValueError("IPC prefix must be /arslan-<16 lowercase hex digits>-")

    rules = Profile("deny")
    rules.allow("process-exec process-fork")
    rules.allow("signal", "(target same-sandbox)")
    rules.allow("process-info*", "(target self)")
    rules.allow("sysctl-read")
    rules.allow("user-preference-read")
    if readable is None:
        rules.allow("file-read* file-map-executable")
    else:
        rules.allow("file-read-metadata")
        rules.allow_paths("file-read* file-map-executable", map(real, readable), file_or_folder)
    rules.allow_paths("file-write*", map(real, writable), file_or_folder)

    devices = [literal(p) for p in ("/dev/null", "/dev/zero", "/dev/tty", "/dev/ptmx",
                                    "/dev/stdout", "/dev/stderr")]
    devices += [subpath("/dev/fd"), '(regex #"^/dev/ttys[0-9]+$")']
    rules.allow("file-read* file-write-data", *devices)
    rules.allow("pseudo-tty")
    rules.allow("file-ioctl", literal("/dev/tty"), literal("/dev/ptmx"),
                '(regex #"^/dev/ttys[0-9]+$")')
    if ipc_prefix is not None:
        rules.allow("ipc-posix-shm* ipc-posix-sem*",
                    f"(ipc-posix-name-prefix {sbpl_string(ipc_prefix)})")
    if SYSTEM_MACH_SERVICES:
        rules.allow("mach-lookup", *(f"(global-name {sbpl_string(n)})" for n in SYSTEM_MACH_SERVICES))
    if network != NetworkMode.NONE:
        rules.allow_paths("network-outbound", map(real, SYSTEM_UNIX_SOCKETS), literal)
        rules.allow("network-outbound", '(remote tcp "localhost:*")')
        if network == NetworkMode.PROXY:
            # Load-bearing with localhost:*: removing this can drop TCP denies.
            # https://github.com/mirzatghayrat/arslan/pull/570#issuecomment-6538778801
            rules.allow("network-outbound", remote_tcp("localhost", proxy_port))
        elif network == NetworkMode.ANY_DECLARED:
            rules.allow("network-outbound", '(remote tcp "*:*")')
        elif network == NetworkMode.PORT_22:
            # Load-bearing with localhost:*: removing this can drop TCP denies.
            # https://github.com/mirzatghayrat/arslan/pull/570#issuecomment-6538778801
            rules.allow("network-outbound", remote_tcp("*", 22))
        for port in sorted(set(denied_ports)):
            rules.deny("network-outbound", remote_tcp("localhost", port))
    # Explicit denials document boundaries that must survive future additions.
    rules.deny("network-bind network-inbound")
    rules.deny("appleevent-send")
    rules.deny("user-preference-write")
    if network == NetworkMode.NONE:
        rules.deny("network*")
    for paths in (closed, protected):
        filters = [file_or_folder(real(p)) for p in paths]
        if filters:
            rules.deny("file-read* file-write* file-map-executable", *filters)
            rules.deny("network-outbound", *filters)
    return rules.text()

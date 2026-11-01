"""The sandbox run_command runs in (0.1.51 P3; SBX-3 v0.1.64).

macOS seatbelt. Since SBX-3 a command runs on SBX-2's default-deny base (`sandbox_profile.default_deny_profile`):
it may write only to the working folder, its run's temp and the tool caches; it reaches only the listed system
services, sockets and devices; it can't listen (the user's D1, 2026-11-01); and it can neither read nor write
the user's credentials, other apps' data and Arslan's own data and keys. Reading elsewhere and running programs
stay open. Online, outbound TCP goes to any host with DNS until SBX-6's proxy (the user's D2); offline, no network.
`profile()` below is the pre-SBX-3 allow-default text, kept only for the harness's historical baseline.

Seatbelt applies the LAST matching rule (measured 2026-10-03): the protected
paths come last, so they stay closed even inside a writable folder. It matches
real paths, so every path is resolved first, and written as an SBPL string so a
folder name cannot inject rules. The text is written with `sandbox_profile` (SBX-1).

A Unix socket is reached with connect(), which the file rule does not cover
(measured 2026-10-03: a sandboxed python3 connected to a 0600 socket inside a
protected folder). So every protected path is also closed to network-outbound,
which for a path means exactly that: connecting to a socket under it. 0.1.53's
Arslan Hands listens in such a folder.

0.1.59: while "Desktop, Documents, Downloads" is off in Settings, those folders are closed too
(`closed`), except the working folder and the project folders kept inside them (`reopen_*`).
Measured on this Mac (2026-10-10): a deny on a folder followed by an allow on a folder inside it
holds; the closed folder stays closed through /System/Volumes/Data/… and through a symlink; listing
its parent still shows its name. Before, the toggle closed only the file tools — a question from
the iPhone made Arslan scan the real ~/Downloads with ls/find/python while it was off.

Leaving the sandbox is always a click (see tool_loop): the model asks up front,
or a stopped command is offered a re-run, or the user answered such a card "in this
conversation" — that last one is a stored grant (`outside` / `*`, S4a: `permissions`), not held here.
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from server.services.sandbox_profile import (NetworkMode, Profile, default_deny_profile, file_or_folder, literal,
                                             real as _real, regex, subpath)

_SANDBOX_EXEC = "/usr/bin/sandbox-exec"
_available: bool | None = None

# strerror(EPERM): what seatbelt returns for a denied file operation, and what
# sandbox-exec prints when it cannot start inside another sandbox.
_DENIED = re.compile(r"operation not permitted", re.I)


# SBX-3 §1b: why a root is writable. The classifier (CLS) reads only IN_SCOPE: its "yes" covers effects inside
# the sandbox's writable area, which is the work folder plus, with SBX-3's private TMPDIR, the run's own temp.
IN_SCOPE, SHARED_CACHE, DEVICE = "in_scope", "shared_cache", "device"


@dataclass(frozen=True)
class Root:
    """A place a sandboxed command may write, and why (§1b). `path` is resolved. `match` says how the profile
    names it: a file or a folder by what is on disk ("auto"), or exactly ("literal"), with everything under it
    ("subpath"), or as a regex over paths ("regex", the pty devices)."""
    path: str
    tag: str
    match: str = "auto"

    def filter(self) -> str:
        if self.match == "regex":
            return regex(self.path)
        return {"literal": literal, "subpath": subpath}.get(self.match, file_or_folder)(Path(self.path))


# SBX-3 §1: the devices a command may write, instead of all of /dev. The null and zero devices, the terminal,
# the descriptors (/dev/stdout and /dev/stderr point into /dev/fd), and ptys for tools that open one: the
# master /dev/ptmx and the /dev/ttysNNN it hands out. SBX-M (#592) ran the corpus on SBX-2's base, which has this
# list, and none of the rows that fail there alone is put down to a device, so /dev/dtracehelper stays out.
_DEVICES = (Root("/dev/null", DEVICE, "literal"), Root("/dev/zero", DEVICE, "literal"),
            Root("/dev/tty", DEVICE, "literal"), Root("/dev/ptmx", DEVICE, "literal"),
            Root("/dev/fd", DEVICE, "subpath"), Root(r"^/dev/ttys[0-9]+$", DEVICE, "regex"))


def writable_roots(workspace: Path, temp: Path | None = None, cache: Path | None = None) -> list[Root]:
    """Where a command in `workspace` may write, tagged (§1b). Temp is the run's own folder (`run_temp`, §1a),
    in scope like the work folder; no longer the shared per-user /var/folders/… parent (with the cache C),
    /private/tmp or /private/var/tmp. A tool that needs one of those gets a re-run card. SBX-M (#592) names none
    to reopen: a hardcoded /tmp is a cost that stands (§1a), and the Darwin temp and cache rows fail on every
    base, so they wait for a probe fix (Codex). SBX-5 (§1c): the user's shared caches are read-only now
    (`shared_caches`); the one cache a command writes is Arslan's own for commands (`run_temp.cache`), which its
    tools are pointed at (`CACHE_ENV`)."""
    from server.services import run_temp
    own = _real(run_temp.cache("commands") if cache is None else cache)
    scope = [_real(workspace), *([_real(temp)] if temp is not None else [])]
    return [*(Root(str(p), IN_SCOPE) for p in scope), Root(str(own), SHARED_CACHE), *_DEVICES]


# SBX-5 §1c: the user's caches, read-only to every sandboxed preset. A tampered package written there would be
# installed later by an unsandboxed process (a hand-added MCP server through npx, the user's own terminal).
_SHARED_CACHES = ("Library/Caches", ".cache", ".npm")

#: The variables that point a tool's cache at a preset's own folder (§1c, ②Main).
CACHE_ENV = ("npm_config_cache", "PIP_CACHE_DIR", "UV_CACHE_DIR", "XDG_CACHE_HOME", "GOCACHE")


def shared_caches() -> list[Path]:
    return _resolved(Path.home() / name for name in _SHARED_CACHES)


def _private_folder(path: Path) -> None:
    """Make `path` a 0700 folder of ours, or refuse one that is already there and isn't (a link, a file, or a
    folder someone else owns): a cache another account prepared could hand a tool its packages (#5a review)."""
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise OSError(f"refusing a cache folder that isn't a folder of ours: {path}")
    if stat.S_IMODE(info.st_mode) & 0o077:
        os.chmod(path, 0o700)


def cache_environment(folder: Path) -> dict[str, str]:
    """The environment that sends a preset's tools to `folder` instead of the user's caches. `folder` and its
    parent are made 0700 and must be ours (`_private_folder`); OSError otherwise."""
    _private_folder(folder.parent)
    _private_folder(folder)
    return {name: str(folder / name.lower()) for name in CACHE_ENV}


#: CAP6b: the plugin folder, which CAP7 fixes. SBX takes it as a parameter so CAP7 does not edit profiles.
PLUGIN_FOLDER: Path | None = None


def cap6b_folders(plugin_folder: Path | None = None) -> list[Path]:
    """CAP6b: the skill and plugin folders, never written by the model (and in the commands preset and the outside
    floor never read: `SKILL.md` goes through `read_skill`, scripts through `run_python`). Resolved, so a
    `~/.agents` that links into a writable folder is closed by its real path. Arslan's data folder, which holds
    the MCP config, is already protected."""
    plugin = PLUGIN_FOLDER if plugin_folder is None else plugin_folder
    return _resolved([Path.home() / ".agents" / "skills", *([plugin] if plugin is not None else [])])


# Kept for SBX-2's harness only: its `legacy-commands` base rebuilds main's commands profile from these as the
# historical baseline (tests/server/sbx/harness.py), and `profile()` with no devices and nothing in
# `deny_write_after_roots` writes main's text byte for byte. No product path calls them
# (test_sbx3a_commands_profile.py pins that). DELETE-BY: v0.1.64, together with that adapter, in Codex's follow-up to
# SBX-3a that removes it (card, "SBX-2 harness retention").
# SBX-M has recorded the baseline (#592), so the adapter may go now; the harness is Codex's
# (docs/plans/0164/SBX-sandbox.md, "SBX-2 harness retention").
_CS_DARWIN_USER_TEMP_DIR = 65537      # <unistd.h>; Python's os.confstr has no name for it


def _darwin_user_dir() -> Path | None:
    try:
        temp = os.confstr(_CS_DARWIN_USER_TEMP_DIR)
    except (ValueError, OSError):
        return None
    return _real(temp).parent if temp else None


def temp_roots() -> list[Path]:
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


def in_scope(path, roots: list[Root]) -> bool:
    """Whether `path`, resolved the way seatbelt matches it, is inside an in-scope root (§1b): a link in the work
    folder that points elsewhere is judged by where it points."""
    return _inside(_real(path), [Path(r.path) for r in roots if r.tag == IN_SCOPE])


def _resolved(paths) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        r = _real(p)
        if r not in out:
            out.append(r)
    return out


def arslan_protected() -> list[Path]:
    """Arslan's own data, keys and Hands' folder (S2a-1). The minimal profile for commands run outside
    the sandbox would close these too (piece 4, held for the user's decision: any seatbelt wrapper
    blocks Apple Events, measured 2026-10-20)."""
    from server import config
    from server.services import hands_client
    home = Path.home()
    return _resolved([config.data_dir(), home / "Library" / "Application Support" / "Arslan", home / ".arslan",
                      home / ".arslan-updater.key", home / "arslan-signing-backup",
                      # 0.1.53: Arslan Hands' socket, token and state (it holds Accessibility).
                      hands_client.folder()])


# S2a-1: the user's credentials and browser profiles. Closed inside the sandbox; a command the user
# lets out of it (ssh, git push, gh, aws) needs them, so they are not part of `arslan_protected`.
_SECRETS = (".ssh", "Library/Keychains", ".aws", ".config/gcloud", ".kube", ".docker/config.json", ".netrc",
            ".npmrc", ".pypirc", ".config/gh", ".git-credentials", ".gnupg", ".azure",
            "Library/Application Support/Google/Chrome", "Library/Application Support/Firefox",
            "Library/Application Support/BraveSoftware", "Library/Application Support/Microsoft Edge",
            "Library/Application Support/Arc", "Library/Safari", "Library/Cookies")


def user_secrets() -> list[Path]:
    ours = arslan_protected()
    return [p for p in _resolved(Path.home() / name for name in _SECRETS) if p not in ours]


def default_protected() -> list[Path]:
    """Never readable or writable from a sandboxed command, whatever else is allowed: Arslan's own
    paths and the user's secrets."""
    return [*arslan_protected(), *user_secrets()]


# SBX-3 §1 (the user's Q3, 2026-10-28): other apps' private data. Commands inherit Arslan's TCC grants, so
# with Full Disk Access open reads would reach these. They are closed to reads and writes the way
# Desktop/Documents/Downloads are while that setting is off (`closed`), except that these are always closed.
# Safari's data is a protected path already (`_SECRETS`). SBX-M didn't measure these folders (#592: the corpus
# leaves the final closed paths to SBX-3); that they are refused is SBX-3p's to test (Codex).
_APP_DATA = ("Library/Mail", "Library/Containers/com.apple.mail", "Library/Messages",
             "Library/Containers/com.apple.MobileSMS", "Pictures/Photos Library.photoslibrary", "Library/Photos",
             "Library/Containers/com.apple.Photos")


def app_data() -> list[Path]:
    protected = default_protected()
    return [p for p in _resolved(Path.home() / name for name in _APP_DATA) if p not in protected]


def _inside(path: Path, folders: list[Path]) -> bool:
    return any(path == folder or folder in path.parents for folder in folders)


def profile(writable: list[Path], protected: list[Path], *, offline: bool = False,
            closed: list[Path] = (), readable: list[Path] = (), copies: list[Path] = (),
            devices: tuple[str, ...] = (), deny_write_after_roots: list[Path] = ()) -> str:
    """The SBPL text. Order matters: deny all writes, re-allow the writable
    folders and `devices` (SBPL filters, SBX-3), close `closed` (0.1.59: the user's
    Desktop/Documents/Downloads while they are off; SBX-3: other apps' data) and
    re-open what lives inside them — writable folders read and write, `readable`
    ones (project folders) read only — then deny writes to `deny_write_after_roots`
    (SBX-3 §e: HR fills it), then close the protected paths (last rule wins) — to
    files and to sockets alike."""
    # S2a-1: no Apple Events from the sandbox. On macOS 26 any seatbelt wrapper already makes them
    # fail (-10004, measured 2026-10-20); the rule makes it explicit (they fail with -600) and holds
    # wherever that is not so. Nothing lifts it: an approved osascript cannot work inside seatbelt.
    rules = Profile("allow")
    rules.deny("appleevent-send")
    if offline:
        rules.deny("network*")
    rules.deny("file-write*", subpath("/"))
    writable = [_real(p) for p in writable]
    rules.allow_paths("file-write*", writable, file_or_folder)
    if devices:
        rules.allow("file-write*", *devices)
    shut = [_real(p) for p in closed]
    if shut:
        rules.deny("file-read* file-write*", *map(file_or_folder, shut))
        open_rw = [p for p in writable if _inside(p, shut)]
        open_r = [p for p in map(_real, readable) if _inside(p, shut) and p not in open_rw]
        rules.allow_paths("file-read* file-write*", open_rw, file_or_folder)
        rules.allow_paths("file-read*", open_r, file_or_folder)
    later = [file_or_folder(_real(p)) for p in deny_write_after_roots]
    if later:
        rules.deny("file-write*", *later)
    shut_to_all = [file_or_folder(_real(p)) for p in protected]
    if shut_to_all:
        rules.deny("file-read* file-write*", *shut_to_all)
        rules.deny("network-outbound", *shut_to_all)   # sockets under them
    # S2a-1 piece 5: the saved tool outputs this conversation was given, read-only and one file at
    # a time, after the protected paths (the last rule wins). Never the folder: `ls` stays closed.
    rules.allow_paths("file-read*", map(_real, copies), literal)
    return rules.text()


def commands_profile(workspace: Path, *, temp: Path | None = None, offline: bool = False, closed: list[Path] = (),
                     readable: list[Path] = (), copies: list[Path] = (), network: NetworkMode | None = None,
                     proxy_port: int | None = None, denied_ports: tuple[int, ...] = (),
                     ipc_prefix: str | None = None, cache: Path | None = None, peer_cache: Path | None = None,
                     plugin_folder: Path | None = None) -> str:
    """The profile a command in `workspace` runs under, with `temp` its run's folder, and the one `available()`
    starts (SBX-3). It is SBX-2's default-deny base (`default_deny_profile`): only the listed services, sockets,
    devices and IPC names, no listening (the user's D1, 2026-11-01), and writes only to the writable roots.

    Network (the user's D2, 2026-11-01): offline is NONE; online is ANY_DECLARED, outbound TCP to any host plus
    DNS, with no `denied_ports` (that mode can't hold them), so loopback to Arslan's own ports stays open as on
    v0.1.63. DELETE-BY: v0.1.64, when SBX-6's proxy lands: online is then PROXY with Arslan's ports denied.
    `network`, `proxy_port` and `denied_ports` go to the base as given (SBX-3p's harness passes them).
    `ipc_prefix` is None for product runs, which permits no POSIX IPC (gate 4, option b: a stock
    multiprocessing Pool is refused, SBX-measurement.md); the harness passes a per-run one to test the rule."""
    roots = writable_roots(workspace, temp, cache)
    writable = [Path(r.path) for r in roots if r.tag != DEVICE]   # the base writes its own device list
    # SBX-5: the CAP6b folders close like a protected path (no read, no write, last).
    protected = [*default_protected(), *cap6b_folders(plugin_folder)]
    # An MCP server's cache is under its folder, in Arslan's data folder, which is protected here already.
    shut = _resolved([*closed, *app_data(), *([peer_cache] if peer_cache is not None else [])])
    if network is None:
        network = NetworkMode.NONE if offline else NetworkMode.ANY_DECLARED
    text = default_deny_profile(writable, protected, closed=shut, network=network, proxy_port=proxy_port,
                                denied_ports=denied_ports, ipc_prefix=ipc_prefix)
    # The base closes `closed` and then `protected` last, over every grant. Reopen what lives inside a closed
    # folder (0.1.59: the work folder read and write, project folders read only), close the protected paths
    # again so a reopened folder can't uncover them, then let the saved copies be read (S2a-1 piece 5).
    # Sockets stay closed under all of them: the base allows only its listed sockets.
    after = Profile("deny")
    open_rw = [p for p in map(_real, writable) if _inside(p, shut)]
    open_r = [p for p in map(_real, readable) if _inside(p, shut) and p not in open_rw]
    after.allow_paths("file-read* file-write* file-map-executable", open_rw, file_or_folder)
    after.allow_paths("file-read* file-map-executable", open_r, file_or_folder)
    if open_rw or open_r:
        after.deny("file-read* file-write* file-map-executable", *(file_or_folder(_real(p)) for p in protected))
    # SBX-5 §1c: the user's caches stay readable and are never written, even inside a writable work folder (~).
    after.deny("file-write*", *(file_or_folder(p) for p in shared_caches()))
    after.allow_paths("file-read*", map(_real, copies), literal)
    return text + "".join(after.text().splitlines(True)[2:])        # its rules, without a second header


def wrapper(workspace: Path, *, temp: Path | None = None, offline: bool = False, closed: list[Path] = (),
            readable: list[Path] = (), copies: list[Path] = ()) -> list[str] | None:
    """The sandbox-exec prefix for a command in `workspace`, or None where seatbelt
    is missing or cannot start (then the caller runs as before and says so)."""
    if not available():
        return None
    return [_SANDBOX_EXEC, "-p", commands_profile(workspace, temp=temp, offline=offline, closed=closed,
                                                  readable=readable, copies=copies)]


def minimal_profile(*, offline: bool = False, copies: list[Path] = (), plugin_folder: Path | None = None) -> str:
    """S2a-1 piece 4 (decision U11): what a command the user let out of the sandbox, or one run with
    the sandbox off, still may not do — send Apple Events, reach the network when offline, read or
    write Arslan's own data, keys and Hands' folder (files and sockets). The user's secrets stay open:
    ssh, git push, gh and aws need them out here. The saved copies this conversation was given stay
    readable, file by file (piece 5). An approved plain osascript or `shortcuts run` runs with no
    wrapper at all (`task_service.unwrapped_once`): any seatbelt wrapper blocks Apple Events."""
    rules = Profile("allow")
    rules.deny("appleevent-send")
    if offline:
        rules.deny("network*")
    ours = [file_or_folder(p) for p in arslan_protected()]
    rules.deny("file-read* file-write*", *ours)
    rules.deny("network-outbound", *ours)
    # SBX-5 CAP6b: the skill and plugin folders are closed outside too (CAP6a); the user's secrets stay open.
    rules.deny("file-read* file-write*", *(file_or_folder(p) for p in cap6b_folders(plugin_folder)))
    rules.allow_paths("file-read*", map(_real, copies), literal)
    return rules.text()


def outside_wrapper(*, offline: bool = False, copies: list[Path] = ()) -> list[str] | None:
    """The sandbox-exec prefix with the minimal profile, or None where seatbelt cannot start (then a
    command outside the sandbox runs as before)."""
    if not available():
        return None
    return ["/usr/bin/sandbox-exec", "-p", minimal_profile(offline=offline, copies=copies)]


def available() -> bool:
    """Probed once per process: present, and able to start here (it cannot nest
    inside another sandbox — Arslan under the bench's sandbox-exec, for one).
    SBX-3: the probe starts the real commands profile, for a scratch working folder,
    so a profile this macOS cannot start reads as unavailable (today's card path)
    instead of failing every command."""
    global _available
    if _available is None:
        ok = False
        if sys.platform == "darwin" and Path(_SANDBOX_EXEC).exists():
            try:
                with tempfile.TemporaryDirectory(prefix="arslan-sandbox-probe-") as scratch:
                    ok = subprocess.run([_SANDBOX_EXEC, "-p", commands_profile(Path(scratch)), "/usr/bin/true"],
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


def refused_outside(result: dict) -> bool:
    """A command under the minimal outside profile that failed with EPERM (piece 4)."""
    return bool(_DENIED.search(f"{result.get('stderr') or ''}\n{result.get('stdout') or ''}"))


def note(workspace: Path, closed: list[Path] = ()) -> str:
    shut = ""
    if closed:
        names = ", ".join(f"~/{p.name}" if p.parent == Path.home() else str(p) for p in closed)
        shut = (f" The user keeps {names} closed (Settings: Desktop, Documents, Downloads is off), so commands "
                "cannot open them either.")
    return ("The sandbox stopped this command: commands may write only inside the working folder "
            f"({workspace}), temp and cache folders, and cannot read ~/.ssh, the keychain or Arslan's data."
            + shut + " If it really needs to work elsewhere, run it again with outside_sandbox: true and a short "
            "why — the user decides with a click. Otherwise tell the user what you needed.")


# ── "for the rest of this conversation" (memory only) ─────────────────────────

def _reset_for_tests() -> None:
    global _available
    _available = None

"""The sandbox run_command runs in (0.1.51 P3).

macOS seatbelt, Codex `workspace-write` shaped: everything is as usual except that
a command may write only to the working folder, temp and tool caches, and can
neither read nor write the user's SSH keys, the keychain files and Arslan's own
data and keys. Reading elsewhere, running programs and the network stay open:
Arslan reads the web with curl, and seatbelt cannot hold a connection to one
host anyway, so nothing is promised about the network.

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
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from server.services.sandbox_profile import Profile, file_or_folder, literal, real as _real, regex, subpath

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
# master /dev/ptmx and the /dev/ttysNNN it hands out. SBX-M confirms the list on a Mac (dtracehelper if needed).
_DEVICES = (Root("/dev/null", DEVICE, "literal"), Root("/dev/zero", DEVICE, "literal"),
            Root("/dev/tty", DEVICE, "literal"), Root("/dev/ptmx", DEVICE, "literal"),
            Root("/dev/fd", DEVICE, "subpath"), Root(r"^/dev/ttys[0-9]+$", DEVICE, "regex"))


def writable_roots(workspace: Path, temp: Path | None = None) -> list[Root]:
    """Where a command in `workspace` may write, tagged (§1b). Temp is the run's own folder (`run_temp`, §1a),
    in scope like the work folder; no longer the shared per-user /var/folders/… parent (with the cache C),
    /private/tmp or /private/var/tmp. A tool that needs one of those gets a re-run card until SBX-M names it
    and only its sub-folder is reopened, as a shared cache. The caches stay writable until SBX-5 (§1c)."""
    home = Path.home()
    shared = [_real(home / "Library" / "Caches"), _real(home / ".cache"), _real(home / ".npm")]
    scope = [_real(workspace), *([_real(temp)] if temp is not None else [])]
    return [*(Root(str(p), IN_SCOPE) for p in scope), *(Root(str(p), SHARED_CACHE) for p in shared), *_DEVICES]


# Kept for SBX-2's harness only: its `legacy-commands` base rebuilds main's commands profile from these as the
# historical baseline (tests/server/sbx/harness.py), and `profile()` with no devices and nothing in
# `deny_write_after_roots` writes main's text byte for byte. No product path calls them
# (test_sbx3_commands.py pins that). DELETE-BY: v0.1.64, together with that adapter, after SBX-M records the
# baseline and before this PR leaves draft (docs/plans/0164/SBX-sandbox.md, "SBX-2 harness retention").
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
# Safari's data is a protected path already (`_SECRETS`). SBX-M confirms the folders on a Mac.
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
                     readable: list[Path] = (), copies: list[Path] = ()) -> str:
    """The profile a command in `workspace` runs under, with `temp` its run's folder, and the one `available()`
    starts (SBX-3)."""
    roots = writable_roots(workspace, temp)
    return profile([Path(r.path) for r in roots if r.tag != DEVICE], default_protected(), offline=offline,
                   closed=[*closed, *app_data()], readable=readable, copies=copies,
                   devices=tuple(r.filter() for r in roots if r.tag == DEVICE))


def wrapper(workspace: Path, *, temp: Path | None = None, offline: bool = False, closed: list[Path] = (),
            readable: list[Path] = (), copies: list[Path] = ()) -> list[str] | None:
    """The sandbox-exec prefix for a command in `workspace`, or None where seatbelt
    is missing or cannot start (then the caller runs as before and says so)."""
    if not available():
        return None
    return [_SANDBOX_EXEC, "-p", commands_profile(workspace, temp=temp, offline=offline, closed=closed,
                                                  readable=readable, copies=copies)]


def minimal_profile(*, offline: bool = False, copies: list[Path] = ()) -> str:
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

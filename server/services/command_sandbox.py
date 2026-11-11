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

Leaving the sandbox is always a click (see tool_loop): the model asks, or the user answered such a card
"in this conversation", which is a stored grant (`outside` / `*`, S4a: `permissions`), not held here.
"""
from __future__ import annotations

import logging
import os
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from server.services import run_later
from server.services.sandbox_profile import (NetworkMode, Profile, default_deny_profile, file_or_folder, literal,
                                             real as _real, regex, subpath)

_SANDBOX_EXEC = "/usr/bin/sandbox-exec"
_TRUST_SERVICE = '(global-name "com.apple.trustd.agent")'   # SBX-6a, the user's setting
_available: bool | None = None
_log = logging.getLogger(__name__)

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
    /private/tmp or /private/var/tmp. A tool that needs one of those is stopped, and the model decides. SBX-M (#592) names none
    to reopen: a hardcoded /tmp is a cost that stands (§1a), and the Darwin temp and cache rows fail on every
    base, so they wait for a probe fix (Codex). SBX-5 (§1c): the user's shared caches are read-only now
    (`shared_caches`); the one cache a command writes is Arslan's own for commands (`run_temp.cache`, or `cache`),
    which its tools are pointed at (`CACHE_ENV`)."""
    from server.services import run_temp
    own = _real(run_temp.cache("commands") if cache is None else cache)
    scope = [_real(workspace), *([_real(temp)] if temp is not None else [])]
    return [*(Root(str(p), IN_SCOPE) for p in scope), Root(str(own), SHARED_CACHE), *_DEVICES]


# SBX-5 §1c: the user's caches, read-only to the commands and MCP presets. A tampered package written there would
# be installed later by an unsandboxed process (a hand-added MCP server through npx, the user's own terminal).
_SHARED_CACHES = ("Library/Caches", ".cache", ".npm")

#: The variables that point a tool's cache at a preset's own folder (§1c). Not measured (SBX-M could not, #592):
#: whether uv and Go honour theirs under the redirect; GOMODCACHE isn't redirected, so ~/go stays as before.
CACHE_ENV = ("npm_config_cache", "PIP_CACHE_DIR", "UV_CACHE_DIR", "XDG_CACHE_HOME", "GOCACHE")


def shared_caches() -> list[Path]:
    return _resolved(Path.home() / name for name in _SHARED_CACHES)


def _private_folder(path: Path) -> None:
    """Make `path` a 0700 folder of ours, or refuse one that is already there and isn't (a link, a file, or a
    folder someone else owns): a cache another account prepared could hand a tool its packages (SBX-5a review)."""
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
    the MCP config, is protected already."""
    return _resolved(cap6b_spellings(plugin_folder))


def cap6b_spellings(plugin_folder: Path | None = None) -> list[Path]:
    """The CAP6b folders as Arslan looks them up, not resolved: a link on the way is held too (`held_ancestors`)."""
    plugin = PLUGIN_FOLDER if plugin_folder is None else plugin_folder
    return [Path.home() / ".agents" / "skills", *([plugin] if plugin is not None else [])]


def held_ancestors(writable, protected, *, planted=(), kept=()) -> list[Path]:
    """SBX-5a (#772 review): the folders between a writable root and a protected path, root included, which the
    profiles deny `file-write*` as literals. A rule on a folder holds its contents but not its parents: a process
    that may write ~ could rename ~/.agents away, skills inside, and use them there. A literal is that one folder
    (rename, removal, mode, making it again, a link put there); creating, writing and removing things inside it
    still work (measured under seatbelt, test_sbx5a_aliases.py).

    `protected` paths count when they exist (nothing to move otherwise, and a missing ~/.config stays makeable).
    `planted` ones (CAP6b) count even when missing, since a folder made or linked where Arslan looks would be read
    as skills, and by their spelling as well as their real path, so a link on the way can't be retargeted. When the
    CAP6b folder itself is a link, that entry is held too (its target is closed as a folder, not reopened).

    Containment goes by `(st_dev, st_ino)` as well as by path (#772 delta review): `realpath` keeps the spelling it
    is given, so a work folder spelt `~/HOME` or in NFD is the same folder as the ~ the protected paths are under.
    A folder that doesn't exist yet is judged by its existing ancestors. Seatbelt matches the folder on disk, so a
    literal in either spelling holds it.

    HR-1 (#813 review 6): `kept` folders (the held run-later folders the walk found, `run_later_folders`) are held
    themselves as well as every folder above them, up to and including the root, when they exist."""
    roots = _resolved(writable)
    ids = {i for i in map(_identity, roots) if i is not None}
    seen: dict[Path, tuple[int, int] | None] = {}
    out: list[Path] = []
    judged: set[Path] = set()           # #813 review 7: membership by set, so the build is linear in `kept`

    def inside(folder: Path) -> bool:
        if any(folder == r or r in folder.parents for r in roots):
            return True
        for f in (folder, *folder.parents):
            if f not in seen:
                seen[f] = _identity(f)
            if seen[f] in ids:
                return True
        return False

    def hold(folder: Path) -> None:
        if folder in judged:
            return
        judged.add(folder)
        if inside(folder):
            out.append(folder)

    for path in [*(_real(p) for p in protected if _real(p).exists()), *(_real(p) for p in planted)]:
        for folder in reversed(path.parents):
            hold(folder)
    for path in planted:
        lexical = Path(os.path.abspath(os.path.expanduser(str(path))))
        for folder in reversed(lexical.parents):
            if folder != folder.parent:
                hold(_real(folder.parent) / folder.name)         # the name itself: a link there, not its target
        entry = _real(lexical.parent) / lexical.name
        if entry.is_symlink():
            hold(entry)                                          # the CAP6b folder is a link: hold the link
    for path in kept:
        folder = _real(path)
        if folder.exists():
            for each in (*reversed(folder.parents), folder):
                hold(each)
    return out


#: Work folders whose last commands-profile walk stopped at a cap (or an unlistable folder): their profile holds the
#: run-later folders by name. `note` says why (⓪Plan, #813 review 6). Keyed by the folder that walk started from and
#: set or cleared only by `commands_profile` (#813 review 7): an MCP server's walk covers its own folder as well, so
#: its outcome says nothing about the work folder's.
_TOO_LARGE: set[Path] = set()
#: #813 review 9: the aliases the last commands-profile walk of a work folder found, for `note`; set the same way.
_ALIASED: dict[Path, tuple[Path, ...]] = {}


def too_large_to_map(workspace: Path) -> bool:
    try:
        return _real(workspace) in _TOO_LARGE
    except OSError:
        return False


def aliases_in(workspace: Path) -> tuple[Path, ...]:
    try:
        return _ALIASED.get(_real(workspace), ())
    except OSError:
        return ()


@dataclass(frozen=True)
class RunLaterHold:
    """What `run_later_folders` found, for a profile."""
    kept: list[Path]                # for `held_ancestors(kept=...)`
    by_name: tuple[str, ...]        # filters to deny `file-write*` over
    complete: bool                  # the walk was complete
    aliases: tuple[Path, ...]       # #813 review 9: held names that link out of their folder
    #: #813 review 10: filters to deny `file-write*` over, the held names at the real path of each held name and held
    #: folder name the walk found as a link (`run_later.link_filters`)
    at_targets: tuple[str, ...] = ()

    @property
    def aliased(self) -> bool:
        """#813 review 9: the profile drops the dependency exemption (`run_later.kernel_filters(aliased=...)`): an
        alias was found, or the walk couldn't finish, so one may be where it didn't look."""
        return bool(self.aliases) or not self.complete


def run_later_folders(folders, *, roots=(), closed=()) -> RunLaterHold:
    """HR-1's ancestor hold (#813 review 6): the held run-later folders that exist under `folders` and `roots` (the
    walk's) and each of `folders`' `core.hooksPath` target, as `run_later.kernel_filters` takes them, for
    `held_ancestors(kept=...)`; and the name filters to deny: inside each private folder the walk didn't list
    (#813 review 8: `closed` and the TCC home folders, `run_later.private_filters`), and everywhere when the walk was
    incomplete (`run_later.folder_filters`). A skipped private folder is kept too, so it and the folders above it
    stay in place and its by-name hold can't be renamed away. #813 review 9: the real paths of the aliases the walk
    found are kept too (a dependency's file a held name links to, and the folders above it, stay in place).
    #813 review 10: so are the real paths of every held name and held folder name the walk found as a link, and the
    held names at them are denied (`run_later.link_filters`: `.vscode -> vsc` holds `vsc/settings.json`).
    A hooksPath that can't be read raises, as in `kernel_filters`."""
    folders, roots = list(folders), list(roots)
    walk = run_later.held_folders([*folders, *roots], roots=roots, closed=closed)
    kept = [*walk.skipped, *walk.folders, *walk.targets]
    for folder in folders:
        target = run_later.hooks_path(folder)
        if target is not None and run_later._is_folder(target):
            kept.append(_real(target))
    by_name = run_later.private_filters(walk.skipped)
    if walk.aliases:
        _log.warning("HR-1: %d run-later name(s) link out of their folder (%s); dependency folders get no exemption "
                     "in this run", len(walk.aliases), ", ".join(map(str, walk.aliases[:5])))
    if not walk.complete:
        _log.warning("HR-1: the held-folder walk stopped at a cap or an unlistable folder; held folders are held by "
                     "name in this run, so a new one (a .git, a first .vscode) can't be made, and dependency folders "
                     "get no exemption")
        by_name = (*by_name, *run_later.folder_filters(folders, roots=roots, aliased=True))
    return RunLaterHold(kept, by_name, walk.complete, walk.aliases, walk.link_filters)


def _identity(path: Path) -> tuple[int, int] | None:
    """`(st_dev, st_ino)` of `path` itself (a link is not followed), or None when it isn't there. Any other error
    (I/O, permission) propagates, so no profile is built (#772 round 3): a root whose identity can't be read would
    otherwise drop out of the comparison and lose its holds. The command or server then doesn't start."""
    try:
        st = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    return st.st_dev, st.st_ino


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
            ".config/rclone", ".rclone.conf", ".s3cfg", ".boto", ".gsutil",
            "Library/Application Support/Google/Chrome", "Library/Application Support/Firefox",
            "Library/Application Support/BraveSoftware", "Library/Application Support/Microsoft Edge",
            "Library/Application Support/Arc", "Library/Safari", "Library/Cookies",
            # Other agents' config, which can hold API keys in MCP entries, its backups and their sign-ins. `codex mcp
            # list` now stops with EPERM here; `codex exec` already did under this profile. A run outside can still read them.
            ".claude.json", ".claude/backups", ".claude/.credentials.json", ".codex/config.toml", ".codex/auth.json")


def user_secrets() -> list[Path]:
    ours = arslan_protected()
    # Backups beside Claude Code's config carry a timestamp in their names, so they're listed for each run: one written
    # while a command runs is closed from the next command on. A regex would reach only the commands' profile, and the
    # file tools, checkpoints and capability sandbox read this list too.
    home = Path.home()
    return [p for p in _resolved([*(home / name for name in _SECRETS), *home.glob(".claude.json.backup*")]) if p not in ours]


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
                     ipc_prefix: str | None = None, bound_ports: list[int] | None = None,
                     system_proxies: list[str] | None = None, trust_service: bool = False,
                     cache: Path | None = None, peer_cache: Path | None = None,
                     plugin_folder: Path | None = None) -> str:
    """The profile a command in `workspace` runs under, with `temp` its run's folder, and the one `available()`
    starts (SBX-3). It is SBX-2's default-deny base (`default_deny_profile`): only the listed services, sockets,
    devices and IPC names, no listening (the user's D1, 2026-11-01), and writes only to the writable roots.

    Network (SBX-6, the user's N-a): offline is NONE; online is PROXY, TCP only to `proxy_port` (the running
    `sandbox_proxy`) and to loopback for dev servers, with no DNS inside. Loopback excludes every port Arslan
    listens on (`bound_ports`, read now when not given) and the system proxies' loopback ports
    (`system_proxies`, likewise), so neither is a way out round the proxy. Online with no proxy port, or with
    Arslan's own ports unknown, is offline: closed, not open. `network` and `proxy_port` go to the base as given, and `denied_ports` adds to the
    excluded ports (SBX-3p's and SBX-6p's harness pass them). `trust_service` (the user's setting
    `sandbox_system_certificates`, default off) grants macOS's certificate trust service in proxy mode only, the
    one thing it adds, as sandbox-runtime's `enableWeakerNetworkIsolation` does: Swift, Xcode's and Go's tools
    check certificates through it, and it fetches certificate data itself, round the proxy.
    `ipc_prefix` is None for product runs, which permits no POSIX IPC (gate 4, option b: a stock
    multiprocessing Pool is refused, SBX-measurement.md); the harness passes a per-run one to test the rule.

    SBX-5: the CAP6b folders (`cap6b_folders`, with `plugin_folder`) close like a protected path, so a work folder
    inside them is not reopened; the user's caches are never written, even inside a writable work folder; the
    one cache written is `cache` (Arslan's commands cache by default), and `peer_cache` is closed when given. An
    MCP server's cache is under its folder, in Arslan's data folder, which is protected here already."""
    roots = writable_roots(workspace, temp, cache)
    writable = [Path(r.path) for r in roots if r.tag != DEVICE]   # the base writes its own device list
    protected = [*default_protected(), *cap6b_folders(plugin_folder)]
    shut = _resolved([*closed, *app_data(), *([peer_cache] if peer_cache is not None else [])])
    if network is None:
        network = NetworkMode.NONE if offline or proxy_port is None else NetworkMode.PROXY
    network = NetworkMode(network)
    if network in (NetworkMode.PROXY, NetworkMode.PORT_22):
        from server.services import sandbox_proxy
        bound = sandbox_proxy.listening_ports() if bound_ports is None else list(bound_ports)
        if bound is None:
            network, proxy_port, denied_ports = NetworkMode.NONE, None, ()
        else:
            system = sandbox_proxy.system_proxies() if system_proxies is None else list(system_proxies)
            denied_ports = tuple(sorted({*sandbox_proxy.excluded_ports(bound, system, proxy_port=proxy_port or 0),
                                         *denied_ports}))
    if network != NetworkMode.PROXY:
        proxy_port = None
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
    # SBX-5a (#772 review): nor are the folders above them moved or replaced, when a writable root holds them.
    # HR-1 (#813 review 6): nor the held run-later folders in the work folder and every folder above them.
    # #813 review 8: the walk never lists the user's closed folders nor the TCC home folders (`closed` is the user's
    # list, before Arslan's own data is added); it holds the held folders inside them by name.
    hold = run_later_folders([workspace], closed=closed)
    (_TOO_LARGE.discard if hold.complete else _TOO_LARGE.add)(_real(workspace))  # this walk's root only (review 7)
    if hold.aliases:                                                             # #813 review 9, for `note`
        _ALIASED[_real(workspace)] = hold.aliases
    else:
        _ALIASED.pop(_real(workspace), None)
    # HR-1: nor the files that make something run later (git hooks and config, editor tasks, agent and package
    # settings, the work folder's core.hooksPath), after every grant and reopen. Raises when hooksPath can't be read.
    # #813 review 9: with no dependency exemption when the walk found an alias (or couldn't finish), and no new link
    # at a held name or held folder name.
    after.deny("file-write-create", *run_later.symlink_filters())
    for filters in run_later.kernel_filters([workspace], aliased=hold.aliased):
        after.deny("file-write*", *filters)
    if hold.at_targets:                     # #813 review 10: the held names at a link's real path
        after.deny("file-write*", *hold.at_targets)
    held = held_ancestors(writable, [*protected, *shut, *shared_caches()], planted=cap6b_spellings(plugin_folder),
                          kept=hold.kept)
    if held:
        after.deny("file-write*", *map(literal, held))
    if hold.by_name:
        after.deny("file-write*", *hold.by_name)
    if trust_service and network == NetworkMode.PROXY:
        after.allow("mach-lookup", _TRUST_SERVICE)
    after.allow_paths("file-read*", map(_real, copies), literal)
    return text + "".join(after.text().splitlines(True)[2:])        # its rules, without a second header


def wrapper(workspace: Path, *, temp: Path | None = None, offline: bool = False, closed: list[Path] = (),
            readable: list[Path] = (), copies: list[Path] = (), proxy_port: int | None = None,
            trust_service: bool = False) -> list[str] | None:
    """The sandbox-exec prefix for a command in `workspace`, or None where seatbelt
    is missing or cannot start (then the caller runs as before and says so)."""
    if not available():
        return None
    return [_SANDBOX_EXEC, "-p", commands_profile(workspace, temp=temp, offline=offline, closed=closed,
                                                  readable=readable, copies=copies, proxy_port=proxy_port,
                                                  trust_service=trust_service)]


def minimal_profile(*, offline: bool = False, copies: list[Path] = (), plugin_folder: Path | None = None,
                    run_later_in: Path | None = None, closed: list[Path] = ()) -> str:
    """S2a-1 piece 4 (decision U11): what a command the user let out of the sandbox, or one run with
    the sandbox off, still may not do — send Apple Events, reach the network when offline, read or
    write Arslan's own data, keys and Hands' folder (files and sockets). The user's secrets stay open:
    ssh, git push, gh and aws need them out here. The saved copies this conversation was given stay
    readable, file by file (piece 5). An approved plain osascript or `shortcuts run` runs with no
    wrapper at all (`task_service.unwrapped_once`): any seatbelt wrapper blocks Apple Events.

    HR-1: `run_later_in` (the work folder) is given when the command left the sandbox under this conversation's
    grant, with no click on its own card: then the files that make something run later stay unwritable, anywhere,
    as inside the sandbox (ruling 2: only that click lifts them). `closed` (the user's closed folders) only tells
    that walk which folders it never lists (#813 review 8); nothing is closed by it out here."""
    rules = Profile("allow")
    rules.deny("appleevent-send")
    if offline:
        rules.deny("network*")
    ours = [file_or_folder(p) for p in arslan_protected()]
    rules.deny("file-read* file-write*", *ours)
    rules.deny("network-outbound", *ours)
    # SBX-5 CAP6b: the skill and plugin folders are closed outside too (CAP6a); the user's secrets stay open.
    rules.deny("file-read* file-write*", *(file_or_folder(p) for p in cap6b_folders(plugin_folder)))
    # SBX-5a (#772 review): everything is writable out here, so every folder above those is held. HR-1 (#813 review
    # 6): with `run_later_in`, so are the held run-later folders in the work folder and every folder above them.
    # Only those (#813 review 7): the walk covers the work folder, so a held folder elsewhere on disk keeps its files
    # held by name (`kernel_filters` below matches at any depth) but is not held in place. #813 review 8: the walk
    # never lists the closed and TCC home folders; the held folders inside them are held by name.
    hold = run_later_folders([run_later_in], closed=closed) if run_later_in is not None else None
    if hold is not None:
        # #813 review 9: no dependency exemption when the walk found an alias, and no new link at a held name.
        rules.deny("file-write-create", *run_later.symlink_filters())
        for filters in run_later.kernel_filters([run_later_in], aliased=hold.aliased):
            rules.deny("file-write*", *filters)
        if hold.at_targets:                 # #813 review 10: the held names at a link's real path
            rules.deny("file-write*", *hold.at_targets)
    held = held_ancestors([Path("/")], arslan_protected(), planted=cap6b_spellings(plugin_folder),
                          kept=hold.kept if hold is not None else ())
    if held:
        rules.deny("file-write*", *map(literal, held))
    if hold is not None and hold.by_name:
        rules.deny("file-write*", *hold.by_name)
    rules.allow_paths("file-read*", map(_real, copies), literal)
    return rules.text()


def outside_wrapper(*, offline: bool = False, copies: list[Path] = (),
                    run_later_in: Path | None = None, closed: list[Path] = ()) -> list[str] | None:
    """The sandbox-exec prefix with the minimal profile, or None where seatbelt cannot start (then a
    command outside the sandbox runs as before)."""
    if not available():
        return None
    return ["/usr/bin/sandbox-exec", "-p", minimal_profile(offline=offline, copies=copies,
                                                           run_later_in=run_later_in, closed=closed)]


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
    """A sandboxed run that failed with EPERM, with a certificate check the closed trust service failed
    (`trust_check_failed`), or on the local proxy's refusal (`proxy_refused`). Heuristic on purpose (Codex does the
    same): a false positive only adds a note the model can ignore."""
    if result.get("sandbox") != "workspace" or result.get("ok") or result.get("exit_code") in (0, None):
        return False
    return (bool(_DENIED.search(f"{result.get('stderr') or ''}\n{result.get('stdout') or ''}"))
            or trust_check_failed(result) or proxy_refused(result))


#: SBX-6a (#668 ruling): the local proxy's refusal of a destination the sandbox keeps closed (`sandbox_proxy.DENIED`).
#: Python prints its reason, and curl without -f its body; curl and git print a refused CONNECT by its code only, which
#: is enough because only that refusal is a 403 from the proxy. A plain-http refusal under curl -f reads like any
#: server's 403 and is not counted.
_PROXY_REFUSED = re.compile(r"Forbidden by Arslan's sandbox: local or non-public destination|"
                            r"CONNECT tunnel failed, response 403\b|Received HTTP code 403 from proxy after CONNECT")


def proxy_refused(result: dict) -> bool:
    """A sandboxed online run whose output carries the local proxy's refusal, whatever the exit code."""
    if result.get("sandbox") != "workspace" or result.get("offline"):
        return False
    return bool(_PROXY_REFUSED.search(f"{result.get('stderr') or ''}\n{result.get('stdout') or ''}"))


#: SBX-6a: the certificate errors a tool prints when Security.framework can't reach the trust service (URLSession
#: and Swift, Xcode's tools, Go on macOS). Their own CA bundles keep curl, Python and git working without it.
_TRUST_FAILED = re.compile(r"NSURLErrorDomain[^\n]*-120[0-6]|NSURLErrorServerCertificate|kCFStreamErrorDomainSSL|"
                           r"errSSL[A-Za-z]+|SecTrust[A-Za-z]*(?:Evaluate|failed)|x509: OSStatus -?\d+|"
                           r"The certificate for this server is invalid", re.I)


def trust_check_failed(result: dict) -> bool:
    """A sandboxed online run whose certificate check failed the way a closed trust service makes it fail."""
    if result.get("sandbox") != "workspace" or result.get("ok") or result.get("offline"):
        return False
    return bool(_TRUST_FAILED.search(f"{result.get('stderr') or ''}\n{result.get('stdout') or ''}"))


#: HR-1 (#813 review 4): what may be a path in a line of git's, in any language. git translates its words (LANG,
#: LC_ALL) but never a path, so a run of characters that are none of white space, quotes, brackets, colons, commas and
#: semicolons, ASCII or full width (git's Chinese messages put a full-width colon right after a path), is a candidate.
_WIDE = "".join(map(chr, (0x2018, 0x2019, 0x201A, 0x201C, 0x201D, 0x201E, 0x00AB, 0x00BB, 0x2039, 0x203A, 0x300C,
                          0x300D, 0x300E, 0x300F, 0xFF08, 0xFF09, 0xFF1A, 0xFF0C, 0xFF1B, 0x3001, 0x3002)))
_PATH_RUN = re.compile("[^\\s'\"`()\\[\\]<>{}:,;" + _WIDE + "]+")
_GIT_WORD = re.compile(r"(?<![\w.-])git(?![\w.-])")


def _is_git(command: str) -> bool:
    """The command runs git, by its text or by the reader's words (quotes removed). Generous on purpose: a word `git`
    anywhere counts, since a false positive only adds a note."""
    if _GIT_WORD.search(command):
        return True
    from server.services import shell_grammar
    reading = shell_grammar.read(command)
    return reading.understood and any(os.path.basename(word) == "git" for words in reading.commands for word in words)


def _held_for_git(token: str, folder: Path, root: Path, target: Path | None) -> bool:
    """`token`, a path git printed (relative to the work folder or the repository's top, or absolute), names a file
    the kernel holds: a run-later name by the work folder's root rule (`.git/config`, `.git/hooks/...` and the work-tree
    names among them), or the work folder's `core.hooksPath` target or a file in it."""
    if run_later.matches(Path(os.path.normpath(os.path.join(folder, token))), root):
        return True
    if target is None:
        return False
    held = os.path.normpath(target)
    return any((path := os.path.normpath(os.path.join(base, token))) == held or path.startswith(held + os.sep)
               for base in (folder, *folder.parents))


def git_refused_paths(result: dict, *, command: str, cwd: Path, hold: bool = False) -> list[str]:
    """HR-1 (#813 reviews 4 and 5): the held paths a git command's refusal lines name, whatever the exit code. A line
    counts only when it carries the EPERM text (`_DENIED`) and names a file the kernel holds from git; on stdout as well
    as stderr (`2>&1`). checkout and switch exit 0 with a held tracked file left as it was; a tracking checkout, `push
    -u` and `--set-upstream-to` exit 0 with the upstream unsaved (`.git/config`). git translates its own words (LANG,
    LC_ALL) but not the path, and macOS doesn't translate strerror, so "Operation not permitted" ends the line in
    every language git speaks. Without that text a held path is only named (a hook printing its own path, a hint, a
    pathspec error, a diff), not refused. In the workspace sandbox, and under the outside floor when it holds them
    (`hold`: let out under this conversation's grant with no click on its own card)."""
    where = result.get("sandbox")
    if not (where == "workspace" or (where == "outside" and hold)):
        return []
    lines = [line for stream in (result.get("stderr") or "", result.get("stdout") or "")
             for line in stream.splitlines() if _DENIED.search(line)]
    tokens = [t for line in lines for t in (run.rstrip(".") for run in _PATH_RUN.findall(line)) if t.strip(".")]
    if not tokens or not _is_git(command):
        return []
    folder = Path(os.path.abspath(cwd))
    try:
        target = run_later.hooks_path(folder)
    except OSError:
        target = None           # only a note: the profile itself failed closed on this already
    root = _real(folder)
    return [token for token in tokens if _held_for_git(token, folder, root, target)]


def git_refused(result: dict, *, command: str, cwd: Path, hold: bool = False) -> bool:
    """`git_refused_paths` names one. Heuristic on purpose: a false positive only adds a note."""
    return bool(git_refused_paths(result, command=command, cwd=cwd, hold=hold))


def git_setup_failed(result: dict, held: list[str]) -> bool:
    """HR-1 (#813 review 5): a git step that failed outright on the repository's own config or hooks only (clone,
    init, `remote add`, a `git config` write): a non-zero exit, and every held path git named is inside a `.git` folder.
    Nothing in the work tree moved, so the ordinary stop note (or, under the floor, the floor's) fits it, not the git
    note's partly updated tree."""
    return bool(held) and not result.get("ok") and all(".git" in Path(token).parts for token in held)


def git_note() -> str:
    """HR-1 (#813 review 4): what the model reads when `git_refused` holds, in the sandbox or under the outside floor,
    at any exit code, except for a setup step that failed outright (`git_setup_failed`). Not the stop note: running it again outside the sandbox doesn't help (the floor holds these files
    too, and only the user's click on that command's own card lifts it), so it ends with the user, not outside_sandbox."""
    return ("Commands can't change files that make something run later (git config or hooks, editor or agent "
            "settings), and git needed to change some of them here, so it didn't update them, even if it exited 0: "
            "an upstream, remote or setting may not have been saved, and a tracked file may have kept its old "
            "content, leaving the work tree partly updated. Check `git status`, tell the user which files or settings "
            "weren't updated, and don't commit over them (a `commit -a` now would undo that change).")


def refused_outside(result: dict) -> bool:
    """A command under the minimal outside profile that failed with EPERM (piece 4)."""
    return bool(_DENIED.search(f"{result.get('stderr') or ''}\n{result.get('stdout') or ''}"))


def note(workspace: Path, closed: list[Path] = (), *, trust: bool = False, proxy: bool = False) -> str:
    shut = ""
    if closed:
        names = ", ".join(f"~/{p.name}" if p.parent == Path.home() else str(p) for p in closed)
        shut = (f" The user keeps {names} closed (Settings: Desktop, Documents, Downloads is off), so commands "
                "cannot open them either.")
    if proxy:
        head = ("The sandbox stopped this command: its network goes through Arslan's proxy, which refused a local or "
                "non-public destination (this Mac, the local network or a link-local address).")
    else:
        head = ("The sandbox stopped this command: commands may write only inside the working folder "
                f"({workspace}), temp and cache folders, and cannot read ~/.ssh, the keychain or Arslan's data." + shut
                # HR-1: for these, not outside_sandbox.
                + " Commands also can't change files that make something run later (git hooks and config, "
                "editor tasks, agent and package settings), even in the working folder: if that is what it "
                "changed, use write_file, which asks the user, or tell the user what to change.")
        if too_large_to_map(workspace):
            # #813 review 7: true under HR-1 alone (git init and clone fail in every sandboxed folder); HR-1b revisits.
            head += (" This working folder is too large to map, so Arslan holds the folders those files live in "
                     "(such as .git and .vscode) by name everywhere in it.")
        if aliased := aliases_in(workspace):
            # #813 review 9: why a dependency's own editor or hook files are refused in this run.
            names = ", ".join(os.path.relpath(p, _real(workspace)) for p in aliased[:5])
            head += (f" Here some of them link out of their folder ({names}), so they are held inside dependency "
                     "folders (node_modules) too in this run.")
    return (head + (" This looks like a certificate check through macOS's trust service, which the sandbox "
                      "closes: the user can allow it in Settings (\"Allow system certificate checks in the "
                      "sandbox\")." if trust else "")
            + " Find a way that works inside it if there is one. If it really has to run outside, run it "
            "again with outside_sandbox: true and a short why, which the user reads before deciding. That starts it "
            "over from the beginning, and whatever it already did stays. Otherwise tell the user what you needed.")


# ── "for the rest of this conversation" (memory only) ─────────────────────────

def _reset_for_tests() -> None:
    global _available
    _available = None

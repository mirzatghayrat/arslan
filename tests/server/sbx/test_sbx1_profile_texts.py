"""SBX-1 (v0.1.64): the exact text of every seatbelt profile Arslan writes, for fixed inputs.

The texts were recorded from main before SBX-1 moved the profiles onto `sandbox_profile`, and
this file passes on both. Later SBX PRs that change a profile change its text here, so the
change is visible line by line in review.

Every input path goes through `A`, a link to the test's folder, so the texts also pin that each
profile resolves what it is given. The test's folder, resolved, is written as <T>.

The pre-SBX-3 commands text is gone (v0.1.64); the commands profile is SBX-2's base, pinned by
`default-deny.sb` (test_sbx2_profile.py), plus the rules test_sbx3a_commands_profile.py writes out.
"""
import os
from pathlib import Path

import pytest

from server.services import capability_sandbox, code_sandbox, command_sandbox, ssh_exec
from tests.server.test_hr1_run_later import RUN_LATER_TEXT     # HR-1's denies, written out once there


@pytest.fixture
def T(tmp_path):
    """The test's folder, with the files, folders and links the profiles below are given."""
    for folder in ("ws", "closed/ws", "closed/proj", "other", "prot", "data", "granted", "runtimes", "mcp",
                   "work", "refs", "py/bin", "py/lib", "venv/bin", "venv/lib"):
        (tmp_path / folder).mkdir(parents=True)
    for file in ("notes.txt", "prot.key", "updater.key", "copy.txt", "py/bin/python3"):
        (tmp_path / file).write_text("x")
    (tmp_path / "link").symlink_to(tmp_path / "ws")
    (tmp_path / "link-granted").symlink_to(tmp_path / "granted")
    (tmp_path / "venv/bin/python").symlink_to(tmp_path / "py/bin/python3")
    return tmp_path


@pytest.fixture(autouse=True)
def _fixed_home_and_caches(T, monkeypatch):
    """SBX-5: the profiles now name the user's caches and CAP6b folders (under ~) and Arslan's commands cache
    (next to the runs' root): fixed under <T>, so the texts don't depend on this machine."""
    from server.services import run_temp
    monkeypatch.setattr(Path, "home", lambda: Path(os.path.realpath(T)) / "home")
    monkeypatch.setattr(run_temp, "cache", lambda preset: Path(os.path.realpath(T)) / f"cache-{preset}")


@pytest.fixture
def A(T):
    """The way in: a link to the test's folder (inside it, so a path not resolved reads <T>/alias/…)."""
    alias = Path(os.path.realpath(T)) / "alias"
    alias.symlink_to(os.path.realpath(T))
    return alias


def _shown(text: str, T: Path) -> str:
    return text.replace(os.path.realpath(T), "<T>")


def test_outside_floor(T, A, monkeypatch):
    # arslan_protected() returns resolved paths; the floor writes them as given.
    ours = [Path(os.path.realpath(T / "data")), Path(os.path.realpath(T / "updater.key"))]
    monkeypatch.setattr(command_sandbox, "arslan_protected", lambda: ours)
    # SBX-5a: every folder above them is held (`held_ancestors`, from / down: everything is writable out here).
    held = _shown(_held(T, "home", "home/.agents"), T)
    assert _shown(command_sandbox.minimal_profile(offline=True, copies=[A / "copy.txt"]), T) == f"""\
(version 1)
(allow default)
(deny appleevent-send)
(deny network*)
(deny file-read* file-write* (subpath "<T>/data") (literal "<T>/updater.key"))
(deny network-outbound (subpath "<T>/data") (literal "<T>/updater.key"))
(deny file-read* file-write* (subpath "<T>/home/.agents/skills"))
{held}
(allow file-read* (literal "<T>/copy.txt"))
"""
    assert _shown(command_sandbox.minimal_profile(), T) == f"""\
(version 1)
(allow default)
(deny appleevent-send)
(deny file-read* file-write* (subpath "<T>/data") (literal "<T>/updater.key"))
(deny network-outbound (subpath "<T>/data") (literal "<T>/updater.key"))
(deny file-read* file-write* (subpath "<T>/home/.agents/skills"))
{held}
"""
    # SBX-5 CAP6b: the plugin folder, once CAP7 names it, closes with the skills.
    assert ('(deny file-read* file-write* (subpath "<T>/home/.agents/skills") (subpath "<T>/plugins"))\n'
            in _shown(command_sandbox.minimal_profile(plugin_folder=A / "plugins"), T))


def _held(T: Path, *below: str) -> str:
    """The held-ancestors rule over / down to <T>, then `below` under <T>."""
    real = Path(os.path.realpath(T))
    chain = [*reversed(real.parents), real, *(real / name for name in below)]
    return "(deny file-write* " + " ".join(f'(literal "{p}")' for p in chain) + ")"


def _between_system_and_usr(T: Path) -> None:
    # computation_profile sorts its read paths; the expected texts put <T> between /System and /usr,
    # which holds for the temp roots CI and macOS use (/home/…, /private/var/…, /tmp/…).
    assert Path("/System") < Path(os.path.realpath(T)) < Path("/usr"), os.path.realpath(T)


def test_run_python_and_artifact_checks(T, A):
    _between_system_and_usr(T)
    python = os.path.join(os.path.realpath(T), "py/bin/python3")
    text = code_sandbox.computation_profile(python, A / "work", A / "refs")
    assert _shown(text, T) == """\
(version 1)
(deny default)
(allow process-exec process-fork)
(allow signal (target same-sandbox))
(allow process-info* (target self))
(allow sysctl-read)
(allow user-preference-read)
(allow file-read-metadata)
(allow file-read* file-map-executable (subpath "/System/Library") (subpath "/System/Volumes/Preboot/Cryptexes/OS") (subpath "<T>/py/bin") (subpath "<T>/py/lib") (subpath "/usr/lib") (subpath "/usr/share/locale") (subpath "<T>/work"))
(allow file-write* (subpath "<T>/work"))
(allow file-read* file-write-data (literal "/dev/null") (literal "/dev/zero") (literal "/dev/tty") (literal "/dev/ptmx") (literal "/dev/stdout") (literal "/dev/stderr") (subpath "/dev/fd") (regex #"^/dev/ttys[0-9]+$"))
(allow pseudo-tty)
(allow file-ioctl (literal "/dev/tty") (literal "/dev/ptmx") (regex #"^/dev/ttys[0-9]+$"))
(allow mach-lookup (global-name "com.apple.FSEvents"))
(deny network-bind network-inbound)
(deny appleevent-send)
(deny user-preference-write)
(deny network*)
(deny file-read* file-write* (literal "/dev/tty") (literal "/dev/ptmx") (regex #"^/dev/ttys[0-9]+$"))
(deny file-read-data file-write-data (literal "/dev/tty") (literal "/dev/ptmx") (regex #"^/dev/ttys[0-9]+$"))
(deny file-ioctl (literal "/dev/tty") (literal "/dev/ptmx") (regex #"^/dev/ttys[0-9]+$"))
(deny pseudo-tty)
(deny mach-lookup (global-name "com.apple.FSEvents"))
(deny user-preference-read)
(deny file-map-executable (subpath "<T>/work"))
(allow file-read-data (literal "/"))
(allow file-read* (literal "/dev/null"))
(allow file-read* (literal "/dev/random"))
(allow file-read* (literal "/dev/urandom"))
(allow file-read* (literal "/private/etc/localtime"))
(deny process-exec)
(allow process-exec (literal "<T>/py/bin/python3"))
(allow file-read* (literal "<T>/py/pyvenv.cfg"))
(deny file-write* (subpath "<T>/refs"))
(deny file-read* file-write* file-map-executable (subpath "<T>/home/.agents/skills"))
"""
    # The artifact checks pass no references: the same text without the references rule.
    refs = next(line for line in text.splitlines(True) if line.startswith('(deny file-write* (subpath "'))
    assert code_sandbox.computation_profile(python, A / "work") == text.replace(refs, "")


def test_run_python_in_a_venv_reached_through_a_link(T, A):
    """The interpreter as given (not resolved) and as resolved are both allowed to run; their
    lib and bin folders are read as resolved."""
    _between_system_and_usr(T)
    assert _shown(code_sandbox.computation_profile(str(A / "venv/bin/python"), A / "work"), T) == """\
(version 1)
(deny default)
(allow process-exec process-fork)
(allow signal (target same-sandbox))
(allow process-info* (target self))
(allow sysctl-read)
(allow user-preference-read)
(allow file-read-metadata)
(allow file-read* file-map-executable (subpath "/System/Library") (subpath "/System/Volumes/Preboot/Cryptexes/OS") (subpath "<T>/py/bin") (subpath "<T>/py/lib") (subpath "<T>/venv/bin") (subpath "<T>/venv/lib") (subpath "/usr/lib") (subpath "/usr/share/locale") (subpath "<T>/work"))
(allow file-write* (subpath "<T>/work"))
(allow file-read* file-write-data (literal "/dev/null") (literal "/dev/zero") (literal "/dev/tty") (literal "/dev/ptmx") (literal "/dev/stdout") (literal "/dev/stderr") (subpath "/dev/fd") (regex #"^/dev/ttys[0-9]+$"))
(allow pseudo-tty)
(allow file-ioctl (literal "/dev/tty") (literal "/dev/ptmx") (regex #"^/dev/ttys[0-9]+$"))
(allow mach-lookup (global-name "com.apple.FSEvents"))
(deny network-bind network-inbound)
(deny appleevent-send)
(deny user-preference-write)
(deny network*)
(deny file-read* file-write* (literal "/dev/tty") (literal "/dev/ptmx") (regex #"^/dev/ttys[0-9]+$"))
(deny file-read-data file-write-data (literal "/dev/tty") (literal "/dev/ptmx") (regex #"^/dev/ttys[0-9]+$"))
(deny file-ioctl (literal "/dev/tty") (literal "/dev/ptmx") (regex #"^/dev/ttys[0-9]+$"))
(deny pseudo-tty)
(deny mach-lookup (global-name "com.apple.FSEvents"))
(deny user-preference-read)
(deny file-map-executable (subpath "<T>/work"))
(allow file-read-data (literal "/"))
(allow file-read* (literal "/dev/null"))
(allow file-read* (literal "/dev/random"))
(allow file-read* (literal "/dev/urandom"))
(allow file-read* (literal "/private/etc/localtime"))
(deny process-exec)
(allow process-exec (literal "<T>/alias/venv/bin/python"))
(allow process-exec (literal "<T>/py/bin/python3"))
(allow file-read* (literal "<T>/alias/venv/pyvenv.cfg"))
(allow file-read* (literal "<T>/py/pyvenv.cfg"))
(deny file-read* file-write* file-map-executable (subpath "<T>/home/.agents/skills"))
"""


def test_installed_mcp_server(T, A, monkeypatch):
    """SBX-4: on the shared base. The protected paths close after the grants (a protected file is a literal
    now, as in the commands profile; a granted link appears twice), then the runtimes and the server's own
    folder open again, after them."""
    monkeypatch.setattr(command_sandbox, "default_protected", lambda: [A / "prot", A / "prot.key"])
    text = capability_sandbox.profile(root=A / "mcp", folders=[str(A / "granted"), str(A / "link-granted")],
                                      network=True, read=[str(A / "runtimes")], proxy_port=41000, bound_ports=[8741],
                                      system_proxies=[])
    assert _shown(text, T) == """\
(version 1)
(deny default)
(allow process-exec process-fork)
(allow signal (target same-sandbox))
(allow process-info* (target self))
(allow sysctl-read)
(allow user-preference-read)
(allow file-read-metadata)
(allow file-read* file-map-executable (subpath "/usr") (subpath "/System") (subpath "/Library/Apple") (subpath "/Library/Frameworks") (subpath "/private/etc") (subpath "/dev") (subpath "/private/var/db/timezone") (subpath "/private/var/db/dyld") (subpath "<T>/granted") (subpath "<T>/granted") (subpath "<T>/mcp/cache"))
(allow file-write* (subpath "<T>/granted") (subpath "<T>/granted") (subpath "<T>/mcp/cache"))
(allow file-read* file-write-data (literal "/dev/null") (literal "/dev/zero") (literal "/dev/tty") (literal "/dev/ptmx") (literal "/dev/stdout") (literal "/dev/stderr") (subpath "/dev/fd") (regex #"^/dev/ttys[0-9]+$"))
(allow pseudo-tty)
(allow file-ioctl (literal "/dev/tty") (literal "/dev/ptmx") (regex #"^/dev/ttys[0-9]+$"))
(allow mach-lookup (global-name "com.apple.FSEvents"))
(allow network-outbound (remote tcp "localhost:*"))
(allow network-outbound (remote tcp "localhost:41000"))
(deny network-outbound (remote tcp "localhost:8741"))
(deny network-bind network-inbound)
(deny appleevent-send)
(deny user-preference-write)
(deny file-read* file-write* file-map-executable (subpath "<T>/cache-commands"))
(deny network-outbound (subpath "<T>/cache-commands"))
(deny file-read* file-write* file-map-executable (subpath "<T>/prot") (literal "<T>/prot.key"))
(deny network-outbound (subpath "<T>/prot") (literal "<T>/prot.key"))
(deny file-read* file-write* (literal "/dev/tty") (literal "/dev/ptmx") (regex #"^/dev/ttys[0-9]+$"))
(deny file-read-data file-write-data (literal "/dev/tty") (literal "/dev/ptmx") (regex #"^/dev/ttys[0-9]+$"))
(deny file-ioctl (literal "/dev/tty") (literal "/dev/ptmx") (regex #"^/dev/ttys[0-9]+$"))
(deny pseudo-tty)
(deny mach-lookup (global-name "com.apple.FSEvents"))
(allow file-read-data (literal "/"))
(allow file-read* file-map-executable (subpath "<T>/runtimes"))
(allow file-read* file-write* file-map-executable (subpath "<T>/mcp"))
(deny file-write* (subpath "<T>/home/.agents/skills"))
(deny file-write* (subpath "<T>/home/Library/Caches") (subpath "<T>/home/.cache") (subpath "<T>/home/.npm"))
""" + RUN_LATER_TEXT
    assert _shown(capability_sandbox.profile(root=A / "mcp", folders=[], network=False, read=[]), T) == """\
(version 1)
(deny default)
(allow process-exec process-fork)
(allow signal (target same-sandbox))
(allow process-info* (target self))
(allow sysctl-read)
(allow user-preference-read)
(allow file-read-metadata)
(allow file-read* file-map-executable (subpath "/usr") (subpath "/System") (subpath "/Library/Apple") (subpath "/Library/Frameworks") (subpath "/private/etc") (subpath "/dev") (subpath "/private/var/db/timezone") (subpath "/private/var/db/dyld") (subpath "<T>/mcp/cache"))
(allow file-write* (subpath "<T>/mcp/cache"))
(allow file-read* file-write-data (literal "/dev/null") (literal "/dev/zero") (literal "/dev/tty") (literal "/dev/ptmx") (literal "/dev/stdout") (literal "/dev/stderr") (subpath "/dev/fd") (regex #"^/dev/ttys[0-9]+$"))
(allow pseudo-tty)
(allow file-ioctl (literal "/dev/tty") (literal "/dev/ptmx") (regex #"^/dev/ttys[0-9]+$"))
(allow mach-lookup (global-name "com.apple.FSEvents"))
(deny network-bind network-inbound)
(deny appleevent-send)
(deny user-preference-write)
(deny network*)
(deny file-read* file-write* file-map-executable (subpath "<T>/cache-commands"))
(deny network-outbound (subpath "<T>/cache-commands"))
(deny file-read* file-write* file-map-executable (subpath "<T>/prot") (literal "<T>/prot.key"))
(deny network-outbound (subpath "<T>/prot") (literal "<T>/prot.key"))
(deny file-read* file-write* (literal "/dev/tty") (literal "/dev/ptmx") (regex #"^/dev/ttys[0-9]+$"))
(deny file-read-data file-write-data (literal "/dev/tty") (literal "/dev/ptmx") (regex #"^/dev/ttys[0-9]+$"))
(deny file-ioctl (literal "/dev/tty") (literal "/dev/ptmx") (regex #"^/dev/ttys[0-9]+$"))
(deny pseudo-tty)
(deny mach-lookup (global-name "com.apple.FSEvents"))
(allow file-read-data (literal "/"))
(allow file-read* file-write* file-map-executable (subpath "<T>/mcp"))
(deny file-write* (subpath "<T>/home/.agents/skills"))
(deny file-write* (subpath "<T>/home/Library/Caches") (subpath "<T>/home/.cache") (subpath "<T>/home/.npm"))
""" + RUN_LATER_TEXT


def test_ssh():
    assert ssh_exec.ssh_profile() == """\
(version 1)
(allow default)
(deny network*)
(allow network-outbound (remote tcp "*:22"))
"""

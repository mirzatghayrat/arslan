"""SBX-1 (v0.1.64): the exact text of every seatbelt profile Arslan writes, for fixed inputs.

The texts were recorded from main before SBX-1 moved the profiles onto `sandbox_profile`, and
this file passes on both. Later SBX PRs that change a profile change its text here, so the
change is visible line by line in review.

Every input path goes through `A`, a link to the test's folder, so the texts also pin that each
profile resolves what it is given. The test's folder, resolved, is written as <T>.
"""
import os
from pathlib import Path

import pytest

from server.services import capability_sandbox, code_sandbox, command_sandbox, ssh_exec


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


@pytest.fixture
def A(T):
    """The way in: a link to the test's folder (inside it, so a path not resolved reads <T>/alias/…)."""
    alias = Path(os.path.realpath(T)) / "alias"
    alias.symlink_to(os.path.realpath(T))
    return alias


def _shown(text: str, T: Path) -> str:
    return text.replace(os.path.realpath(T), "<T>")


def test_commands_profile_with_every_part(T, A):
    text = command_sandbox.profile(
        [A / "link", A / "notes.txt", A / "missing", A / "closed/ws"], [A / "prot", A / "prot.key"], offline=True,
        closed=[A / "closed"], readable=[A / "closed/proj", A / "other", A / "closed/ws"], copies=[A / "copy.txt"])
    assert _shown(text, T) == """\
(version 1)
(allow default)
(deny appleevent-send)
(deny network*)
(deny file-write* (subpath "/"))
(allow file-write* (subpath "<T>/ws") (literal "<T>/notes.txt") (subpath "<T>/missing") (subpath "<T>/closed/ws"))
(deny file-read* file-write* (subpath "<T>/closed"))
(allow file-read* file-write* (subpath "<T>/closed/ws"))
(allow file-read* (subpath "<T>/closed/proj"))
(deny file-read* file-write* (subpath "<T>/prot") (literal "<T>/prot.key"))
(deny network-outbound (subpath "<T>/prot") (literal "<T>/prot.key"))
(allow file-read* (literal "<T>/copy.txt"))
"""


def test_a_closed_folder_with_nothing_to_reopen_stays_closed(T, A):
    """The default case for closed folders: Desktop, Documents and Downloads closed (the setting
    off), with no working or project folder inside them. Nothing is reopened after the deny."""
    expected = """\
(version 1)
(allow default)
(deny appleevent-send)
(deny file-write* (subpath "/"))
(allow file-write* (subpath "<T>/ws"))
(deny file-read* file-write* (subpath "<T>/closed"))
(deny file-read* file-write* (subpath "<T>/prot"))
(deny network-outbound (subpath "<T>/prot"))
"""
    assert _shown(command_sandbox.profile([A / "ws"], [A / "prot"], closed=[A / "closed"]), T) == expected
    assert _shown(command_sandbox.profile([A / "ws"], [A / "prot"], closed=[A / "closed"],
                                          readable=[A / "other"]), T) == expected


def test_commands_profile_plain_and_empty(T, A):
    quoted = A / 'a") (allow default) ("'
    assert _shown(command_sandbox.profile([A / "ws", quoted], []), T) == """\
(version 1)
(allow default)
(deny appleevent-send)
(deny file-write* (subpath "/"))
(allow file-write* (subpath "<T>/ws") (subpath "<T>/a\\") (allow default) (\\""))
"""
    assert command_sandbox.profile([], []) == """\
(version 1)
(allow default)
(deny appleevent-send)
(deny file-write* (subpath "/"))
"""


def test_a_non_ascii_name_is_written_as_its_own_characters(T, A):
    """SBX-1b: a CJK name is written as itself. Until SBX-1b it was `\\u5de5\\u4f5c\\u533a`
    (json.dumps), which seatbelt does not decode, so the rule matched no real folder (#471's review)."""
    name = "\u5de5\u4f5c\u533a"           # a working folder named in Chinese
    (T / f"{name}.key").write_text("x")      # and a protected file named the same way: a literal
    lines = _shown(command_sandbox.profile([A / name], [A / f"{name}.key"]), T).splitlines()
    assert lines[-3:] == [f'(allow file-write* (subpath "<T>/{name}"))',
                          f'(deny file-read* file-write* (literal "<T>/{name}.key"))',
                          f'(deny network-outbound (literal "<T>/{name}.key"))']


def test_outside_floor(T, A, monkeypatch):
    # arslan_protected() returns resolved paths; the floor writes them as given.
    ours = [Path(os.path.realpath(T / "data")), Path(os.path.realpath(T / "updater.key"))]
    monkeypatch.setattr(command_sandbox, "arslan_protected", lambda: ours)
    assert _shown(command_sandbox.minimal_profile(offline=True, copies=[A / "copy.txt"]), T) == """\
(version 1)
(allow default)
(deny appleevent-send)
(deny network*)
(deny file-read* file-write* (subpath "<T>/data") (literal "<T>/updater.key"))
(deny network-outbound (subpath "<T>/data") (literal "<T>/updater.key"))
(allow file-read* (literal "<T>/copy.txt"))
"""
    assert _shown(command_sandbox.minimal_profile(), T) == """\
(version 1)
(allow default)
(deny appleevent-send)
(deny file-read* file-write* (subpath "<T>/data") (literal "<T>/updater.key"))
(deny network-outbound (subpath "<T>/data") (literal "<T>/updater.key"))
"""


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
(allow file-read-data (literal "/"))
(allow file-read* (literal "/dev/null"))
(allow file-read* (literal "/dev/random"))
(allow file-read* (literal "/dev/urandom"))
(allow file-read* (literal "/private/etc/localtime"))
(deny process-exec)
(allow process-exec (literal "<T>/py/bin/python3"))
(allow file-read* (literal "<T>/py/pyvenv.cfg"))
(deny file-write* (subpath "<T>/refs"))
"""
    # The artifact checks pass no references: the same text without the last rule.
    assert code_sandbox.computation_profile(python, A / "work") == text[:text.rindex("(deny file-write*")]


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
"""


def test_installed_mcp_server(T, A, monkeypatch):
    """SBX-4: on the shared base. The protected paths close after the grants (a protected file is a literal
    now, as in the commands profile; a granted link appears twice), then the runtimes and the server's own
    folder open again, after them."""
    monkeypatch.setattr(command_sandbox, "default_protected", lambda: [A / "prot", A / "prot.key"])
    text = capability_sandbox.profile(root=A / "mcp", folders=[str(A / "granted"), str(A / "link-granted")],
                                      network=True, read=[str(A / "runtimes")])
    assert _shown(text, T) == """\
(version 1)
(deny default)
(allow process-exec process-fork)
(allow signal (target same-sandbox))
(allow process-info* (target self))
(allow sysctl-read)
(allow user-preference-read)
(allow file-read-metadata)
(allow file-read* file-map-executable (subpath "/usr") (subpath "/System") (subpath "/Library/Apple") (subpath "/Library/Frameworks") (subpath "/private/etc") (subpath "/dev") (subpath "/private/var/db/timezone") (subpath "/private/var/db/dyld") (subpath "<T>/granted") (subpath "<T>/granted"))
(allow file-write* (subpath "<T>/granted") (subpath "<T>/granted"))
(allow file-read* file-write-data (literal "/dev/null") (literal "/dev/zero") (literal "/dev/tty") (literal "/dev/ptmx") (literal "/dev/stdout") (literal "/dev/stderr") (subpath "/dev/fd") (regex #"^/dev/ttys[0-9]+$"))
(allow pseudo-tty)
(allow file-ioctl (literal "/dev/tty") (literal "/dev/ptmx") (regex #"^/dev/ttys[0-9]+$"))
(allow mach-lookup (global-name "com.apple.FSEvents"))
(allow mach-lookup (global-name "com.apple.trustd.agent"))
(allow network-outbound (literal "/private/var/run/mDNSResponder"))
(allow network-outbound (remote tcp "localhost:*"))
(allow network-outbound (remote tcp "*:*"))
(deny network-bind network-inbound)
(deny appleevent-send)
(deny user-preference-write)
(deny file-read* file-write* file-map-executable (subpath "<T>/prot") (literal "<T>/prot.key"))
(deny network-outbound (subpath "<T>/prot") (literal "<T>/prot.key"))
(allow file-read-data (literal "/"))
(allow file-read* file-map-executable (subpath "<T>/runtimes"))
(allow file-read* file-write* file-map-executable (subpath "<T>/mcp"))
"""
    assert _shown(capability_sandbox.profile(root=A / "mcp", folders=[], network=False, read=[]), T) == """\
(version 1)
(deny default)
(allow process-exec process-fork)
(allow signal (target same-sandbox))
(allow process-info* (target self))
(allow sysctl-read)
(allow user-preference-read)
(allow file-read-metadata)
(allow file-read* file-map-executable (subpath "/usr") (subpath "/System") (subpath "/Library/Apple") (subpath "/Library/Frameworks") (subpath "/private/etc") (subpath "/dev") (subpath "/private/var/db/timezone") (subpath "/private/var/db/dyld"))
(allow file-read* file-write-data (literal "/dev/null") (literal "/dev/zero") (literal "/dev/tty") (literal "/dev/ptmx") (literal "/dev/stdout") (literal "/dev/stderr") (subpath "/dev/fd") (regex #"^/dev/ttys[0-9]+$"))
(allow pseudo-tty)
(allow file-ioctl (literal "/dev/tty") (literal "/dev/ptmx") (regex #"^/dev/ttys[0-9]+$"))
(allow mach-lookup (global-name "com.apple.FSEvents"))
(deny network-bind network-inbound)
(deny appleevent-send)
(deny user-preference-write)
(deny network*)
(deny file-read* file-write* file-map-executable (subpath "<T>/prot") (literal "<T>/prot.key"))
(deny network-outbound (subpath "<T>/prot") (literal "<T>/prot.key"))
(allow file-read-data (literal "/"))
(allow file-read* file-write* file-map-executable (subpath "<T>/mcp"))
"""


def test_ssh():
    assert ssh_exec.ssh_profile() == """\
(version 1)
(allow default)
(deny network*)
(allow network-outbound (remote tcp "*:22"))
"""

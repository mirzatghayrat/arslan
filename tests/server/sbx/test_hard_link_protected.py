"""L-991-r2-7: a sandboxed command can't reach a file the commands profile denies by hard-linking it into the work
folder. Seatbelt judges a hard link by the name it is opened through, so the link itself must be refused.

Measured on macOS 26 (2026-11-18): seatbelt refuses `link()` unless the process may write the source file, with no
`file-link` rule in the profile. A file the command may only read (the control outside the work folder) can't be
linked either; giving its folder `file-write*` makes the same link succeed. So every file the commands profile denies
writing (the protected paths, which are read and write denied, and the write-denied run-later and cache paths) can't
be linked, also when the work folder holds it, and no link to a new name can be made inside a denied folder.

Only a work folder that holds the denied files tests the profile's denies: from a work folder elsewhere nothing
outside it is writable, so every link out is refused whatever the denies say (measured: a mutant dropping ~/.ssh
from the protected list still passes there). Both tests therefore also run with the work folder at home, where
dropping any one deny (the ~/.ssh entry, Arslan's data, the LaunchAgents hold, the shared-cache deny) fails them.

Under real seatbelt, in a scratch HOME with benign stand-in files. The probe prints, per step, "ok" or the errno's name.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from server.services import command_sandbox

macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")

PROBE = """
import errno, json, os, sys
out = {}
for name, source, link in json.loads(sys.argv[1]):
    for step in ('link', 'read', 'write'):
        try:
            if step == 'link':
                os.link(source, link)
            elif step == 'read':
                open(link).read()
            else:
                with open(link, 'r+') as f:
                    f.write('changed')
            out[f'{name}-{step}'] = 'ok'
        except OSError as exc:
            out[f'{name}-{step}'] = errno.errorcode.get(exc.errno, str(exc.errno))
print(json.dumps(out))
"""
REFUSED = {"EPERM", "EACCES"}


@pytest.fixture
def home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    data = home / "arslan-data"          # inside home, so a work folder at home holds it
    data.mkdir()
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(data))
    temp = tmp_path / "t"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    return home


def _files(home: Path, tmp_path: Path) -> dict[str, Path]:
    files = {"ssh": home / ".ssh" / "id_stand_in", "data": home / "arslan-data" / "stand-in.db",
             "launch-agent": home / "Library" / "LaunchAgents" / "stand.in.plist",
             "cache": home / ".cache" / "stand-in", "control": tmp_path / "elsewhere" / "plain.txt"}
    for path in files.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original")
    return files


def _probe(profile: str, checks) -> dict:
    path = command_sandbox.write_profile(profile)
    try:
        result = subprocess.run([command_sandbox._SANDBOX_EXEC, "-f", str(path), sys.executable, "-I", "-c", PROBE,
                                 json.dumps([(n, str(s), str(d)) for n, s, d in checks])],
                                capture_output=True, text=True, timeout=30)
    finally:
        command_sandbox.remove_profile(path)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


DENIED = ("ssh", "data", "launch-agent", "cache")


@pytest.mark.macos
@macos
@pytest.mark.parametrize("at_home", [False, True], ids=["work-folder", "work-folder-is-home"])
def test_no_hard_link_to_a_denied_file(home, tmp_path, at_home):
    """With the work folder at home, ~/.ssh, LaunchAgents and ~/.cache are inside the writable root, under their own
    denies. Controls: a file in the work folder links and is reached through the link; a file outside it that the
    command may read but not write is refused like the denied ones (the rule the measurement found)."""
    work = home if at_home else tmp_path / "work"
    work.mkdir(exist_ok=True)
    files = _files(home, tmp_path)
    (work / "mine.txt").write_text("original")
    files["mine"] = work / "mine.txt"
    out = _probe(command_sandbox.commands_profile(work, offline=True),
                 [(name, path, work / f"{name}-link") for name, path in files.items()])
    assert out["mine-link"] == out["mine-read"] == out["mine-write"] == "ok", out
    assert out["control-link"] in REFUSED, out
    for name in DENIED:
        assert out[f"{name}-link"] in REFUSED, (name, out)
        assert out[f"{name}-read"] == out[f"{name}-write"] == "ENOENT", (name, out)   # no link there to open
        assert files[name].read_text() == "original" and files[name].stat().st_nlink == 1, name


@pytest.mark.macos
@macos
@pytest.mark.parametrize("at_home", [False, True], ids=["work-folder", "work-folder-is-home"])
def test_no_hard_link_to_a_new_name_inside_a_denied_folder(home, tmp_path, at_home):
    work = home if at_home else tmp_path / "work"
    work.mkdir(exist_ok=True)
    _files(home, tmp_path)
    (work / "mine.txt").write_text("original")
    targets = {"ssh": home / ".ssh" / "new", "data": home / "arslan-data" / "new",
               "launch-agent": home / "Library" / "LaunchAgents" / "new.plist", "cache": home / ".cache" / "new"}
    out = _probe(command_sandbox.commands_profile(work, offline=True),
                 [(name, work / "mine.txt", path) for name, path in targets.items()])
    for name, path in targets.items():
        assert out[f"{name}-link"] in REFUSED and not path.exists(), (name, out)
    assert (work / "mine.txt").stat().st_nlink == 1

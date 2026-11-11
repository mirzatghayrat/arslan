"""HR-1 #813 review 12 (v0.1.64): the folder the profile files are written in is closed in every preset.

Review 11 gives sandbox-exec its profile as a file, in `sandbox-profiles/` in Arslan's data folder
(`command_sandbox.profile_folder`), because every preset closes that folder: the commands sandbox, an MCP server's
and the outside floor. Nothing they run may read, change, rename, remove or add a profile there between its writing
and sandbox-exec's read, its own included. ⓪Plan's cheap pin for the one mutant that survived review 11 (the folder
dropped from the closed paths):

- the profile text lists that folder, or a folder above it, among the paths closed to reads and writes (anywhere);
- under real seatbelt, from a profile delivered as the product delivers it (`-f`), every one of those is refused and
  the files are as they were, while the preset's own writable folder is written (macOS).

The MCP preset is built with the product's protected paths here: the harness's MCP adapter stands one folder in for
them. Stand-in names and plain paths only.
"""
import contextlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from server.services import command_sandbox
from tests.server.sbx.harness import Harness
from tests.server.sbx.test_hr1_run_later_aliases import PRESETS, STAND_IN, _folder
from tests.server.sbx.test_hr1_run_later_kernel import _floor_profile

macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")

_CLOSED_RULE = re.compile(r"^\(deny file-read\* file-write\*[^(]*(.*)\)$")
_SUBPATH = re.compile(r'\(subpath "((?:[^"\\]|\\.)*)"\)')

#: argv: own (the profile this process started from), other (another command's), new (a name not there yet), the
#: preset's writable folder. Prints each outcome: "done", "refused" (EPERM) or "error <errno>".
_OPS = """
import json, os, sys
own, other, new, writable = sys.argv[1:5]

def attempt(step):
    try:
        step()
    except PermissionError:
        return 'refused'
    except OSError as error:
        return f'error {error.errno}'
    return 'done'

def write(path):
    with open(path, 'w') as handle:
        handle.write('(version 1)(allow default)')

def read(path):
    with open(path) as handle:
        handle.read()

print(json.dumps([attempt(lambda: read(own)), attempt(lambda: write(own)), attempt(lambda: write(other)),
                  attempt(lambda: os.rename(other, other + '.moved')), attempt(lambda: os.unlink(own)),
                  attempt(lambda: write(new)), attempt(lambda: os.listdir(os.path.dirname(own))),
                  attempt(lambda: write(os.path.join(writable, 'ordinary.txt')))]))
"""


@contextlib.contextmanager
def _harness_env(sbx):
    """The harness's scratch HOME, temp and data folder, as it builds its presets."""
    with pytest.MonkeyPatch.context() as environment:
        for name in ("HOME", "TMPDIR", "ARSLAN_DATA_DIR"):
            environment.setenv(name, sbx.env[name])
        environment.setattr(tempfile, "tempdir", str(sbx.temp))
        yield


def _profile_folder(sbx) -> Path:
    with _harness_env(sbx):
        return command_sandbox.profile_folder()


def _profile(sbx) -> str:
    """The preset's text as the product builds it, the MCP preset closing the product's protected paths."""
    _folder(sbx)
    if sbx.base == "outside-floor":
        return _floor_profile(sbx)
    if sbx.base == "mcp":
        with _harness_env(sbx):
            protected = command_sandbox.default_protected()
        return sbx.profile(protected=protected)
    return sbx.profile()


def _closed(text: str) -> list[Path]:
    """The folders the text closes to reads and writes (`(deny file-read* file-write* … (subpath …))`)."""
    out = []
    for line in text.splitlines():
        rule = _CLOSED_RULE.match(line)
        if rule:
            out += [Path(re.sub(r"\\(.)", r"\1", path)) for path in _SUBPATH.findall(rule.group(1))]
    return out


@pytest.mark.parametrize("base", PRESETS)
def test_every_preset_lists_the_profile_folder_among_its_closed_paths(tmp_path, base):
    sbx = Harness(tmp_path, base)
    folder = _profile_folder(sbx)
    closed = _closed(_profile(sbx))
    assert closed, "no closed paths found in the profile text"
    assert any(path == folder or path in folder.parents for path in closed), (folder, closed)


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", PRESETS, indirect=True)
def test_nothing_run_under_a_preset_can_touch_the_profile_folder(sbx):
    """Its own profile read, rewritten or removed; another command's rewritten or renamed; a new one added; the folder
    listed: each refused, and the files unchanged. The preset's writable folder is written."""
    text = _profile(sbx)
    with _harness_env(sbx):
        own, other = command_sandbox.write_profile(text), command_sandbox.write_profile(text)
    new = own.parent / f"{STAND_IN}.sb"
    try:
        ran = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(own), sys.executable, "-I", "-c", _OPS, str(own),
                              str(other), str(new), str(_folder(sbx))], cwd=sbx.work, env=sbx.env,
                             capture_output=True, text=True, timeout=120)
        assert ran.returncode == 0, ran.stderr
        assert json.loads(ran.stdout) == ["refused"] * 7 + ["done"]
        assert own.read_text() == other.read_text() == text
        assert not new.exists() and not Path(f"{other}.moved").exists()
    finally:
        for path in (own, other, new, Path(f"{other}.moved")):
            command_sandbox.remove_profile(path)

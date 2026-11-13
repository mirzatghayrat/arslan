"""S4b-0 (v0.1.64): the commands sandbox takes the user's allowed folders as extra writable roots.

S4b (②Main) wires Settings' allowed folders to the callers; this is the sandbox's side. `allowed` on `writable_roots`,
`commands_profile` and `wrapper`: each root tagged ALLOWED (not in scope for the classifier), pinned by `wrapper` like
the work folder (SBX-9), walked by HR-1 like it (its held folders, `core.hooksPath` and caps), reopened inside a closed
folder, and seen by `open_once`. An unsafe root raises ValueError (no profile, the command doesn't start). None leaves
the profile byte for byte as it was.

- Portable: each refusal class, what is accepted (a folder outside home, on a stand-in volume, among them), the tag,
  `open_once`, and the empty case against today's text rebuilt from its parts (test_sbx3a's).
- Real seatbelt: `cp` into an allowed root works and the folder beside it stays denied; inside one, a git hook, the
  `.git` folder and a `core.hooksPath` target are refused as in the work folder; a swap after the build is refused.

The system folders are stood in for (`SYSTEM_FOLDERS`): the test's temp is under /private on macOS. Stand-in names.
"""
import json
import os
import sys
from pathlib import Path

import pytest

from server.services import command_sandbox, root_pin
from server.services.sandbox_profile import NetworkMode, real, subpath
from tests.server.sbx.test_sbx3a_commands_profile import _base_for, _shared_caches_read_only
from tests.server.sbx import test_sbx9_root_pin as sbx9
from tests.server.sbx.test_sbx9_root_pin import _swap_for_link

home = sbx9.home        # the fixture: a scratch HOME, temp root and data folder (home/data)

macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")
STAND_IN = "zz-stand-in-word"


@pytest.fixture
def system(tmp_path, monkeypatch):
    """A stand-in system folder, so a folder under the test's temp (in /private on macOS) can be allowed."""
    folder = tmp_path.resolve() / "zz-system"
    folder.mkdir()
    monkeypatch.setattr(command_sandbox, "SYSTEM_FOLDERS", (folder,))
    return folder


@pytest.fixture
def env(home, system):
    """sbx9's scratch HOME with a work folder, and the stand-in system folder."""
    home = home.resolve()
    (home / "ws").mkdir()
    return home, home / "ws"


def _folders(*paths) -> list[Path]:
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)
    return list(paths)


def _profile(ws, allowed, **kw) -> str:
    return command_sandbox.commands_profile(ws, offline=True, allowed=allowed, **kw)


# ── refusals: no profile, the command doesn't start ──────────────────────────

def _refused_cases(home: Path, ws: Path, system: Path) -> dict:
    (home / "file.txt").write_text("x")
    (home / "link").symlink_to(_folders(home / "linked")[0], target_is_directory=True)
    return {
        "home itself": ([home], {}),
        "/": ([Path("/")], {}),
        "inside a system folder": (_folders(system / STAND_IN), {}),
        "above a system folder": ([system.parent], {}),
        "missing": ([home / "missing"], {}),
        "a file": ([home / "file.txt"], {}),
        "a link to a folder": ([home / "link"], {}),
        "holding a protected path": (_folders(home / ".docker"), {}),        # ~/.docker/config.json
        "a protected folder": (_folders(home / ".ssh"), {}),
        "inside a protected folder": (_folders(home / ".ssh" / STAND_IN), {}),
        "inside the data folder": (_folders(home / "data" / STAND_IN), {}),
        "inside an app's data": (_folders(home / "Library" / "Mail" / STAND_IN), {}),
        "holding an app's data": (_folders(home / "Library"), {}),
        "a closed folder": (_folders(home / "Desktop"), {"closed": [home / "Desktop"]}),
        "holding a closed folder": (_folders(home / STAND_IN / "shut")[:0] + [home / STAND_IN],
                                    {"closed": [home / STAND_IN / "shut"]}),
        "the work folder": ([ws], {}),
        "inside the work folder": (_folders(ws / STAND_IN), {}),
        "overlapping": (_folders(home / "p", home / "p" / "q"), {}),
        "the same twice": (_folders(home / "p") * 2, {}),
        "a sixth": (_folders(*(home / f"p{i}" for i in range(6))), {}),
    }


_SYSTEM, _REAL, _SHUT, _OVERLAP = ("a system folder", "not an existing real folder", "a protected or closed folder",
                                    "the work folder or another allowed folder")
#: case: the reason it is refused for (each class has its own check, so dropping one is seen even where another
#: would also refuse it: the home folder holds ~/.ssh's name).
CASES = {"home itself": "the home folder", "/": _SYSTEM, "inside a system folder": _SYSTEM,
         "above a system folder": _SYSTEM, "missing": _REAL, "a file": _REAL, "a link to a folder": _REAL,
         "holding a protected path": _SHUT, "a protected folder": _SHUT, "inside a protected folder": _SHUT,
         "inside the data folder": _SHUT, "inside an app's data": _SHUT, "holding an app's data": _SHUT,
         "a closed folder": _SHUT, "holding a closed folder": _SHUT, "the work folder": _OVERLAP,
         "inside the work folder": _OVERLAP, "overlapping": _OVERLAP, "the same twice": _OVERLAP,
         "a sixth": "more than 5 folders"}


@pytest.mark.parametrize("case", sorted(CASES))
def test_each_unsafe_root_raises_and_builds_no_profile(env, system, case):
    home, ws = env
    allowed, kw = _refused_cases(home, ws, system)[case]
    with pytest.raises(ValueError, match=f"^allowed: .*{CASES[case]}"):
        _profile(ws, allowed, **kw)


def test_holding_a_closed_folder_is_refused_and_the_same_folder_beside_it_is_not(env):
    home, ws = env
    (home / STAND_IN / "Desktop").mkdir(parents=True)
    with pytest.raises(ValueError):
        _profile(ws, [home / STAND_IN], closed=[home / STAND_IN / "Desktop"])
    _profile(ws, [home / STAND_IN], closed=[home / "Desktop"])                  # the control


def test_safe_roots_are_accepted_outside_home_and_on_a_volume_too(env, tmp_path):
    home, ws = env
    volume = tmp_path.resolve() / "Volumes" / STAND_IN / "proj"                  # outside the scratch HOME
    roots = _folders(home / "a", home / "b" / "c", volume, home / "d", home / "e")   # five
    text = _profile(ws, roots)
    for root in roots:
        assert f'(subpath "{root}")' in text


def test_a_root_inside_a_closed_folder_is_reopened_and_open_once_sees_it(env):
    """The closed-folder reopen covers an allowed root, as the work folder; `open_once` refuses a folder inside it."""
    home, ws = env
    desk = home / "Desktop"
    proj, sub = _folders(desk / "proj", desk / "proj" / STAND_IN)
    text = _profile(ws, [proj], closed=[desk])
    assert f'(allow file-read* file-write* file-map-executable (subpath "{proj}"))' in text
    _profile(ws, [], closed=[desk], open_once=sub)                              # the control: closed, so reopened
    with pytest.raises(ValueError, match="already inside a writable folder"):
        _profile(ws, [proj], closed=[desk], open_once=sub)


def test_the_roots_are_tagged_allowed_and_not_in_scope(env):
    home, ws = env
    proj = _folders(home / "proj")[0]
    roots = command_sandbox.writable_roots(ws, allowed=[proj])
    assert [r for r in roots if r.tag == command_sandbox.ALLOWED] == [command_sandbox.Root(str(proj), "allowed")]
    assert command_sandbox.in_scope(ws / "a.txt", roots)
    assert not command_sandbox.in_scope(proj / "a.txt", roots)


def test_no_allowed_roots_is_todays_profile_byte_for_byte(env):
    home, ws = env
    today = _base_for(home, NetworkMode.NONE) + _shared_caches_read_only()      # rebuilt from its parts
    assert command_sandbox.commands_profile(ws, offline=True) == today
    assert _profile(ws, ()) == today and _profile(ws, []) == today


# ── the pin (SBX-9) ──────────────────────────────────────────────────────────

@pytest.mark.macos
@macos
def test_an_allowed_root_is_pinned_and_a_swap_after_the_build_is_refused(env):
    home, ws = env
    proj, outside = _folders(home / "proj", home / "outside")
    prefix = command_sandbox.wrapper(ws, offline=True, allowed=[proj])
    profile = command_sandbox.profile_path(prefix)
    pins = list(command_sandbox._PINS[str(profile)])
    try:
        assert pins[-1].path == real(proj) and subpath(real(proj)) in profile.read_text()
        command_sandbox.check_pins(profile)
        _swap_for_link(proj, outside)
        with pytest.raises(root_pin.Swapped):
            command_sandbox.check_pins(profile)
    finally:
        command_sandbox.remove_profile(profile)
    assert all(p.fd is None for p in pins)


@pytest.mark.macos
@macos
def test_a_link_given_as_an_allowed_root_is_refused_and_a_walk_root_still_pins_in_its_place(env):
    home, ws = env
    proj, kid = _folders(home / "proj", ws / "sub" / "kid")
    (home / "link").symlink_to(proj, target_is_directory=True)
    with pytest.raises(root_pin.Swapped):
        command_sandbox.wrapper(ws, offline=True, allowed=[home / "link"])
    prefix = command_sandbox.wrapper(kid, offline=True, walk_root=ws, allowed=[proj])   # SBX-10's slot is kept
    try:
        assert [p.path for p in command_sandbox._PINS[str(command_sandbox.profile_path(prefix))]][-2:] == [ws, proj]
    finally:
        command_sandbox.remove_profile(command_sandbox.profile_path(prefix))


# ── real seatbelt ────────────────────────────────────────────────────────────

@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
def test_cp_into_an_allowed_root_works_and_the_folder_beside_it_is_still_denied(sbx, system):
    proj, beside = _folders(sbx.home / "proj", sbx.home / "beside")
    (sbx.work / "src.txt").write_text("zz")
    text = sbx.profile(allowed=[proj])

    def cp(to, profile):
        return sbx.run(["/bin/cp", sbx.work / "src.txt", to], probe="s4b0-cp", profile=profile).returncode
    assert cp(proj / "before.txt", sbx.profile()) != 0                          # the control: closed without it
    assert cp(proj / "a.txt", text) == 0 and (proj / "a.txt").read_text() == "zz"
    assert cp(beside / "a.txt", text) != 0 and not (beside / "a.txt").exists()


_HELD = """
import json, os, sys
root = sys.argv[1]
out = {}
for name in (".git/hooks/pre-commit", "hp/pre-commit", "zz-stand-in-word.txt"):
    try:
        open(os.path.join(root, name), "w").write("zz")
    except PermissionError:
        out[name] = "refused"
    else:
        out[name] = "written"
try:
    os.rename(os.path.join(root, ".git"), os.path.join(root, "x"))
except PermissionError:
    out["mv .git x"] = "refused"
else:
    out["mv .git x"] = "moved"
print(json.dumps(out))
"""


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
@pytest.mark.parametrize("where", ["allowed", "work"])
def test_in_an_allowed_root_a_hook_the_git_folder_and_a_hookspath_target_are_held_as_in_the_work_folder(
        sbx, system, where):
    proj = _folders(sbx.home / "proj")[0]
    root = proj if where == "allowed" else sbx.work
    _folders(root / ".git" / "hooks", root / "hp")
    (root / ".git" / "config").write_text("[core]\n\thooksPath = hp\n")
    result = sbx.python(_HELD, root, probe="s4b0-held", profile=sbx.profile(allowed=[proj]))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {".git/hooks/pre-commit": "refused", "hp/pre-commit": "refused",
                                         f"{STAND_IN}.txt": "written", "mv .git x": "refused"}
    assert (root / ".git").is_dir() and not os.path.lexists(root / "hp" / "pre-commit")

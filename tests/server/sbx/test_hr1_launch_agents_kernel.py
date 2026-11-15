"""Run-later at home (v0.1.64): LaunchAgents and the login-items store under real seatbelt, through the product path.

`run_later.home_filters` holds ~/Library/LaunchAgents, ~/Library/StartupItems and the background task manager's store
(plus /Library/LaunchAgents and /Library/LaunchDaemons) by path, in the outside floor that holds run-later files
(`terminal_exec.run(sandbox=False, hold_run_later=True)`) and always in the commands profile (`sandbox=True`). Each
case runs in a scratch HOME (`HOME` and so `Path.home` point at a temp folder); the real ~/Library is never written.

Cases: a plain plist write under the floor is refused (control: it lands without the hold), and in the commands
profile with the work folder at the scratch HOME; a LaunchAgents that is a link elsewhere is held through the link and
at its target; renaming LaunchAgents aside (or ~/Library itself) and putting a fresh one in leaves no plist; and git's
maintenance scheduler (`git maintenance start`) leaves no plist under the floor, while the control shows it writes one.
For that one, git's own test knob points the scheduler at `true` and the profile also refuses to exec launchctl, so no
launchd job is ever registered.

Stand-in names only.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from server.services import command_sandbox, run_later, terminal_exec

STAND_IN = "zz-stand-in-word"
PLIST = f"{STAND_IN}.plist"
macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")

#: The test's own addition to every outside profile: launchctl never starts, so nothing reaches launchd.
NO_LAUNCHCTL = '\n(deny process-exec (literal "/bin/launchctl"))\n'


def test_home_filters_name_each_folder_its_real_path_and_the_folders_above(tmp_path):
    """Any platform: the filters' text. A LaunchAgents that is a link adds its target, and the folders above it."""
    from server.services.sandbox_profile import literal, subpath
    tmp_path = Path(os.path.realpath(tmp_path))
    home = tmp_path / "hömé"                           # non-ASCII stays as is (`sbpl_string`), never `\\u` escapes
    target = tmp_path / f"{STAND_IN}-agents"
    target.mkdir()
    (home / "Library").mkdir(parents=True)
    plain = run_later.home_filters(home)
    for name in run_later.HOME_NAMES:
        assert subpath(home / name) in plain
    for name in run_later.SYSTEM_NAMES:
        assert subpath(name) in plain
    assert literal(home / "Library") in plain and literal(home / "Library" / "Application Support") in plain
    assert literal(home) not in plain and subpath(target) not in plain
    assert "hömé" in "".join(plain) and "\\u" not in "".join(plain)
    (home / "Library" / "LaunchAgents").symlink_to(target)
    linked = run_later.home_filters(home)
    real = Path(os.path.realpath(target))
    assert subpath(home / "Library" / "LaunchAgents") in linked and subpath(real) in linked
    assert literal(real.parent) in linked


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """A scratch HOME with an empty ~/Library/LaunchAgents; every outside profile refuses to exec launchctl."""
    folder = tmp_path / "home"
    (folder / "Library" / "LaunchAgents").mkdir(parents=True)
    (folder / "Library" / "Application Support").mkdir()
    monkeypatch.setenv("HOME", str(folder))
    assert Path.home() == folder
    built = command_sandbox.minimal_profile
    monkeypatch.setattr(command_sandbox, "minimal_profile", lambda **kw: built(**kw) + NO_LAUNCHCTL)
    return folder


def _work(home: Path) -> Path:
    work = home / STAND_IN
    work.mkdir(exist_ok=True)
    return work


async def _floor(command: str, home: Path, *, hold: bool = True) -> dict:
    return await terminal_exec.run(command, cwd=_work(home), offline=True, hold_run_later=hold)


def _plists(*folders: Path) -> list[Path]:
    return [p for f in folders if f.is_dir() for p in f.rglob("*.plist")]


@pytest.mark.macos
@macos
async def test_a_plist_write_under_the_floor_is_refused_and_lands_without_the_hold(home):
    agents = home / "Library" / "LaunchAgents"
    command = f"printf zz > '{agents / PLIST}'"
    held = await _floor(command, home)
    assert held["exit_code"] != 0 and held["sandbox"] == "outside", held
    assert not (agents / PLIST).exists()
    landed = await _floor(command, home, hold=False)
    assert landed["exit_code"] == 0, landed
    assert (agents / PLIST).read_text() == "zz"


@pytest.mark.macos
@macos
@pytest.mark.parametrize("name", run_later.HOME_NAMES)
async def test_each_home_name_is_refused_under_the_floor(home, name):
    folder = home / name
    folder.mkdir(parents=True, exist_ok=True)
    result = await _floor(f"printf zz > '{folder / PLIST}'", home)
    assert result["exit_code"] != 0, result
    assert not (folder / PLIST).exists()


@pytest.mark.macos
@macos
async def test_another_letter_case_is_refused_too_existing_or_fresh(home):
    """The literal paths hold other spellings on this case-insensitive volume, also for a folder made fresh."""
    existing = await _floor(f"printf zz > '{home}/library/launchagents/{PLIST}'", home)
    assert existing["exit_code"] != 0 and _plists(home / "Library") == [], existing
    (home / "Library" / "LaunchAgents").rmdir()
    fresh = await _floor(f"mkdir '{home}/Library/launchagents' && printf zz > '{home}/Library/launchagents/{PLIST}'",
                         home)
    assert fresh["exit_code"] != 0 and _plists(home / "Library") == [], fresh


@pytest.mark.macos
@macos
async def test_the_commands_profile_refuses_it_with_the_work_folder_at_home(home):
    agents = home / "Library" / "LaunchAgents"
    result = await terminal_exec.run(f"printf zz > '{agents / PLIST}'; printf zz > {STAND_IN}.txt", cwd=home,
                                     sandbox=True, offline=True)
    assert result["sandbox"] == "workspace", result
    assert not (agents / PLIST).exists()
    assert (home / f"{STAND_IN}.txt").read_text() == "zz"                 # the work folder itself is writable


@pytest.mark.macos
@macos
async def test_a_launch_agents_link_is_held_through_the_link_and_at_its_target(home):
    agents = home / "Library" / "LaunchAgents"
    agents.rmdir()
    target = home / f"{STAND_IN}-agents"
    target.mkdir()
    agents.symlink_to(target)
    for command in (f"printf zz > '{agents / PLIST}'", f"printf zz > '{target / PLIST}'"):
        result = await _floor(command, home)
        assert result["exit_code"] != 0, result
    assert _plists(target) == []
    sandboxed = await terminal_exec.run(f"printf zz > '{target / PLIST}'", cwd=home, sandbox=True, offline=True)
    assert sandboxed["exit_code"] != 0 and _plists(target) == [], sandboxed


@pytest.mark.macos
@macos
@pytest.mark.parametrize("dangling", [False, True], ids=["existing", "dangling"])
@pytest.mark.parametrize("sandbox", [False, True], ids=["floor", "commands"])
async def test_a_plist_link_inside_the_folder_is_held_at_its_target(home, dangling, sandbox):
    """A dotfiles manager's plist: a link in LaunchAgents to a file elsewhere, which launchd reads (#940 review 1).
    Writing through the link, to the target, or renaming the target's folder aside and a fresh one in: all refused."""
    agents = home / "Library" / "LaunchAgents"
    dotfiles = home / f"{STAND_IN}-dotfiles"
    dotfiles.mkdir()
    target = dotfiles / PLIST
    if not dangling:
        target.write_text("old")
    (agents / PLIST).symlink_to(target)
    commands = (f"printf zz > '{agents / PLIST}'", f"printf zz > '{target}'",
                f"cd '{home}' && mv '{dotfiles.name}' D2 && mkdir '{dotfiles.name}'"
                f" && printf zz > '{dotfiles.name}/{PLIST}'")
    for command in commands:
        if sandbox:
            result = await terminal_exec.run(command, cwd=home, sandbox=True, offline=True)
        else:
            result = await _floor(command, home)
        assert result["exit_code"] != 0, (command, result)
    assert (not target.exists()) if dangling else target.read_text() == "old"
    assert dotfiles.is_dir() and not (home / "D2").exists()


def test_home_filters_hold_a_link_targets_real_path_and_its_folders(tmp_path):
    home = tmp_path / "home"
    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    target = tmp_path / "dots" / "launchd" / PLIST
    target.parent.mkdir(parents=True)
    (agents / PLIST).symlink_to(target)                           # dangling: a write through it lands at target
    (agents / "plain.plist").write_text("x")
    filters = run_later.home_filters(home)
    real = Path(os.path.realpath(target))
    assert f'(literal "{real}")' in filters
    assert f'(literal "{real.parent}")' in filters and f'(literal "{real.parent.parent}")' in filters
    assert not any("plain.plist" in f for f in filters)


#: Renames that would move a held folder (or ~/Library above it) aside and put a fresh one in its place.
RENAMES = {
    "agents-aside": "mv Library/LaunchAgents Library/LA2 && mkdir Library/LaunchAgents"
                    f" && printf zz > Library/LaunchAgents/{PLIST}",
    "library-aside": f"mv Library L2 && printf zz > L2/LaunchAgents/{PLIST} && mv L2 Library",
    "support-aside": "mkdir -p 'Library/Application Support/com.apple.backgroundtaskmanagementagent'"
                     " && mv 'Library/Application Support' Library/AS2"
                     f" && printf zz > Library/AS2/com.apple.backgroundtaskmanagementagent/{PLIST}"
                     " && mv Library/AS2 'Library/Application Support'",
}


@pytest.mark.macos
@macos
@pytest.mark.parametrize("case", sorted(RENAMES))
@pytest.mark.parametrize("sandbox", [False, True], ids=["floor", "commands"])
async def test_a_rename_aside_and_a_fresh_folder_leave_no_plist(home, case, sandbox):
    btm = home / "Library" / "Application Support" / "com.apple.backgroundtaskmanagementagent"
    btm.mkdir()
    command = f"cd '{home}' && {RENAMES[case]}"
    if sandbox:
        result = await terminal_exec.run(command, cwd=home, sandbox=True, offline=True)
    else:
        result = await _floor(command, home)
    assert result["exit_code"] != 0, result
    assert _plists(home / "Library", home / "L2") == []
    assert (home / "Library" / "LaunchAgents").is_dir() and btm.is_dir()


#: git's own test knob runs `true` in launchctl's place; the profile refuses launchctl as well (NO_LAUNCHCTL).
_MAINTENANCE = "GIT_TEST_MAINT_SCHEDULER=launchctl:true git maintenance start"


@pytest.mark.macos
@macos
async def test_git_maintenance_start_under_the_floor_leaves_no_plist(home):
    agents = home / "Library" / "LaunchAgents"
    work = _work(home)
    made = subprocess.run(["git", "init", "-q"], cwd=work, capture_output=True, text=True, timeout=60,
                          env={"PATH": "/usr/bin:/bin", "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1"})
    assert made.returncode == 0, made.stderr                  # made outside: init writes .git/config and hooks
    held = await _floor(_MAINTENANCE, home)
    assert held["exit_code"] != 0, held
    assert not list(agents.glob("org.git-scm.git.*.plist"))
    # Control: the same scheduler without the hold writes its plists (launchctl stays out of reach either way).
    landed = await _floor(_MAINTENANCE, home, hold=False)
    assert landed["exit_code"] == 0, landed
    assert list(agents.glob("org.git-scm.git.*.plist"))

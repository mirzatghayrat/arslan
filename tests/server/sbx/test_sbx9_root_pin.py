"""SBX-9 (v0.1.64): a writable root is pinned once, so a concurrent link swap can't redirect a sandboxed command's writes.

⓪Plan (#846 review): the per-run folder and the work folder were checked, then resolved again while the profile was
built; a flipper swapping one for a link to another folder and back let commands write there. Now each root is resolved
once and pinned (`root_pin`), the profile names only the pinned real paths, and the start is refused when a root isn't
that folder right before the spawn.

- The pin itself, portable: a link root refused (unless `follow`), a link at the open refused (`O_NOFOLLOW`), the
  check before the spawn, the descriptors closed, `real` not resolving a pinned path again.
- The file tools: the working folder pinned once per call and checked again right before the write.
- Real seatbelt, through the real executor: a swap before the start and a swap between the profile and the spawn are
  refused with the note; under an active flipper (the run's temp, and separately the work folder) no marker reaches
  the outside folder.
"""
import asyncio
import errno
import os
import sys
import tempfile
import threading
from pathlib import Path

import pytest

from server import config
from server.registry import file_tools
from server.services import (capability_sandbox, code_sandbox, command_sandbox, root_pin, run_temp, terminal_exec,
                             workspace_paths)
from server.services.sandbox_profile import real, subpath

macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")


@pytest.fixture
def home(monkeypatch, tmp_path):
    """A scratch HOME, temp root and data folder: nothing here touches the real ones."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    temp = tmp_path / "t"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    data = home / "data"
    data.mkdir()
    monkeypatch.setattr(config, "data_dir", lambda: data)
    monkeypatch.setattr(command_sandbox, "_PINS", {})   # this test's pins only (others build profiles without starting)
    run_temp._reset_for_tests()
    yield home
    run_temp._reset_for_tests()


def _swap_for_link(folder: Path, target: Path) -> Path:
    """`folder` moved aside and a link to `target` put at its name; returns where the folder went."""
    aside = folder.with_name(folder.name + ".aside")
    os.rename(folder, aside)
    os.symlink(target, folder, target_is_directory=True)
    return aside


def _closed(fd: int) -> bool:
    try:
        os.fstat(fd)
    except OSError as exc:
        return exc.errno == errno.EBADF
    return False


# ── the pin, portable ────────────────────────────────────────────────────────

def test_a_root_that_is_a_link_is_refused_unless_followed(tmp_path):
    folder, link = tmp_path / "folder", tmp_path / "link"
    folder.mkdir()
    link.symlink_to(folder, target_is_directory=True)
    with pytest.raises(root_pin.Swapped):
        root_pin.pin(link)
    followed = root_pin.pin(link, follow=True)         # a user's granted folder may be a link: resolved once, here
    try:
        assert followed.path == real(folder) and followed.identity == (folder.stat().st_dev, folder.stat().st_ino)
    finally:
        root_pin.release([followed])


def test_a_real_path_that_is_a_link_at_the_open_is_refused(tmp_path, monkeypatch):
    """A swap between the realpath and the open: `O_NOFOLLOW` refuses the link there."""
    folder, link = tmp_path / "folder", tmp_path / "link"
    folder.mkdir()
    link.symlink_to(folder, target_is_directory=True)
    resolve = os.path.realpath
    monkeypatch.setattr(root_pin.os.path, "realpath",
                        lambda p, *a, **k: str(link) if str(p) == str(folder) else resolve(p, *a, **k))
    with pytest.raises(root_pin.Swapped):
        root_pin.pin(folder)


def test_a_link_that_goes_while_it_is_resolved_is_refused(tmp_path, monkeypatch):
    """Python's realpath lstats a link, then reads it: a link gone between the two raises EINVAL, a swap too."""
    def racing(*args, **kwargs):
        raise OSError(errno.EINVAL, "Invalid argument")
    monkeypatch.setattr(root_pin.os.path, "realpath", racing)
    with pytest.raises(root_pin.Swapped):
        root_pin.pin(tmp_path)


@pytest.mark.parametrize("swap", ["link", "another folder", "gone", "a file"])
def test_the_check_before_the_spawn_refuses_a_root_that_isnt_the_pinned_folder(tmp_path, swap):
    folder, outside = tmp_path / "folder", tmp_path / "outside"
    folder.mkdir()
    outside.mkdir()
    pinned = root_pin.pin(folder)
    try:
        root_pin.check([pinned])                        # unchanged: fine
        aside = folder.with_name("aside")
        os.rename(folder, aside)
        if swap == "link":
            folder.symlink_to(outside, target_is_directory=True)
        elif swap == "another folder":
            folder.mkdir()
        elif swap == "a file":
            folder.write_text("x")
        with pytest.raises(root_pin.Swapped):
            root_pin.check([pinned])
    finally:
        root_pin.release([pinned])


def test_release_closes_the_descriptors(tmp_path):
    pins = [root_pin.pin(tmp_path)]
    fd = pins[0].fd
    assert fd is not None and not _closed(fd)
    root_pin.release(pins)
    assert _closed(fd) and pins[0].fd is None
    root_pin.release(pins)                              # twice is fine


def test_a_pinned_path_is_not_resolved_again_while_the_profile_is_built(tmp_path):
    folder, outside = tmp_path / "folder", tmp_path / "outside"
    folder.mkdir()
    outside.mkdir()
    pinned = root_pin.pin(folder)
    try:
        _swap_for_link(folder, outside)
        with root_pin.pinned([pinned]):
            assert real(folder) == pinned.path          # the pinned real path, as it is
        assert real(folder) == real(outside)            # outside the build: resolved as before
    finally:
        root_pin.release([pinned])


# ── an MCP server's folders ──────────────────────────────────────────────────

def test_an_mcp_servers_own_and_granted_folders_are_pinned_and_checked(home, tmp_path):
    """Its own folder and cache pinned, a granted link resolved once (the user may grant one); the profile names those
    real paths, and a swap after it is caught by the check before the start. The descriptors go with the file."""
    root, granted, outside = home / "data" / "srv", tmp_path / "granted", tmp_path / "outside"
    for folder in (root, granted, outside):
        folder.mkdir()
    (tmp_path / "grant").symlink_to(granted, target_is_directory=True)
    _, args, _, _ = capability_sandbox.wrap("/bin/echo", [], {}, {"root": str(root),
                                                                  "folders": [str(tmp_path / "grant")]})
    profile = command_sandbox.profile_path(args)
    pins = list(command_sandbox._PINS[str(profile)])
    try:
        assert [p.path for p in pins] == [real(root), real(root / "cache"), real(granted)]
        assert subpath(real(granted)) in profile.read_text()
        command_sandbox.check_pins(profile)
        _swap_for_link(granted, outside)
        with pytest.raises(root_pin.Swapped):
            command_sandbox.check_pins(profile)
    finally:
        command_sandbox.remove_profile(profile)
    assert all(p.fd is None for p in pins) and str(profile) not in command_sandbox._PINS


# ── the file tools ───────────────────────────────────────────────────────────

def test_the_file_tools_refuse_a_working_folder_that_is_a_link(tmp_path):
    work, outside = tmp_path / "work", tmp_path / "outside"
    work.mkdir()
    outside.mkdir()
    _swap_for_link(work, outside)
    with pytest.raises(workspace_paths.PathEscape, match="isn't the folder it was"):
        workspace_paths.resolve_in_workspace("notes.md", work, for_write=True)


def test_a_write_is_refused_when_the_working_folder_is_swapped_before_it(home, tmp_path, monkeypatch):
    """Resolved and identity-checked once; checked again right before the write. Swapped between the two, the write
    is refused and nothing lands outside."""
    work, outside = tmp_path / "work", tmp_path / "outside"
    work.mkdir()
    outside.mkdir()
    resolve = file_tools.resolve_in_workspace
    swapped = []

    def then_swap(*args, **kwargs):
        out = resolve(*args, **kwargs)
        if not swapped:
            aside = _swap_for_link(work, outside)
            swapped.append(aside)
            (aside / "notes.md").write_text("old")       # what the folder held
            (outside / "notes.md").write_text("outside")
        return out
    monkeypatch.setattr(file_tools, "resolve_in_workspace", then_swap)
    with pytest.raises(workspace_paths.PathEscape, match="isn't the folder it was"):
        file_tools._write_inside(work, work / "notes.md", "new")
    assert (outside / "notes.md").read_text() == "outside" and sorted(p.name for p in outside.iterdir()) == ["notes.md"]


# ── real seatbelt, through the real executor ─────────────────────────────────

@pytest.fixture
def roots(home, tmp_path, monkeypatch):
    """The work folder, the run's temp (always this folder, so a flipper can swap it) and an outside folder."""
    work, temp, outside = tmp_path / "work", tmp_path / "runtemp", tmp_path / "outside"
    for folder in (work, temp, outside):
        folder.mkdir()
    monkeypatch.setattr(run_temp, "folder", lambda key: temp)
    return {"work": work, "temp": temp, "outside": outside}


def _marks(roots, i: int) -> str:
    """A command that tries to write a marker in each root by its name, in its working folder, and straight into the
    outside folder (which only a profile that granted it would allow)."""
    return (f'printf x > "$TMPDIR/t-{i}" 2>/dev/null; printf x > "{roots["work"]}/w-{i}" 2>/dev/null; '
            f'printf x > ./c-{i} 2>/dev/null; printf x > "{roots["outside"]}/o-{i}" 2>/dev/null; :')


@pytest.mark.macos
@macos
@pytest.mark.parametrize("which", ["temp", "work"])
async def test_a_root_swapped_for_a_link_before_the_start_is_refused_with_the_note(roots, which):
    _swap_for_link(roots[which], roots["outside"])
    result = await terminal_exec.run(_marks(roots, 0), cwd=roots["work"], sandbox=True, offline=True)
    assert result["code"] == "root_swapped" and result["exit_code"] is None, result
    assert "Nothing ran" in result["note"]
    assert not list(roots["outside"].iterdir())
    assert command_sandbox._PINS == {}


@pytest.mark.macos
@macos
async def test_a_swap_between_the_profile_and_the_spawn_is_refused_and_the_pins_are_closed(roots, monkeypatch):
    built, pins = command_sandbox.wrapper, []
    pin = root_pin.pin

    def recording(*args, **kwargs):
        pins.append(pin(*args, **kwargs))
        return pins[-1]

    def then_swap(*args, **kwargs):
        prefix = built(*args, **kwargs)
        _swap_for_link(roots["temp"], roots["outside"])
        return prefix
    monkeypatch.setattr(root_pin, "pin", recording)
    monkeypatch.setattr(command_sandbox, "wrapper", then_swap)
    result = await terminal_exec.run(_marks(roots, 0), cwd=roots["work"], sandbox=True, offline=True)
    assert result["code"] == "root_swapped", result
    assert not list(roots["outside"].iterdir())
    assert pins and all(p.fd is None for p in pins) and command_sandbox._PINS == {}

    monkeypatch.setattr(command_sandbox, "wrapper", built)       # an ordinary run: started, and its pins closed
    os.unlink(roots["temp"])
    os.rename(roots["temp"].with_name("runtemp.aside"), roots["temp"])
    pins.clear()
    result = await terminal_exec.run("printf x > \"$TMPDIR/ok\"", cwd=roots["work"], sandbox=True, offline=True)
    assert result["ok"], result
    assert (roots["temp"] / "ok").exists()
    assert len(pins) >= 2 and all(p.fd is None for p in pins) and command_sandbox._PINS == {}


@pytest.mark.macos
@macos
async def test_a_swap_after_the_spawn_grants_no_other_folder(roots):
    """The honest limit, measured: seatbelt grants paths, so a command may replace its own (empty) temp folder with a
    link, but a write through that link is judged by where it points and refused. The run's next command is then
    refused at the start (the folder isn't the pinned one any more)."""
    swap = (f'rmdir "$TMPDIR" && ln -s "{roots["outside"]}" "$TMPDIR" && echo swapped; '
            'printf x > "$TMPDIR/after" 2>/dev/null; :')
    result = await terminal_exec.run(swap, cwd=roots["work"], sandbox=True, offline=True)
    assert result["exit_code"] == 0 and "swapped" in result["stdout"], result
    assert roots["temp"].is_symlink() and not list(roots["outside"].iterdir())
    again = await terminal_exec.run(_marks(roots, 1), cwd=roots["work"], sandbox=True, offline=True)
    assert again["code"] == "root_swapped" and not list(roots["outside"].iterdir()), again


@pytest.mark.macos
@macos
async def test_the_outside_floor_refuses_a_work_folder_swapped_before_the_start(roots):
    """The floor holds the run-later files in the work folder it pinned (HR-1), so that folder is pinned too."""
    _swap_for_link(roots["work"], roots["outside"])
    result = await terminal_exec.run(_marks(roots, 0), cwd=roots["work"], sandbox=False, offline=True,
                                     hold_run_later=True)
    assert result["code"] == "root_swapped" and result["sandbox"] == "outside", result
    assert not list(roots["outside"].iterdir()) and command_sandbox._PINS == {}


@pytest.mark.macos
@macos
async def test_run_python_refuses_its_folder_swapped_after_the_profile(home, tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    built, folders = code_sandbox.computation_profile, []

    def then_swap(python, workspace, *rest):
        text = built(python, workspace, *rest)
        folders.append(workspace)
        os.rename(workspace, tmp_path / "aside")
        os.symlink(outside, workspace, target_is_directory=True)
        return text
    monkeypatch.setattr(code_sandbox, "_env_cache", (sys.executable, "test-env"))
    monkeypatch.setattr(code_sandbox, "computation_profile", then_swap)
    try:
        result = await code_sandbox.run_python(f"open({str(outside / 'x')!r}, 'w').write('x')")
    finally:
        if folders and folders[0].is_symlink():
            os.unlink(folders[0])
    assert result["ok"] is False and "Nothing ran" in result["error"], result
    assert not list(outside.iterdir())


COMMANDS = 200
BATCH = 8


def _flip(folder: Path, outside: Path, stop: threading.Event, flips: list) -> None:
    """Swap `folder` for a link to `outside` and back, as fast as it can, until `stop`."""
    aside = folder.with_name(folder.name + ".aside")
    while not stop.is_set():
        os.rename(folder, aside)
        os.symlink(outside, folder, target_is_directory=True)
        os.unlink(folder)
        os.rename(aside, folder)
        flips[0] += 1


@pytest.mark.macos
@macos
@pytest.mark.parametrize("which", ["temp", "work"])
async def test_under_an_active_flipper_no_command_writes_outside(roots, which, record_property):
    """⓪Plan's measurement, as a test: N sandboxed commands while a flipper swaps the run's temp (or the work folder)
    for a link to an outside folder and back. Not one marker reaches the outside folder; how many starts the identity
    check refused is recorded."""
    stop, flips = threading.Event(), [0]
    flipper = threading.Thread(target=_flip, args=(roots[which], roots["outside"], stop, flips), daemon=True)
    outcomes, errors = {"ran": 0, "refused": 0, "failed": 0}, set()
    flipper.start()
    try:
        for start in range(0, COMMANDS, BATCH):
            results = await asyncio.gather(
                *(terminal_exec.run(_marks(roots, i), cwd=roots["work"], sandbox=True, offline=True, timeout_s=30)
                  for i in range(start, min(start + BATCH, COMMANDS))), return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    outcomes["failed"] += 1                 # e.g. the work folder gone at the spawn's chdir
                    errors.add(type(result).__name__)
                elif result.get("code") == "root_swapped":
                    outcomes["refused"] += 1
                else:
                    outcomes["ran"] += 1
    finally:
        stop.set()
        flipper.join(10)
    assert roots[which].is_dir() and not roots[which].is_symlink()
    escaped = sorted(p.name for p in roots["outside"].iterdir())
    commands = len({name.split("-", 1)[1] for name in escaped})
    for name, value in {**outcomes, "flips": flips[0], "escaped": len(escaped), "commands": commands}.items():
        record_property(name, value)
    print(f"\nSBX-9 race ({which}): {outcomes} {sorted(errors)}, flips {flips[0]}, "
          f"{len(escaped)} marker(s) outside from {commands} command(s)")
    assert flips[0] > 0 and sum(outcomes.values()) == COMMANDS, (outcomes, flips)
    assert escaped == [], f"{len(escaped)} marker(s) outside: {escaped[:10]} ({outcomes})"
    assert command_sandbox._PINS == {}

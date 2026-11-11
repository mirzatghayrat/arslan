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
import subprocess
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

def test_a_root_that_is_a_link_is_refused(tmp_path):
    folder, link = tmp_path / "folder", tmp_path / "link"
    folder.mkdir()
    link.symlink_to(folder, target_is_directory=True)
    with pytest.raises(root_pin.Swapped):
        root_pin.pin(link)


@pytest.mark.parametrize("portable", [False, True], ids=["nofollow-any", "walk-from-root"])
def test_a_link_in_any_component_of_the_real_path_is_refused_at_the_pin_and_the_check(tmp_path, monkeypatch,
                                                                                         portable):
    """Astra #855 P1: an ancestor of the pinned folder swapped for a link to where it went keeps the folder's identity;
    the open refuses it all the same (macOS `O_NOFOLLOW_ANY`, or the walk from `/` elsewhere)."""
    if portable:
        monkeypatch.setattr(root_pin, "_NOFOLLOW_ANY", 0)
    above, moved = tmp_path / "above", tmp_path / "moved"
    (above / "work").mkdir(parents=True)
    pinned = root_pin.pin(above / "work")
    try:
        os.rename(above, moved)
        os.symlink(moved, above, target_is_directory=True)        # same folder, reached through a link now
        with pytest.raises(root_pin.Swapped):
            root_pin.check([pinned])
        with pytest.raises(OSError):
            root_pin.open_folder(str(pinned.path))
    finally:
        root_pin.release([pinned])


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

def _mcp_grants(home, tmp_path):
    """An MCP server's folder, and grants: a real folder, then a file, a missing path and a link to a folder."""
    root, granted, outside = home / "data" / "srv", tmp_path / "granted", tmp_path / "outside"
    for folder in (root, granted, outside):
        folder.mkdir()
    (tmp_path / "file").write_text("x")
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)
    return root, granted, outside, {"file": tmp_path / "file", "missing": tmp_path / "missing",
                                    "link": tmp_path / "link"}


def test_an_mcp_servers_own_and_granted_folders_are_pinned_and_checked(home, tmp_path):
    """Its own folder, its cache and a granted folder pinned; the profile names those real paths, and a swap after it
    is caught by the check before the start. The descriptors go with the file."""
    root, granted, outside, _ = _mcp_grants(home, tmp_path)
    _, args, _, _ = capability_sandbox.wrap("/bin/echo", [], {}, {"root": str(root), "folders": [str(granted)]})
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


@pytest.mark.parametrize("kind", ["file", "missing", "link"])
def test_an_unpinnable_mcp_grant_is_left_out_of_the_profile(home, tmp_path, kind):
    """Astra #855 P1: a grant that can't be pinned (a file, a missing path, a link) is omitted: not pinned, and not
    passed to the profile by its name to be resolved later. The pinned grant beside it stays."""
    root, granted, outside, unpinnable = _mcp_grants(home, tmp_path)
    grant = unpinnable[kind]
    _, args, _, _ = capability_sandbox.wrap("/bin/echo", [], {}, {"root": str(root),
                                                                  "folders": [str(grant), str(granted)]})
    profile = command_sandbox.profile_path(args)
    try:
        assert [p.path for p in command_sandbox._PINS[str(profile)]] == [real(root), real(root / "cache"),
                                                                         real(granted)]
        text = profile.read_text()
        assert str(grant) not in text and str(real(outside)) not in text and subpath(real(granted)) in text
    finally:
        command_sandbox.remove_profile(profile)


@pytest.mark.macos
@macos
def test_missing_mcp_grant_cannot_become_unpinned_write_allow(home, tmp_path, monkeypatch):
    """Astra #855's probe: a grant missing when it is pinned becomes a link to an outside folder before the profile is
    built (the race). It was left out, so on real seatbelt nothing is written outside, through the link or straight
    there; the pinned grant beside it is written."""
    root, granted, outside, unpinnable = _mcp_grants(home, tmp_path)
    missing = unpinnable["missing"]
    pin = root_pin.pin

    def racing(name):
        try:
            return pin(name)
        except root_pin.Swapped:
            if Path(name) == missing:
                os.symlink(outside, missing, target_is_directory=True)  # it appears, as a link, right after the pin
            raise
    monkeypatch.setattr(root_pin, "pin", racing)
    _, args, _, cwd = capability_sandbox.wrap("/usr/bin/touch", [], {}, {"root": str(root),
                                                                         "folders": [str(missing), str(granted)]})
    profile = command_sandbox.profile_path(args)
    try:
        runs = [subprocess.run([capability_sandbox.SANDBOX_EXEC, "-f", str(profile), "/usr/bin/touch", str(target)],
                               cwd=cwd, capture_output=True)
                for target in (missing / "through", outside / "straight", granted / "marker")]
    finally:
        command_sandbox.remove_profile(profile)
    assert missing.is_symlink() and runs[0].returncode != 0 and runs[1].returncode != 0, runs
    assert not list(outside.iterdir())
    assert runs[2].returncode == 0 and (granted / "marker").exists(), runs[2].stderr


def test_a_plugin_hooks_temp_swapped_for_a_link_is_refused_before_its_profile(home, tmp_path):
    """HOOK-2's runner pins the hook's temp, its one writable folder, as the commands do."""
    from server.services import plugin_hook_runner
    temp, outside = tmp_path / "hooktemp", tmp_path / "outside"
    temp.mkdir()
    outside.mkdir()
    _swap_for_link(temp, outside)
    with pytest.raises(root_pin.Swapped):
        plugin_hook_runner._prefix(temp, tmp_path, tmp_path, ())
    assert command_sandbox._PINS == {}


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
    pin = workspace_paths.pin_root(work)
    try:
        with pytest.raises(workspace_paths.PathEscape, match="isn't the folder it was"):
            file_tools._write_inside(pin, work / "notes.md", "new")
    finally:
        root_pin.release([pin])
    assert (outside / "notes.md").read_text() == "outside" and sorted(p.name for p in outside.iterdir()) == ["notes.md"]


def _file_tools(monkeypatch, work: Path):
    async def workspace():
        return work
    monkeypatch.setattr(file_tools, "_workspace_root", workspace)
    return file_tools.WriteFileExecutor().execute, file_tools.EditFileExecutor().execute


def _after_resolution(monkeypatch, action):
    """`action()` once, right after the tool's resolution (at its snapshot, before any folder is made or written)."""
    snapshot, done = file_tools._snapshot_write, []

    def then(root, path, content):
        if not done:
            done.append(action())
        return snapshot(root, path, content)
    monkeypatch.setattr(file_tools, "_snapshot_write", then)
    checkpoint = file_tools.checkpoints.ensure

    async def first(*args, **kwargs):
        if not done:
            done.append(action())
        return await checkpoint(*args, **kwargs)
    monkeypatch.setattr(file_tools.checkpoints, "ensure", first)


async def test_one_file_write_acquires_one_root_pin(home, tmp_path, monkeypatch):
    """Astra #855 P1: one pin from the resolution through the folders to the write, for write_file and edit_file."""
    work = tmp_path / "work"
    work.mkdir()
    write, edit = _file_tools(monkeypatch, work)
    pin, pins = root_pin.pin, []

    def counting(*args, **kwargs):
        pins.append(pin(*args, **kwargs))
        return pins[-1]
    monkeypatch.setattr(root_pin, "pin", counting)
    assert (await write({"path": "a/b/notes.md", "content": "one"}))["ok"]
    assert len(pins) == 1 and pins[0].fd is None
    assert (await edit({"path": "a/b/notes.md", "old_string": "one", "new_string": "two"}))["ok"]
    assert len(pins) == 2 and pins[1].fd is None
    assert (work / "a" / "b" / "notes.md").read_text() == "two"


@pytest.mark.parametrize("tool", ["write", "edit"])
async def test_a_file_write_never_resolves_the_pinned_root_again(home, tmp_path, monkeypatch, tool):
    """Astra #855 delta: the pinned root is its own real path; a write at the root's top level (where the parent
    probe is the root itself) must not resolve it again, in the resolution or in _write_inside."""
    work = tmp_path / "work"
    work.mkdir()
    (work / "notes.md").write_text("one")
    write, edit = _file_tools(monkeypatch, work)
    real_work = Path(os.path.realpath(work))
    resolve, roots = Path.resolve, []

    def watching(self, *args, **kwargs):
        if self == real_work:
            roots.append(self)
        return resolve(self, *args, **kwargs)
    monkeypatch.setattr(Path, "resolve", watching)
    if tool == "write":
        result = await write({"path": "notes.md", "content": "two"})
    else:
        result = await edit({"path": "notes.md", "old_string": "one", "new_string": "two"})
    assert result["ok"] and (work / "notes.md").read_text() == "two"
    assert roots == []


@pytest.mark.parametrize("tool", ["write", "edit"])
async def test_replaced_root_between_resolution_and_write_is_refused(home, tmp_path, monkeypatch, tool):
    """Astra #855 P1: the working folder renamed away and a new one put at its path after the resolution: the write
    compares against the identity the resolution pinned, so it is refused, and neither folder is written."""
    work, old = tmp_path / "work", tmp_path / "old"
    work.mkdir()
    (work / "notes.md").write_text("one")
    write, edit = _file_tools(monkeypatch, work)

    def replace():
        os.rename(work, old)
        work.mkdir()
    _after_resolution(monkeypatch, replace)
    if tool == "write":
        out = await write({"path": "notes.md", "content": "two"})
    else:
        out = await edit({"path": "notes.md", "old_string": "one", "new_string": "two"})
    assert out["ok"] is False and "isn't the folder it was" in out["error"], out
    assert list(work.iterdir()) == [] and (old / "notes.md").read_text() == "one"


async def test_root_ancestor_link_after_validation_is_refused(home, tmp_path, monkeypatch):
    """Astra #855 P1: after the resolution, a folder ABOVE the working folder is moved and a link to where it went put
    at its name. The working folder keeps its identity, but its path now runs through a link: the write is refused
    (as before SBX-9), and nothing lands in the relocated original."""
    above, moved = tmp_path / "above", tmp_path / "moved"
    work = above / "work"
    work.mkdir(parents=True)
    write, _ = _file_tools(monkeypatch, work)

    def relink():
        os.rename(above, moved)
        os.symlink(moved, above, target_is_directory=True)
    _after_resolution(monkeypatch, relink)
    out = await write({"path": "sub/notes.md", "content": "x"})
    assert out["ok"] is False, out
    assert list((moved / "work").iterdir()) == []


async def test_root_ancestor_link_under_a_flipper_writes_only_where_the_path_has_no_link(home, tmp_path, monkeypatch):
    """The same swap, over and over, from another process, while 200 writes run: every write is either refused or
    lands in the working folder, and nothing is made anywhere else."""
    above = tmp_path / "above"
    work = above / "work"
    work.mkdir(parents=True)
    write, _ = _file_tools(monkeypatch, work)
    stop, done = tmp_path / "stop", {"ok": 0, "refused": 0}
    # The link points at where the folder goes (`above.aside`): the relocated original.
    flipper = subprocess.Popen([sys.executable, "-c", _FLIPPER, str(above), str(above) + ".aside", str(stop)],
                               stdout=subprocess.PIPE, text=True)
    try:
        for i in range(COMMANDS):
            out = await write({"path": f"d{i}/notes.md", "content": "x"})
            done["ok" if out["ok"] else "refused"] += 1
    finally:
        stop.write_text("")
        flips = int(flipper.communicate(timeout=30)[0] or 0)
    print(f"\nSBX-9 ancestor flipper: {done}, flips {flips}")
    written = sorted(p.parent.name for p in work.glob("d*/notes.md"))
    assert flips > 0 and not above.is_symlink() and len(written) == done["ok"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["above", "home", "stop", "t"]


#: A flipper in its own process (no GIL shared with the writer): swaps argv[1] for a link to argv[2] and back until the
#: file argv[3] exists, then prints how many times. A writer may make a folder at the name in the gap between the two
#: renames: that one is removed (it is inside the work folder) and the original put back.
_FLIPPER = """
import os, shutil, sys
folder, outside, stop = sys.argv[1:4]
aside, flips = folder + ".aside", 0
while not os.path.exists(stop) or os.path.lexists(aside):
    try:
        os.rename(folder, aside)
        os.symlink(outside, folder)
        os.unlink(folder)
    except OSError:
        pass
    if os.path.lexists(aside):
        if os.path.islink(folder):
            os.unlink(folder)
        elif os.path.isdir(folder):
            shutil.rmtree(folder, ignore_errors=True)
        try:
            os.rename(aside, folder)
        except OSError:
            pass
    flips += 1
print(flips)
"""


async def test_write_file_under_an_active_flipper_makes_no_folder_outside(home, tmp_path, monkeypatch):
    """⓪Plan: `write_file` into a new nested path while a folder on the way is swapped for a link to an outside folder
    and back. Its folders are made from the working folder's descriptor (mkdirat, O_NOFOLLOW opens), so none is made
    outside and no file lands there. Repeated 200 times."""
    work, outside = tmp_path / "work", tmp_path / "outside"
    (work / "a").mkdir(parents=True)
    outside.mkdir()

    async def workspace():
        return work
    monkeypatch.setattr(file_tools, "_workspace_root", workspace)
    write = file_tools.WriteFileExecutor().execute
    stop, results = tmp_path / "stop", {"ok": 0, "refused": 0}
    flipper = subprocess.Popen([sys.executable, "-c", _FLIPPER, str(work / "a"), str(outside), str(stop)],
                               stdout=subprocess.PIPE, text=True)
    try:
        for i in range(COMMANDS):
            out = await write({"path": f"a/b{i}/c/f.txt", "content": "x"})
            results["ok" if out["ok"] else "refused"] += 1
    finally:
        stop.write_text("")
        flips = int(flipper.communicate(timeout=30)[0] or 0)
    made = sorted(str(p.relative_to(outside)) for p in outside.rglob("*"))
    print(f"\nSBX-9 write_file race: {results}, flips {flips}, {len(made)} entr(ies) outside")
    assert flips > 0 and (work / "a").is_dir() and not (work / "a").is_symlink()
    assert made == [], f"{len(made)} made outside: {made[:10]} ({results})"


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

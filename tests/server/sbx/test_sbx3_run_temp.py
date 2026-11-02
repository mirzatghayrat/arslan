"""SBX-3 §1a (v0.1.64): each run's own temp folder (`run_temp`), handed to its commands as TMPDIR.

- Two runs get different folders: 0700, under the per-user temp folder, outside every protected root.
- Every command of a run shares the run's folder. A command outside any run gets one of its own that
  goes with it.
- The folder goes when the run ends, including after a time limit or a cancel. It stays while a process a
  command left running is alive, and the next start's sweep removes it after.
- The commands profile writes that folder as temp, and no longer the shared per-user parent,
  /private/tmp or /private/var/tmp.

That a sandboxed command cannot write the shared temp folders is a deny, so it is SBX-3p's (Codex's).
Here the only real-seatbelt test checks that a command can use its own TMPDIR.
"""
import asyncio
import os
import signal
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from server.services import command_sandbox, execution_context, host_run, run_temp, terminal_exec

macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")


@pytest.fixture(autouse=True)
def fresh():
    run_temp._reset_for_tests()
    yield
    for path in list(run_temp._folders.values()):
        run_temp._remove(path)
    run_temp._reset_for_tests()


async def _env(command: str, cwd: Path, **kw) -> dict:
    return await terminal_exec.run(command, cwd=cwd, **kw)


async def _reaped(path: Path, seconds: int = 30) -> None:
    """Until every process group recorded for `path` is gone. A killed process still counts until the kernel
    has reaped it, which takes longer under load; `finish` keeps the folder until then, by design."""
    for _ in range(seconds * 10):
        if not any(run_temp._alive(group) for group in run_temp._groups(path)):
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"a process group of {path} was never reaped")


# ── where it is ──────────────────────────────────────────────────────────────

def test_two_runs_get_their_own_folder_outside_every_protected_root():
    one, two = run_temp.folder(1), run_temp.folder(2)
    assert one != two and one.parent == two.parent == run_temp.root()
    assert stat.S_IMODE(one.stat().st_mode) == stat.S_IMODE(two.stat().st_mode) == 0o700
    assert run_temp.root().parent == command_sandbox._real(tempfile.gettempdir())
    assert not command_sandbox._inside(run_temp.root(), command_sandbox.default_protected())
    assert run_temp.folder(1) == one                                   # the same run keeps its folder


def test_each_data_folder_has_its_own_root(tmp_path, monkeypatch):
    """Two Arslan instances never sweep each other's runs."""
    from server import config
    one = run_temp.root()
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path / "other-data")
    assert run_temp.root() != one and run_temp.root().parent == one.parent


async def test_the_commands_of_a_run_share_its_folder_as_tmpdir(tmp_path):
    with execution_context.bind_run(5):
        first = await _env('printf "%s\\n%s" "$TMPDIR" "$TMPPREFIX"', tmp_path)
        second = await _env('printf "%s" "$TMPDIR"', tmp_path)
    tmpdir, prefix = first["stdout"].splitlines()
    assert tmpdir == second["stdout"] == str(run_temp.folder(5))
    assert prefix.startswith(tmpdir + os.sep)                          # zsh's here-documents land there too


async def test_a_command_outside_any_run_gets_a_folder_that_goes_with_it(tmp_path):
    result = await _env('printf "%s" "$TMPDIR"; touch "$TMPDIR/left"', tmp_path)
    own = Path(result["stdout"])
    assert own.parent == run_temp.root() and not own.exists()


# ── when it goes ─────────────────────────────────────────────────────────────

async def test_the_folder_goes_when_the_run_ends(tmp_path):
    with execution_context.bind_run(6):
        await _env('touch "$TMPDIR/x"', tmp_path)
    path = run_temp.folder(6)
    assert (path / "x").exists()
    run_temp.finish(6)
    assert not path.exists() and not run_temp._record(path).exists()


@pytest.mark.parametrize("ending", ["done", "error", "cancel"])
async def test_a_runs_folder_goes_when_the_run_ends_however_it_ends(execution_db, tmp_path, ending):
    seen = {}

    async def body(emit):
        out = await _env('printf "%s" "$TMPDIR"; touch "$TMPDIR/x"', tmp_path)
        seen["folder"] = Path(out["stdout"])
        assert (seen["folder"] / "x").exists()
        if ending == "error":
            raise RuntimeError("boom")
        if ending == "cancel":
            raise asyncio.CancelledError
        return "ok"
    try:
        await host_run.execute("conv-sbx3", "x", lambda e: None, body)
    except (RuntimeError, asyncio.CancelledError):
        pass
    assert seen["folder"].parent == run_temp.root() and not seen["folder"].exists()


async def test_a_time_limit_or_a_cancel_leaves_nothing_behind(tmp_path):
    with execution_context.bind_run(8):
        timed = await _env("sleep 30", tmp_path, timeout_s=1)
        assert timed["code"] == "time_limit"
        task = asyncio.ensure_future(_env("sleep 30", tmp_path))
        await asyncio.sleep(0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    path = run_temp.folder(8)
    await _reaped(path)                                                # both groups were killed
    run_temp.finish(8)
    assert not path.exists()


async def test_a_process_left_running_keeps_the_folder_until_the_sweep_after_it(tmp_path):
    with execution_context.bind_run(7):
        await _env("sleep 30 >/dev/null 2>&1 &", tmp_path)
    path = run_temp.folder(7)
    run_temp.finish(7)
    assert path.exists()                                               # its child is still running
    assert run_temp.sweep() == 0 and path.exists()
    for group in run_temp._groups(path):
        os.killpg(group, signal.SIGKILL)
    await _reaped(path)
    assert run_temp.sweep() == 1 and not path.exists()


def test_the_sweep_removes_only_what_is_over():
    base = run_temp.root()
    base.mkdir(mode=0o700, exist_ok=True)
    done = subprocess.Popen(["true"], start_new_session=True)
    done.wait()
    over, held, foreign = (Path(tempfile.mkdtemp(dir=base)) for _ in range(3))
    run_temp._record(over).write_text(f"{done.pid}\n")
    run_temp._record(held).write_text(f"{os.getpgrp()}\n")              # this test's own group: alive
    run_temp._record(foreign).write_text("1\n")                        # not ours to signal: taken as alive
    stray = base / "run-gone-x.groups"
    stray.write_text("1\n")
    live = run_temp.folder(9)                                          # a run of this start
    try:
        assert run_temp.sweep() == 1
        assert not over.exists() and held.exists() and foreign.exists() and live.exists()
        assert not stray.exists()
    finally:
        run_temp._remove(held)
        run_temp._remove(foreign)



def test_the_sweep_leaves_a_link_in_the_root_and_what_it_points_to(tmp_path):
    """A link in the runs' root is never a run's folder: the sweep neither follows nor counts it."""
    base = run_temp.root()
    base.mkdir(mode=0o700, exist_ok=True)
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "keep.txt").write_text("x")
    link = base / "run-link-test"
    link.symlink_to(target, target_is_directory=True)
    try:
        assert run_temp.sweep() == 0
        assert link.is_symlink() and (target / "keep.txt").read_text() == "x"
    finally:
        link.unlink()

# ── what the profile writes ──────────────────────────────────────────────────

def test_the_commands_profile_writes_the_runs_folder_not_the_shared_temp(tmp_path):
    temp = run_temp.folder(3)
    roots = command_sandbox.writable_roots(tmp_path, temp=temp)
    assert [r.path for r in roots if r.tag == "in_scope"] == [str(tmp_path.resolve()), str(temp)]
    text = command_sandbox.commands_profile(tmp_path, temp=temp)
    writes = next(line for line in text.splitlines() if line.startswith("(allow file-write* (subpath"))
    assert f'(subpath "{temp}")' in writes
    user = command_sandbox._real(tempfile.gettempdir())
    for shared in (user.parent if user.name == "T" else user, Path("/private/tmp"), Path("/private/var/tmp")):
        assert f'(subpath "{shared}")' not in writes


# ── what should run does run (macOS) ─────────────────────────────────────────

@pytest.mark.macos
@macos
async def test_a_sandboxed_command_uses_its_own_tmpdir(tmp_path):
    with execution_context.bind_run(4):
        result = await _env("python3 -c 'import tempfile; f = tempfile.NamedTemporaryFile(delete=False); "
                            "f.write(b\"x\"); print(f.name)'", tmp_path, sandbox=True)
    assert result["sandbox"] == "workspace" and result["ok"], result
    assert Path(result["stdout"].strip()).parent == run_temp.folder(4)

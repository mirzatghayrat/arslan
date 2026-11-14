"""HR-1 review delta 11 (v0.1.64) under real seatbelt: links at held names past the held-folder cap.

Codex's case (#813, at c3524821): with 200 or 1,000 links at held names, the held-folder cap (`WALK_HELD`,
`WALK_HELD_BYTES`) tripped, the walk stopped, and the by-name fallback can't name a link's target with an ordinary
name, so those targets stayed writable. The fix: links are outside that cap (every one the walk sees has its
target's held names denied, and the target held in place), with their own cap, `WALK_LINKS`, past which no profile
is built and nothing starts in the sandbox. The profile goes to sandbox-exec as a file (`-f`). Measured here in the
commands preset, an MCP server's granted folder and the outside floor that holds them; each layout also has more
held folders than `WALK_HELD`, so the held-folder cap trips as well.

`WALK_LINKS` is 256, not ⓪Plan's 4,096: sandbox-exec's own compile time grows with the square of the profile (about
1 s for 200 links, 10 s for 600) and it refuses one past about 800 (run_later.py has the numbers). So 1,000 links,
held in review 10's terms, now fail closed, like 4,097.

Stand-in names and plain paths only.
"""
import json
import os
import subprocess
import sys
import time

import pytest

from server.services import command_sandbox, run_later
from tests.server.sbx.test_hr1_run_later_aliases import _OPS, PRESETS, STAND_IN, _folder, _profile

macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")

#: More held folders than WALK_HELD (two each), so the held-folder cap trips whatever the links do.
REPOSITORIES = run_later.WALK_HELD // 2 + 22


def _lay_out(folder, links: int) -> None:
    for i in range(REPOSITORIES):
        git = folder / f"{STAND_IN}-r{i:04}" / ".git"
        for name in ("hooks", "objects", "refs"):          # HR-1c: what git takes for a repository, so D answers
            (git / name).mkdir(parents=True)
        (git / "HEAD").write_text("ref: refs/heads/main\n")
    for i in range(links):
        target = folder / f"{STAND_IN}-l{i:04}" / "vsc"            # an ordinary name
        target.mkdir(parents=True)
        for name in ("settings.json", "other.json"):
            (target / name).write_text("old")
        (target.parent / ".vscode").symlink_to("vsc")


def _run(sbx, folder, steps, text) -> tuple[list[str], float]:
    """`steps` under `text`, delivered as the product delivers it (a file, `sandbox-exec -f`), and the run's time."""
    with pytest.MonkeyPatch.context() as environment:
        environment.setenv("ARSLAN_DATA_DIR", sbx.env["ARSLAN_DATA_DIR"])
        path = command_sandbox.write_profile(text)
    started = time.perf_counter()
    try:
        ran = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(path), sys.executable, "-I", "-c", _OPS, str(folder),
                              json.dumps(steps)], cwd=sbx.work, env=sbx.env, capture_output=True, text=True,
                             timeout=300)
    finally:
        command_sandbox.remove_profile(path)
    assert ran.returncode == 0, ran.stderr
    return json.loads(ran.stdout), time.perf_counter() - started


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", PRESETS, indirect=True)
@pytest.mark.parametrize("links", [200, run_later.WALK_LINKS])
def test_links_at_held_names_past_the_held_folder_cap_have_their_targets_held(sbx, links, record_property):
    """Every link's target: its held names refused and unchanged, the target held in place; an ordinary file beside
    them written. The profile builds and starts in a bounded time (generous: the measured times are in the PR)."""
    folder = _folder(sbx)
    _lay_out(folder, links)
    assert not run_later.held_folders([folder]).complete                  # the held-folder cap trips
    started = time.perf_counter()
    text = _profile(sbx)
    built = time.perf_counter() - started
    steps = [["write", f"{STAND_IN}-l{i:04}/vsc/settings.json"] for i in range(links)]
    steps += [["rename", f"{STAND_IN}-l{links - 1:04}/vsc", f"{STAND_IN}-moved"],
              ["write", f"{STAND_IN}-l0000/vsc/other.json"]]
    outcomes, ran = _run(sbx, folder, steps, text)
    record_property("profile_bytes", len(text.encode()))
    record_property("build_seconds", round(built, 3))
    record_property("run_seconds", round(ran, 3))
    assert built < 60 and ran < 60 and len(text.encode()) > 1 << 17     # well past where review 10's cap stopped
    assert outcomes == ["refused"] * (links + 1) + ["done"]
    assert all((folder / f"{STAND_IN}-l{i:04}" / "vsc" / "settings.json").read_text() == "old" for i in range(links))


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", PRESETS, indirect=True)
@pytest.mark.parametrize("links", [run_later.WALK_LINKS + 1, 1000, 4097])
def test_past_the_link_cap_no_profile_is_built(sbx, links):
    """Past `WALK_LINKS` links at held names: the preset builds no profile (`TooManyLinks`), so nothing starts."""
    _lay_out(_folder(sbx), links)
    with pytest.raises(run_later.TooManyLinks):
        _profile(sbx)


@pytest.mark.macos
@macos
async def test_past_the_link_cap_a_command_doesnt_start_and_no_file_is_left(tmp_path):
    """The product path: in the sandbox and under the floor that holds them, the command doesn't run and the note says
    why; no profile file is left."""
    from server.services import terminal_exec
    work = tmp_path / "work"
    work.mkdir()
    _lay_out(work, run_later.WALK_LINKS + 1)
    before = set(os.listdir(command_sandbox.profile_folder()))
    for result in (await terminal_exec.run(f"touch {STAND_IN}-ran", cwd=work, sandbox=True, offline=True),
                   await terminal_exec.run(f"touch {STAND_IN}-ran", cwd=work, offline=True, hold_run_later=True)):
        assert result["code"] == "too_many_links", result
        assert f"more than {run_later.WALK_LINKS:,} links" in result["note"], result
        assert not (work / f"{STAND_IN}-ran").exists()
    assert set(os.listdir(command_sandbox.profile_folder())) == before

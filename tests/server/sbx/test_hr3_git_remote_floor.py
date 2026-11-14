"""HR-3's residual git config writer under the outside floor, with real seatbelt (through SBX's harness, under a
scratch HOME).

Adding a remote writes the repository's .git/config, but the text reader reads `git remote` as a read, on purpose
(`terminal_policy._GIT_READS`; the shapes corpus keeps it as the residual row `residuals-git-remote`), so outside the
sandbox no card names that file. Under this conversation's outside grant with no click on the command's own card,
HR-1's floor (`command_sandbox.minimal_profile(run_later_in=...)`) is what holds it: that row's command is refused,
.git/config stays byte-identical, and the model reads the floor's note. Control: the same floor without the hold, as
a command runs with the sandbox switched off, lets the same write land (the documented residual), so the test can see
a write.

Stand-in names and plain git steps only.
"""
import sys

import pytest

from server.services import command_sandbox, terminal_exec
from tests.server.sbx.test_hr1_run_later_kernel import STAND_IN, _floor_profile, _git

macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")

#: The shapes corpus's `residuals-git-remote` row, word for word.
ADD_REMOTE = f"git remote add {STAND_IN} {STAND_IN}-source"
#: The floor's own sentence in the note (`terminal_exec.explain` with `hold`): only a click on its own card lifts it.
FLOOR_SENTENCE = "without the user's click on its own card, change files that make something run later"


def _url(repo) -> str | None:
    found = _git(repo, "config", "--get", f"remote.{STAND_IN}.url")
    return found.stdout.strip() if found.returncode == 0 else None


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["outside-floor"], indirect=True)
def test_under_the_outside_floor_adding_a_remote_leaves_the_config_byte_identical(sbx):
    assert _git(sbx.work, "init", "-q", "-b", "main").returncode == 0     # made outside: init writes .git/config
    config = sbx.work / ".git" / "config"
    before = config.read_bytes()
    ran = sbx.run(["/bin/bash", "-p", "-c", ADD_REMOTE], probe="hr3-floor-remote-add", profile=_floor_profile(sbx))
    assert ran.returncode != 0, ran.stderr
    assert config.read_bytes() == before and _url(sbx.work) is None
    result = {"ok": False, "exit_code": ran.returncode, "stdout": ran.stdout, "stderr": ran.stderr,
              "cwd": str(sbx.work), "sandbox": "outside", "error": f"exit code {ran.returncode}"}
    terminal_exec.explain(result, cwd=sbx.work, closed=[], mode="outside", timed_out=False, command=ADD_REMOTE,
                          hold=True)
    assert FLOOR_SENTENCE in result.get("note", ""), result
    # Control: the same floor without the hold, as with the sandbox switched off, lets the same write land.
    landed = sbx.run(["/bin/bash", "-p", "-c", ADD_REMOTE], probe="hr3-floor-remote-add-unheld")
    assert landed.returncode == 0, landed.stderr
    assert _url(sbx.work) == f"{STAND_IN}-source" and config.read_bytes() != before

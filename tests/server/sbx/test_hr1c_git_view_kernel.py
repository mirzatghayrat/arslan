"""HR-1c, D (v0.1.64) under real seatbelt: git's own view around one command in the commands preset, without the
grant (through SBX's harness, under a scratch HOME).

The kernel allows these writes (no held path names them: the residual D covers): hooks written into a bare repository
and into a nested submodule's git folder are quarantined by D, the sample beside them left; a new `.git` file pointing
at a repository prepared in the temp folder is renamed aside, and the hook outside is left where it is. (A hook
written through an existing `.git` link is refused by the kernel itself since #813's review 10, `link_filters`; D's
unit test covers it in tests/server/test_hr1c_git_view.py.)

Stand-in names and plain git steps only; the adversarial shapes are Codex's corpus.
"""
import os
import sys

import pytest

from server.services import command_sandbox, git_config_guard
from tests.server.sbx.test_hr1_run_later_kernel import STAND_IN, _git

macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")


def _checked(sbx, script: str, probe: str):
    """One command in the commands profile, without the grant, between D's snapshot and restore."""
    saved = git_config_guard.snapshot(sbx.work, grant=False, view=True)
    ran = sbx.run(["/bin/bash", "-p", "-c", script], probe=probe)
    return ran, git_config_guard.restore(saved)


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
def test_d_quarantines_hooks_the_kernels_names_cant_see(sbx, tmp_path, monkeypatch):
    monkeypatch.setattr(git_config_guard, "QUARANTINE", tmp_path / "quarantine")
    for args in (["init", "-q", "--bare", f"{STAND_IN}.git"], ["init", "-q", "nested"],
                 ["init", "-q", "--bare", "nested/.git/modules/a/modules/b"]):
        assert _git(sbx.work, *args).returncode == 0
    hooks = [f"{STAND_IN}.git/hooks/post-update", "nested/.git/modules/a/modules/b/hooks/post-checkout",
             f"{STAND_IN}.git/hooks/{STAND_IN}.sample"]
    script = "".join(f"printf '#!/bin/sh\\n' > {name} && chmod +x {name} && " for name in hooks) + "echo written"
    ran, outcome = _checked(sbx, script, "hr1c-d-hooks")
    assert ran.returncode == 0 and ran.stdout.strip() == "written", ran.stderr
    assert sorted(outcome.quarantined) == ["post-checkout", "post-update"], outcome.message()
    assert [(sbx.work / name).exists() for name in hooks] == [False, False, True]
    assert outcome.moved == outcome.aside == outcome.unanswered == []


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
def test_d_renames_aside_a_new_git_file_pointing_outside(sbx, tmp_path, monkeypatch):
    monkeypatch.setattr(git_config_guard, "QUARANTINE", tmp_path / "quarantine")
    prepared = sbx.temp / f"{STAND_IN}.git"
    script = (f"mkdir -p {prepared}/objects {prepared}/refs {prepared}/hooks fresh && "
              f"printf 'ref: refs/heads/main\\n' > {prepared}/HEAD && printf '#!/bin/sh\\n' > {prepared}/hooks/pre-commit"
              f" && printf 'gitdir: {prepared}\\n' > fresh/.git && echo written")
    ran, outcome = _checked(sbx, script, "hr1c-d-git-file")
    assert ran.returncode == 0 and ran.stdout.strip() == "written"
    assert outcome.aside == [os.path.join("fresh", ".git")] and outcome.quarantined == []
    assert not (sbx.work / "fresh" / ".git").exists() and (prepared / "hooks" / "pre-commit").exists()
    assert "renamed aside" in outcome.message()

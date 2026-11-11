"""HR-1b (v0.1.64) under real seatbelt: git's flow under this conversation's git_config grant, and git's sample hooks.

In the commands preset (the product's `commands_profile`, through SBX's harness, under a scratch HOME), with the grant
(`git_config_ok=True`, terminal_exec's template-free environment, and git_config_guard's snapshot before and restore
after, as terminal_exec runs them): clone, init, a tracking checkout, `push -u`, `--set-upstream-to`, `remote add`
and `config user.name` all work, on a bare origin kept in the work folder; a `core.hooksPath` set in the sandbox is
put back afterwards. The hooks stay held under the grant, the hooks folder itself included. Without the grant the
flow is #813's (tests/server/sbx/test_hr1_run_later_kernel.py, unchanged). git's sample hooks may be written in the
sandbox; renaming one to an exact hook name is refused, and a link at a hook name turns that exemption off for the run
(⓪Plan's ruling: it is an alias, as #813's node_modules rule has it).

Stand-in names and plain git steps only; the adversarial config shapes are Codex's corpus.
"""
import json
import os
import sys

import pytest

from server.services import command_sandbox, git_config_guard, terminal_exec
from tests.server.sbx.test_hr1_run_later_kernel import (FLOW_MEASURED, STAND_IN, _git, _out, _seed, _upstream,
                                                        _write)

macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")
VALUE = f"{STAND_IN}-hooks"


def _granted(sbx, script: str, probe: str):
    """One command as terminal_exec runs it under the grant: snapshot, the lifted profile and environment, restore."""
    saved = git_config_guard.snapshot(sbx.work)
    sbx.env.update(terminal_exec.GIT_CONFIG_ENV)
    try:
        ran = sbx.run(["/bin/bash", "-p", "-c", script], probe=probe, profile=sbx.profile(git_config_ok=True))
    finally:
        for name in terminal_exec.GIT_CONFIG_ENV:
            sbx.env.pop(name, None)
    return ran, git_config_guard.restore(saved)


#: Each step under the grant, in this order on `_seed`'s clone (`repo`), and how to read its effect afterwards.
GRANTED_FLOW = [
    ("clone", "git clone -q origin.git cloned"),
    ("init", "git init -q fresh"),
    ("checkout -b x origin/x", "cd repo && git checkout -q -b x origin/x"),
    ("switch -c y", "cd repo && git switch -q -c y"),
    ("push -u origin y", "cd repo && git push -q -u origin y"),
    ("branch --set-upstream-to", "cd repo && git branch -q --set-upstream-to=origin/x"),
    ("remote add", "cd repo && git remote add other ../origin.git"),
    ("config user.name", f"cd repo && git config user.name {STAND_IN}"),
    ("config core.hooksPath", f"cd repo && git config core.hooksPath {VALUE}"),
]


def _effect(work, step: str) -> str:
    repo, origin = work / "repo", work / "origin.git"
    if step == "clone":
        cloned = work / "cloned"
        return "yes" if _out(cloned, "rev-parse", "--verify", "-q", "origin/x") and _upstream(cloned, "main") else "no"
    if step == "init":
        return "yes" if _out(work / "fresh", "rev-parse", "--git-dir") else "no"
    if step == "checkout -b x origin/x":
        return "yes" if _upstream(repo, "x") == "origin/x" else "no"
    if step == "switch -c y":
        return "yes" if _out(repo, "branch", "--show-current") == "y" else "no"
    if step == "push -u origin y":
        return "yes" if _out(origin, "rev-parse", "--verify", "-q", "refs/heads/y") and _upstream(repo, "y") else "no"
    if step == "branch --set-upstream-to":
        return "yes" if _upstream(repo, "y") == "origin/x" else "no"
    if step == "remote add":
        return "yes" if "other" in (_out(repo, "remote") or "").split() else "no"
    if step == "config user.name":
        return "yes" if _out(repo, "config", "user.name") == STAND_IN else "no"
    assert step == "config core.hooksPath"
    return "put back" if _out(repo, "config", "core.hooksPath") is None else "kept"


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
def test_the_git_flow_under_the_grant(sbx):
    """Each step exits 0 and does what it says; only the hooksPath line is put back, by its key name."""
    _seed(sbx.work)
    measured, reverted = {}, {}
    for step, script in GRANTED_FLOW:
        ran, outcome = _granted(sbx, script, "hr1b-git-flow")
        measured[step] = (ran.returncode, _effect(sbx.work, step))
        reverted[step] = (outcome.reverted, outcome.restored, outcome.unchecked)
        if step == "config core.hooksPath":
            assert VALUE not in outcome.message() and "core.hookspath" in outcome.message()
    assert measured == {step: (0, "yes") for step, _ in GRANTED_FLOW[:-1]} | {"config core.hooksPath": (0, "put back")}, \
        json.dumps(measured)
    assert reverted == {step: ([], [], False) for step, _ in GRANTED_FLOW[:-1]} | {
        "config core.hooksPath": (["core.hookspath"], [], False)}
    # The same steps without the grant are #813's (its flow test): clone, init and every config step refused.
    assert FLOW_MEASURED["clone"][2] == FLOW_MEASURED["remote add"][2] == "no"


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
@pytest.mark.parametrize("granted", [False, True])
async def test_the_product_path_under_the_grant_with_the_profile_file(sbx, granted, monkeypatch):
    """terminal_exec.run itself (the `-f` profile file in the data folder, the snapshot and the put-back), under the
    harness's scratch HOME, data and temp: with the grant `git init` and `config user.name` work and the hooksPath is
    put back by name; without it init is refused. No profile file is left either way."""
    for name in ("HOME", "TMPDIR", "ARSLAN_DATA_DIR", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL"):
        monkeypatch.setenv(name, sbx.env[name])
    before = set(os.listdir(command_sandbox.profile_folder()))
    script = (f"git init -q fresh && git -C fresh config user.name {STAND_IN} "
              f"&& git -C fresh config core.hooksPath {VALUE}")
    result = await terminal_exec.run(script, cwd=sbx.work, sandbox=True, offline=True, git_config=granted)
    assert result["sandbox"] == "workspace"
    assert set(os.listdir(command_sandbox.profile_folder())) == before
    if not granted:
        assert not result["ok"] and not (sbx.work / "fresh" / ".git" / "config").exists()
        return
    assert result["ok"], result
    fresh = sbx.work / "fresh"
    assert _out(fresh, "config", "user.name") == STAND_IN and _out(fresh, "config", "core.hooksPath") is None
    assert "core.hookspath" in result["git_config_note"] and VALUE not in result["git_config_note"]
    assert not (fresh / ".git" / "hooks").exists()                   # no template folder under the grant


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
def test_under_the_grant_the_hooks_and_the_hooks_folder_stay_refused(sbx):
    """The grant lifts the config names only: a hook, the hooks folder of a repository made without one, and
    `.gitmodules` stay refused; the config beside them is written."""
    assert _git(sbx.work, "init", "-q", "--template=", "repo").returncode == 0      # no hooks folder
    assert _git(sbx.work, "init", "-q", "full").returncode == 0                      # git's own hooks folder
    script = (f"mkdir repo/.git/hooks; echo mkdir=$?; echo zz > full/.git/hooks/{STAND_IN}; echo hook=$?; "
              "echo zz > repo/.gitmodules; echo gitmodules=$?; git -C repo config user.name zz; echo config=$?")
    ran, outcome = _granted(sbx, script, "hr1b-hooks-held")
    codes = dict(line.split("=") for line in ran.stdout.split())
    assert {k: v != "0" for k, v in codes.items()} == {"mkdir": True, "hook": True, "gitmodules": True,
                                                       "config": False}
    assert not (sbx.work / "repo" / ".git" / "hooks").exists()
    assert not (sbx.work / "full" / ".git" / "hooks" / STAND_IN).exists()
    assert outcome.reverted == [] and _out(sbx.work / "repo", "config", "user.name") == "zz"


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
@pytest.mark.parametrize("granted", [False, True])
def test_a_sample_hook_is_written_and_renaming_it_to_a_hook_name_is_refused(sbx, granted):
    """Ruling 1: git never runs a `.sample` file, so one is written in the sandbox; an exact hook name stays held,
    by a rename too, and so does a name that only contains `.sample`. The hooks folder is git's own (made outside):
    making it stays held (test above)."""
    assert _git(sbx.work, "init", "-q").returncode == 0
    hooks = sbx.work / ".git" / "hooks"
    sample, other = f".git/hooks/{STAND_IN}.sample", f".git/hooks/{STAND_IN}.sample-{STAND_IN}"
    profile = sbx.profile(git_config_ok=granted)
    written = sbx.python("""
import json, pathlib, sys
out = {}
for name in sys.argv[1:]:
    try:
        pathlib.Path(name).write_text('zz')
    except PermissionError:
        out[name] = 'refused'
    else:
        out[name] = 'written'
print(json.dumps(out))
""", sbx.work / sample, sbx.work / other, sbx.work / ".git/hooks/pre-commit", probe="hr1b-sample", profile=profile)
    assert json.loads(written.stdout) == {str(sbx.work / sample): "written", str(sbx.work / other): "refused",
                                         str(sbx.work / ".git/hooks/pre-commit"): "refused"}
    renamed = sbx.run(["/bin/mv", sample, ".git/hooks/pre-commit"], probe="hr1b-sample-rename", profile=profile)
    assert renamed.returncode != 0 and not (hooks / "pre-commit").exists() and (sbx.work / sample).exists()


_WRITE_EACH = """
import json, pathlib, sys
out = {}
for name in sys.argv[1:]:
    try:
        pathlib.Path(name).write_text('zz')
    except PermissionError:
        out[name] = 'refused'
    else:
        out[name] = 'written'
print(json.dumps(out))
"""


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
@pytest.mark.parametrize("granted", [False, True])
@pytest.mark.parametrize("linked", [False, True])
def test_a_link_at_a_hook_name_turns_the_sample_exemption_off(sbx, granted, linked):
    """⓪Plan's ruling: a link at a hook name (here `pre-commit -> pre-commit.sample`, made before the command, as a
    checkout could) is an alias, like #813's node_modules rule: the write through it is refused, and so is any
    other sample in that run (the exemption is off). With no link the samples are written as before."""
    assert _git(sbx.work, "init", "-q").returncode == 0
    hooks = sbx.work / ".git" / "hooks"
    (hooks / "pre-commit.sample").write_text("#!/bin/sh\n")
    if linked:
        (hooks / "pre-commit").symlink_to("pre-commit.sample")
    names = [hooks / "pre-commit.sample", hooks / f"{STAND_IN}.sample"] + ([hooks / "pre-commit"] if linked else [])
    ran = sbx.python(_WRITE_EACH, *names, probe="hr1b-sample-alias", profile=sbx.profile(git_config_ok=granted))
    expected = "refused" if linked else "written"
    assert json.loads(ran.stdout) == {str(name): expected for name in names}
    if linked:
        assert (hooks / "pre-commit.sample").read_text() == "#!/bin/sh\n"


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
def test_making_a_link_at_a_hook_name_to_a_sample_is_refused(sbx):
    """#813's SYMLINK create deny covers it: `ln -s pre-commit.sample pre-commit`, and a link made elsewhere renamed
    onto the hook name, are refused; the sample beside it is still written (no link was there when it started)."""
    assert _git(sbx.work, "init", "-q").returncode == 0
    hooks = sbx.work / ".git" / "hooks"
    (hooks / "pre-commit.sample").write_text("#!/bin/sh\n")
    script = ("ln -s pre-commit.sample .git/hooks/pre-commit; echo link=$?; "
              f"ln -s .git/hooks/pre-commit.sample {STAND_IN}-link; mv {STAND_IN}-link .git/hooks/pre-commit; "
              "echo rename=$?; echo zz > .git/hooks/pre-commit.sample; echo sample=$?")
    ran = sbx.run(["/bin/bash", "-p", "-c", script], probe="hr1b-sample-link-made", profile=sbx.profile())
    codes = dict(line.split("=") for line in ran.stdout.split())
    assert {k: v != "0" for k, v in codes.items()} == {"link": True, "rename": True, "sample": False}
    assert not os.path.lexists(hooks / "pre-commit")


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
def test_without_the_grant_a_plain_write_to_the_sample_beside_the_config_is_as_in_813(sbx):
    """The exemption is the samples only: without the grant the config stays refused, beside a sample written."""
    assert _git(sbx.work, "init", "-q").returncode == 0
    names = [f".git/hooks/{STAND_IN}.sample", ".git/config"]
    assert _write(sbx, sbx.work, names) == {names[0]: "written", names[1]: "refused"}

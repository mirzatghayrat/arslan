"""HR-1b (v0.1.64) under real seatbelt: git's flow under this conversation's git_config grant, and git's sample hooks.

In the commands preset (the product's `commands_profile`, through SBX's harness, under a scratch HOME), with the grant
(`git_config_ok=True`, terminal_exec's template-free environment, and git_config_guard's snapshot before and restore
after, as terminal_exec runs them): clone, init, a tracking checkout, `push -u`, `--set-upstream-to`, `remote add`
and `config user.name` all work, on a bare origin kept in the work folder; a `core.hooksPath` set in the sandbox is
put back afterwards. The hooks stay held under the grant, the hooks folder itself included. Without the grant the
flow is #813's (tests/server/sbx/test_hr1_run_later_kernel.py, unchanged). git's sample hooks may be written in the
sandbox; renaming one to an exact hook name is refused, and a link at a hook name turns that exemption off for the run
(⓪Plan's ruling: it is an alias, as #813's node_modules rule has it).

Review delta 2 (⓪Plan's max review): what the command leaves running ends with it, or is put back by the next granted
command; no flag, ACL or hard link on a config under the grant; a config with a second name drops the lift; on an
aliased profile a config under node_modules stays held; a hook hard-linked to its sample makes the sample an alias.

Stand-in names and plain git steps only; the adversarial config shapes are Codex's corpus.
"""
import asyncio
import json
import os
import select
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


# ── review delta 2 (⓪Plan's max review) ──────────────────────────────────────

def _product_env(sbx, monkeypatch) -> None:
    for name in ("HOME", "TMPDIR", "ARSLAN_DATA_DIR", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL"):
        monkeypatch.setenv(name, sbx.env[name])


def _codes(ran) -> dict:
    return {k: v != "0" for k, v in (line.split("=") for line in ran.stdout.split())}


#: FIFOs in the work folder that order an own-session child against the test, with no timing.
_GATE, _DONE = f"{STAND_IN}-gate", f"{STAND_IN}-done"


def _own_session_child(key: str) -> str:
    """A child that leaves the command's group (`setsid`) and writes `key` once the test opens `_GATE`, which it does
    only after the granted command (and so its put-back) returned; it then writes `_DONE`. A fixed 0.5 s delay raced
    both ways under load: a put-back slower than 0.5 s reverted the key first, and a child slower than the test's
    1.5 s wait wrote it after the read; either left the key unset when the test read it. The parent exits only once
    the child has left the group: had it exited first, the command's end (`_end_group`) could kill the child before
    its `setsid`, and the key would never be written."""
    return (f"{sys.executable} -I -c \"import os, subprocess\n"
            "r, w = os.pipe()\n"
            "if os.fork(): os.close(w); os.read(r, 1); os._exit(0)\n"
            "os.setsid(); os.write(w, b'x'); os.close(w); os.close(r)\n"
            f"open('{_GATE}', 'rb').read(1)\n"
            f"subprocess.run(['git', '-C', 'repo', 'config', '{key}', '{VALUE}'])\n"
            f"open('{_DONE}', 'wb').write(b'x')\" "
            ">/dev/null 2>&1 </dev/null")


async def _granted_then_child_writes(sbx, script: str) -> dict:
    """The granted command, then its own-session child's write, strictly after the put-back. Both FIFOs are held open
    read-write by the test, so neither side's open waits for the other; a child that never writes fails the test."""
    gate, done = sbx.work / _GATE, sbx.work / _DONE
    os.mkfifo(gate)
    os.mkfifo(done)
    gate_fd, done_fd = os.open(gate, os.O_RDWR), os.open(done, os.O_RDWR)
    try:
        granted = await terminal_exec.run(script, cwd=sbx.work, sandbox=True, offline=True, git_config=True)
        assert granted["ok"], granted
        os.write(gate_fd, b"x")                                   # the put-back is over: the child may write now
        ready, _, _ = await asyncio.to_thread(select.select, [done_fd], [], [], 60)
        assert ready, "the child never wrote the key"
        assert os.read(done_fd, 1) == b"x"
    finally:
        os.close(gate_fd)
        os.close(done_fd)
    return granted


#: A child that writes a program-naming key after the command: in the command's group 0.5 s after it exits (the group
#: is ended first, so it never writes), or in a session of its own after the put-back.
_LATER = {
    "group": f"(sleep 0.5; git -C repo config core.hooksPath {VALUE}) >/dev/null 2>&1 &",
    "own session": _own_session_child("core.hooksPath"),
}


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
@pytest.mark.parametrize("child", sorted(_LATER))
async def test_a_process_the_command_leaves_running_never_keeps_a_key(sbx, monkeypatch, child):
    """Blocker 1, on the product path: the command's group ends before the put-back, so a background child never
    writes; one that left the group writes after the check, and the next granted command, whose baseline is the last
    put-back and never the file, puts it back."""
    _product_env(sbx, monkeypatch)
    assert _git(sbx.work, "init", "-q", "repo").returncode == 0
    config = sbx.work / "repo" / ".git" / "config"
    if child == "group":
        result = await terminal_exec.run(_LATER[child], cwd=sbx.work, sandbox=True, offline=True, git_config=True)
        assert result["ok"], result
        await asyncio.sleep(1.5)                  # past the 0.5 s at which the ended child would have written
    else:
        result = await _granted_then_child_writes(sbx, _LATER[child])
    if child == "group":
        assert _out(sbx.work / "repo", "config", "core.hooksPath") is None
        assert "stopped what this command left running" in result["git_config_note"]
    else:
        assert _out(sbx.work / "repo", "config", "core.hooksPath") == VALUE        # the residual, until the next one
    assert VALUE.encode() not in git_config_guard.snapshot(sbx.work).files[config]
    again = await terminal_exec.run("true", cwd=sbx.work, sandbox=True, offline=True, git_config=True)
    assert again["ok"] and _out(sbx.work / "repo", "config", "core.hooksPath") is None
    assert ("core.hookspath" in again.get("git_config_note", "")) == (child == "own session")


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
def test_under_the_grant_no_flag_acl_or_hard_link_can_be_set_on_a_config(sbx):
    """Blockers 2 and 3 (a): the lift is the config's writes only. `file-link` (measured: it refuses a link to a config
    and a link at its name), `file-write-flags` and `file-write-acl` stay denied, so `uchg`, an ACL and a hard link
    in either direction are refused, and the key the command added is put back."""
    assert _git(sbx.work, "init", "-q", "repo").returncode == 0
    (sbx.work / f"{STAND_IN}.txt").write_text("zz")
    script = (f"cd repo && git config core.hooksPath {VALUE}; echo config=$?; chflags uchg .git/config; echo uchg=$?; "
              "chmod +a 'everyone deny delete' .git/config; echo acl=$?; "
              f"ln .git/config ../{STAND_IN}-to; echo link_to=$?; ln ../{STAND_IN}.txt .git/config.worktree; "
              "echo link_at=$?")
    ran, outcome = _granted(sbx, script, "hr1b-flags-links")
    assert _codes(ran) == {"config": False, "uchg": True, "acl": True, "link_to": True, "link_at": True}
    config = sbx.work / "repo" / ".git" / "config"
    assert outcome.reverted == ["core.hookspath"] and outcome.held == []
    assert config.stat().st_nlink == 1 and config.stat().st_flags == 0
    assert not (sbx.work / f"{STAND_IN}-to").exists() and not (config.parent / "config.worktree").exists()


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
def test_a_flag_on_a_submodules_folder_set_under_the_grant_does_not_keep_the_key(sbx):
    """Blocker 2: a submodule's folder (`.git/modules/<name>`) isn't held in place, so the command can set `uchg` on
    it after adding a key, which blocks the put-back's new file there; the put-back clears it and reverts the key."""
    assert _git(sbx.work, "init", "-q", "repo").returncode == 0
    module = sbx.work / "repo" / ".git" / "modules" / STAND_IN
    module.mkdir(parents=True)
    (module / "config").write_text("[core]\n\tbare = false\n")
    script = (f"git config --file repo/.git/modules/{STAND_IN}/config core.hooksPath {VALUE}; echo config=$?; "
              f"chflags uchg repo/.git/modules/{STAND_IN}; echo uchg=$?")
    try:
        ran, outcome = _granted(sbx, script, "hr1b-folder-flag")
    finally:
        os.chflags(module, 0)
    assert _codes(ran) == {"config": False, "uchg": False}
    assert outcome.reverted == ["core.hookspath"] and outcome.held == []
    assert (module / "config").read_text() == "[core]\n\tbare = false\n"


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
async def test_a_config_with_a_second_name_runs_held_with_a_note(sbx, monkeypatch):
    """Blocker 3 (b), on the product path: a config with another name (made outside, before the command) drops the
    lift for the run, as without the grant, and the step says why."""
    _product_env(sbx, monkeypatch)
    assert _git(sbx.work, "init", "-q", "repo").returncode == 0
    os.link(sbx.work / "repo" / ".git" / "config", sbx.work / f"{STAND_IN}-other")
    result = await terminal_exec.run(f"git -C repo config user.name {STAND_IN}", cwd=sbx.work, sandbox=True,
                                     offline=True, git_config=True)
    assert not result["ok"] and _out(sbx.work / "repo", "config", "user.name") is None
    assert "a hard link" in result["git_config_note"]


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
def test_on_an_aliased_profile_a_config_under_node_modules_stays_held_under_the_grant(sbx):
    """Blocker 4: with an alias found, the profile holds dependency folders; the guard's walk never opens them, so
    the grant doesn't lift a config there either. The work folder's own config is still lifted."""
    assert _git(sbx.work, "init", "-q", "repo").returncode == 0
    dependency = sbx.work / "node_modules" / STAND_IN / ".git" / "config"
    dependency.parent.mkdir(parents=True)
    dependency.write_text("")
    (sbx.work / f"{STAND_IN}-elsewhere").mkdir()
    (sbx.work / f"{STAND_IN}-elsewhere" / "envrc").write_text("")
    (sbx.work / ".envrc").symlink_to(f"{STAND_IN}-elsewhere/envrc")             # an alias: it leaves its folder
    assert command_sandbox.run_later_folders([sbx.work]).aliased
    names = [f"node_modules/{STAND_IN}/.git/config", "repo/.git/config"]
    assert _write(sbx, sbx.work, names) == {names[0]: "refused", names[1]: "refused"}     # main: both held
    ran = sbx.python(_WRITE_EACH, *(sbx.work / n for n in names), probe="hr1b-aliased-nm",
                     profile=sbx.profile(git_config_ok=True))
    assert json.loads(ran.stdout) == {str(sbx.work / names[0]): "refused", str(sbx.work / names[1]): "written"}
    assert dependency.read_text() == ""


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
@pytest.mark.parametrize("granted", [False, True])
def test_a_hook_enabled_by_hard_linking_its_sample_is_not_written_through_the_sample(sbx, granted):
    """Blocker 5: `pre-commit` hard-linked to `pre-commit.sample` (made outside) makes the sample an alias: writing
    it is refused, so the live hook keeps its bytes. A sample with one name beside it is refused too in that run."""
    assert _git(sbx.work, "init", "-q").returncode == 0
    hooks = sbx.work / ".git" / "hooks"
    (hooks / "pre-commit.sample").write_text("#!/bin/sh\n")
    os.link(hooks / "pre-commit.sample", hooks / "pre-commit")
    names = [hooks / "pre-commit.sample", hooks / f"{STAND_IN}.sample"]
    ran = sbx.python(_WRITE_EACH, *names, probe="hr1b-sample-hard-link", profile=sbx.profile(git_config_ok=granted))
    assert json.loads(ran.stdout) == {str(name): "refused" for name in names}
    assert (hooks / "pre-commit").read_text() == "#!/bin/sh\n"


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
def test_without_the_grant_a_plain_write_to_the_sample_beside_the_config_is_as_in_813(sbx):
    """The exemption is the samples only: without the grant the config stays refused, beside a sample written."""
    assert _git(sbx.work, "init", "-q").returncode == 0
    names = [f".git/hooks/{STAND_IN}.sample", ".git/config"]
    assert _write(sbx, sbx.work, names) == {names[0]: "written", names[1]: "refused"}


# ── review delta 3 (Codex's re-run: a process in its own session writes after the put-back) ─────────────────────

@pytest.fixture(autouse=True)
def _fresh_guard():
    for each in (git_config_guard._BASELINES, git_config_guard.ENDED, git_config_guard.WATCHED):
        each.clear()
    yield
    for each in (git_config_guard._BASELINES, git_config_guard.ENDED, git_config_guard.WATCHED):
        each.clear()


#: A child that leaves the command's group (`setsid`) and writes a stand-in program key after the put-back.
_FSMONITOR_LATER = _own_session_child("core.fsmonitor")


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
@pytest.mark.parametrize("writable,reader", [(True, ""), (True, f"{STAND_IN}-other"), (False, "")])
async def test_a_key_written_after_the_put_back_never_reaches_an_ungranted_command(sbx, monkeypatch, writable, reader):
    """The race, on the product path: the granted command ends and is put back; its own-session child writes
    core.fsmonitor after that. The next command, without the grant, in this conversation or (review delta 4) another,
    finds it put back before it starts (git reads no key), and the step names the key, never its value. When the
    put-back can't be written (the `.git` folder made read-only from outside the sandbox) that command is refused,
    does nothing, and the grant ends."""
    from server.services import tool_outputs
    _product_env(sbx, monkeypatch)
    assert _git(sbx.work, "init", "-q", "repo").returncode == 0
    git = sbx.work / "repo" / ".git"
    await _granted_then_child_writes(sbx, _FSMONITOR_LATER)
    assert _out(sbx.work / "repo", "config", "core.fsmonitor") == VALUE        # written after the put-back
    mode = git.stat().st_mode
    if not writable:
        git.chmod(0o555)
    token = tool_outputs.conversation.set(reader)
    try:
        ran = await terminal_exec.run(f"git -C repo config --get core.fsmonitor; echo got=$?; touch {STAND_IN}-ran",
                                      cwd=sbx.work, sandbox=True, offline=True)
    finally:
        tool_outputs.conversation.reset(token)
        git.chmod(mode)
    assert VALUE not in ran["git_config_note"] and VALUE not in ran["stdout"]
    if writable:
        assert ran["ok"] and ran["stdout"].split() == ["got=1"] and "core.fsmonitor" in ran["git_config_note"]
        assert _out(sbx.work / "repo", "config", "core.fsmonitor") is None and (sbx.work / f"{STAND_IN}-ran").exists()
    else:
        assert not ran["ok"] and ran["git_config_note"] == git_config_guard.REFUSED and "" in git_config_guard.ENDED
        assert not (sbx.work / f"{STAND_IN}-ran").exists()


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
def test_a_config_removed_by_ln_f_under_the_grant_is_written_back(sbx):
    """Codex's side finding: `cp` the config, then `ln -f` the copy onto it. The unlink is allowed under the grant, the
    link is refused, so the config is gone; the put-back writes it back from the baseline and says so."""
    assert _git(sbx.work, "init", "-q", "repo").returncode == 0
    config = sbx.work / "repo" / ".git" / "config"
    before = config.read_bytes()
    script = (f"cp repo/.git/config {STAND_IN}-copy && ln -f {STAND_IN}-copy repo/.git/config; echo ln=$?; "
              "test -e repo/.git/config; echo gone=$?")
    ran, outcome = _granted(sbx, script, "hr1b-config-removed")
    assert _codes(ran) == {"ln": True, "gone": True}
    assert outcome.replaced == [os.path.join("repo", ".git", "config")] and "was removed" in outcome.message()
    assert config.read_bytes() == before and config.stat().st_nlink == 1

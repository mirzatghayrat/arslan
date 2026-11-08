"""SBX-5a (v0.1.64): CAP6b and the Arslan-owned caches (card, "CAP6b" and §1c).

- The skill and plugin folders (`command_sandbox.cap6b_folders`) are never read or written by a command, inside
  the sandbox or out of it, never written by an MCP server even inside a granted folder, and out of run_python's
  reach. `write_file` / `edit_file` refuse them, and Arslan's data folder too, except the eval's marked folder.
- The user's ~/.npm, ~/.cache and ~/Library/Caches are read-only to commands and MCP servers. Commands write
  Arslan's own commands cache; each MCP server writes its own cache under its folder; neither sees the other's.
- An MCP server whose folder holds a hard link to a file outside it does not start.

The macOS cases run the product paths under real seatbelt (terminal_exec, capability_sandbox.wrap,
code_sandbox.computation_profile). SBX-5p's gates (test_sbx5_paths.py, Codex's) run the same closures through
the SBX harness.
"""
import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from server.services import capability_sandbox, code_sandbox, command_sandbox, run_temp, terminal_exec, workspace_paths

macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")

# Probe script for the real-seatbelt cases: tries each (name, action, path) and prints, per name, "ok" or the
# errno's name. Only those words come back, never file contents; the tests check the sentinels afterwards.
PROBE = """
import errno, json, os, pathlib, sys
out = {}
for name, action, path in json.loads(sys.argv[1]):
    p = pathlib.Path(os.path.expandvars(path))
    try:
        if action == 'read':
            p.read_text()
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('changed')
        out[name] = 'ok'
    except OSError as exc:
        out[name] = errno.errorcode.get(exc.errno, str(exc.errno))
print(json.dumps(out))
"""
REFUSED = {"EPERM", "EACCES"}


def _sentinel(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "sentinel"
    path.write_text("original")
    return path


@pytest.fixture
def home(monkeypatch, tmp_path):
    """A scratch HOME (Path.home() follows it) and a scratch temp root, so the runs' folders and Arslan's own
    commands cache sit under this test's folder, never the real ones."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    temp = tmp_path / "t"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    return home


# ── portable: what the profiles and helpers are made of ──────────────────────────────

def test_the_cap6b_folders_are_resolved_and_take_the_plugin_folder(home, tmp_path, monkeypatch):
    real = tmp_path / "elsewhere"
    (real / "skills").mkdir(parents=True)
    (home / ".agents").symlink_to(real, target_is_directory=True)
    assert command_sandbox.cap6b_folders() == [(real / "skills").resolve()]      # the real path, not the link
    plugin = tmp_path / "plugins"
    assert command_sandbox.cap6b_folders(plugin)[-1] == plugin.resolve()
    monkeypatch.setattr(command_sandbox, "PLUGIN_FOLDER", plugin)                 # CAP7 sets it
    assert command_sandbox.cap6b_folders()[-1] == plugin.resolve()


def test_the_commands_cache_is_outside_the_users_and_mcp_has_none_shared(home):
    commands = run_temp.cache("commands")
    assert not any(commands.is_relative_to(p) for p in command_sandbox.shared_caches())
    assert not any(commands.is_relative_to(p) for p in command_sandbox.default_protected())
    for preset in ("mcp", "shared"):                  # one cache for every MCP server would be a channel
        with pytest.raises(ValueError):
            run_temp.cache(preset)


def test_cache_folders_are_private_and_ours(tmp_path):
    folder = tmp_path / "parent" / "commands"
    (tmp_path / "parent").mkdir()
    command_sandbox.cache_environment(folder)
    for path in (folder, folder.parent):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700, path
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "linked").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    with pytest.raises(OSError, match="folder of ours"):
        command_sandbox.cache_environment(tmp_path / "linked" / "commands")   # a link as the parent
    (tmp_path / "file").write_text("x")
    with pytest.raises(OSError):
        command_sandbox.cache_environment(tmp_path / "file" / "commands")     # a file as the parent
    loose = tmp_path / "loose"
    loose.mkdir(mode=0o755)
    command_sandbox.cache_environment(loose / "commands")
    assert stat.S_IMODE(loose.stat().st_mode) == 0o700                    # tightened, not trusted


async def test_a_sandboxed_run_points_its_tools_at_the_commands_cache(home, monkeypatch, tmp_path):
    monkeypatch.setattr(command_sandbox, "wrapper", lambda cwd, **kw: ["/usr/bin/env"])
    result = await terminal_exec.run("env", cwd=tmp_path, sandbox=True, offline=True)
    lines = dict(line.split("=", 1) for line in result["stdout"].splitlines() if "=" in line)
    own = run_temp.cache("commands")
    for name in command_sandbox.CACHE_ENV:
        assert Path(lines[name]).parent == own, name
    assert stat.S_IMODE(own.stat().st_mode) == 0o700


def test_each_mcp_server_starts_with_its_own_cache(home, tmp_path):
    envs = []
    for name in ("a", "b"):
        _, args, env, _ = capability_sandbox.wrap("/bin/echo", [], {"PATH": "/usr/bin"},
                                                  {"root": str(tmp_path / name), "folders": [], "network": False})
        for variable in command_sandbox.CACHE_ENV:
            assert Path(env[variable]).parent == tmp_path / name / "cache", variable
        envs.append(env)
        other = (tmp_path / ("b" if name == "a" else "a")).resolve()
        assert f'"{other}' not in args[1]                                  # never the other server's folder
    assert envs[0]["npm_config_cache"] != envs[1]["npm_config_cache"]


def test_mcp_closes_the_commands_cache_after_a_grant_that_contains_it(home, tmp_path):
    """The commands cache is closed to an MCP server after its grants, so a wide grant doesn't open a package a
    command planted there."""
    parent = tmp_path / "wide"
    peer, own = parent / "commands-cache", tmp_path / "mcp-cache"
    peer.mkdir(parents=True)
    lines = capability_sandbox.profile(root=tmp_path / "srv", folders=[str(parent)], network=False, read=[],
                                       cache=own, peer_cache=peer).splitlines()
    grant = next(i for i, line in enumerate(lines)
                 if line.startswith("(allow file-write*") and str(parent.resolve()) in line)
    closed = lines.index(f'(deny file-read* file-write* file-map-executable (subpath "{peer.resolve()}"))')
    assert grant < closed


def test_the_file_tools_refuse_the_cap6b_folders_and_arslans_data_even_inside_the_workspace(home, monkeypatch):
    (home / ".agents" / "skills").mkdir(parents=True)
    data = home / "Library" / "Application Support" / "Arslan"
    data.mkdir(parents=True)
    from server import config
    monkeypatch.setattr(config, "data_dir", lambda: data)
    for path in (".agents/skills/x/SKILL.md", ".agents/skills/new.md", "Library/Application Support/Arslan/a.db"):
        with pytest.raises(workspace_paths.PathEscape, match="skills, plugins or data"):
            workspace_paths.resolve_in_workspace(path, home, for_write=True, make_parents=True)
    assert workspace_paths.resolve_in_workspace("notes.md", home, for_write=True) == (home / "notes.md").resolve()
    with pytest.raises(workspace_paths.PathEscape, match="skills, plugins or data"):    # the data folder itself
        workspace_paths.resolve_in_workspace("mcp.json", data, for_write=True)
    for own in ("runtimes/node/bin", "capabilities/x"):      # Arslan's own folders as the working folder: refused
        (data / own).mkdir(parents=True)
        with pytest.raises(workspace_paths.PathEscape, match="skills, plugins or data"):
            workspace_paths.resolve_in_workspace("npx", data / own, for_write=True)
    inside = data / "workspace"                    # the eval's marked working folder writes its own files
    inside.mkdir()
    assert workspace_paths.resolve_in_workspace("brief.md", inside, for_write=True) == (inside / "brief.md").resolve()
    # Reading stays as before: SKILL.md is read through read_skill, not refused here.
    (home / ".agents" / "skills" / "a.md").write_text("x")
    assert workspace_paths.resolve_in_workspace(".agents/skills/a.md", home).name == "a.md"


async def test_write_file_and_edit_file_refuse_them_and_write_the_marked_eval_folder(home, monkeypatch, tmp_path):
    """Through the tools themselves: nothing is written into the skill, plugin or data folder from a working
    folder that contains them, and the eval's `<data>/workspace` still gets its file."""
    from server import config
    from server.registry import file_tools
    data = home / "data"
    plugin = home / "plugins"
    sentinels = [_sentinel(home / ".agents" / "skills"), _sentinel(plugin), _sentinel(data)]
    monkeypatch.setattr(config, "data_dir", lambda: data)
    monkeypatch.setattr(command_sandbox, "PLUGIN_FOLDER", plugin)
    root = home

    async def workspace():
        return root

    monkeypatch.setattr(file_tools, "_workspace_root", workspace)
    write, edit = file_tools.WriteFileExecutor().execute, file_tools.EditFileExecutor().execute
    for sentinel in sentinels:
        relative = str(sentinel.relative_to(home))
        assert (await write({"path": relative, "content": "changed"}))["ok"] is False, relative
        assert (await write({"path": str(sentinel.parent.relative_to(home) / "new.md"), "content": "x"}))["ok"] is False
        assert (await edit({"path": relative, "old_string": "original", "new_string": "changed"}))["ok"] is False
        assert sentinel.read_text() == "original" and not (sentinel.parent / "new.md").exists()
    assert (await write({"path": "notes.md", "content": "ok"}))["ok"] is True
    root = data / "workspace"
    root.mkdir()
    assert (await write({"path": "brief.md", "content": "ok"}))["ok"] is True
    assert (root / "brief.md").read_text() == "ok"


def test_the_sbx_harness_claims_both_features():
    from tests.server.sbx import harness
    assert {"cap6b", "shared-cache-exclusions"} <= harness.BUILT_FEATURES


def test_a_server_whose_folder_holds_a_link_from_outside_does_not_start(home, tmp_path):
    """SBX-5p measured that a hard link already in a server's folder writes the outside file; refused at spawn."""
    root = tmp_path / "srv"
    (root / "lib").mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("x")
    os.link(outside, root / "lib" / "planted")
    with pytest.raises(capability_sandbox.OutsideLink, match="lib/planted"):
        capability_sandbox.wrap("/bin/echo", [], {"PATH": "/usr/bin"}, {"root": str(root), "folders": [], "network": False})


def test_links_inside_the_folder_and_symlinks_are_fine(home, tmp_path):
    root = tmp_path / "srv"
    (root / "cache").mkdir(parents=True)
    (root / "cache" / "pkg").write_text("x")
    os.link(root / "cache" / "pkg", root / "pkg")                # a tool linking from its own cache
    (root / "to-outside").symlink_to(tmp_path)                    # never followed
    assert capability_sandbox.outside_links(root) == []
    capability_sandbox.wrap("/bin/echo", [], {"PATH": "/usr/bin"}, {"root": str(root), "folders": [], "network": False})


# ── macOS: the product paths under real seatbelt ──────────────────────────────────────

def _targets(home: Path, plugin: Path) -> dict[str, Path]:
    return {"skills": _sentinel(home / ".agents" / "skills"), "plugin": _sentinel(plugin),
            "npm": _sentinel(home / ".npm"), "cache": _sentinel(home / ".cache"),
            "Library-Caches": _sentinel(home / "Library" / "Caches")}


def _probe_command(checks: list[tuple[str, str, Path]]) -> str:
    return " ".join(shlex.quote(part) for part in (
        sys.executable, "-I", "-c", PROBE, json.dumps([(n, a, str(p)) for n, a, p in checks])))


def _outcome(stdout: str) -> dict:
    return json.loads(stdout.strip().splitlines()[-1])


@pytest.mark.macos
@macos
async def test_a_sandboxed_command_keeps_off_cap6b_and_the_users_caches_and_writes_its_own(home, monkeypatch):
    """The work folder is HOME, so every closed folder is inside a writable ancestor."""
    plugin = home / "plugins"
    monkeypatch.setattr(command_sandbox, "PLUGIN_FOLDER", plugin)
    targets = _targets(home, plugin)
    command = _probe_command([
        *((f"{n}-read", "read", p) for n, p in targets.items()),
        *((f"{n}-write", "write", p) for n, p in targets.items()),
        ("own-cache", "write", "$PIP_CACHE_DIR/probe"), ("work", "write", home / "ordinary.txt")])
    result = await terminal_exec.run(command, cwd=home, sandbox=True, offline=True)   # the probe expands $PIP_…
    assert result["sandbox"] == "workspace", result.get("error")
    out = _outcome(result["stdout"])
    assert {out[f"{n}-read"] for n in ("skills", "plugin")} <= REFUSED, out             # CAP6b: no read
    assert {out[f"{n}-write"] for n in targets} <= REFUSED, out                          # nor write; caches too
    assert {out[f"{n}-read"] for n in ("npm", "cache", "Library-Caches")} == {"ok"}, out  # caches stay readable
    assert out["own-cache"] == "ok" and out["work"] == "ok", out                         # its own cache is written
    assert (run_temp.cache("commands") / "pip_cache_dir" / "probe").read_text() == "changed"
    assert all(p.read_text() == "original" for p in targets.values())


@pytest.mark.macos
@macos
async def test_a_command_let_out_of_the_sandbox_still_cant_touch_cap6b(home, monkeypatch):
    plugin = home / "plugins"
    monkeypatch.setattr(command_sandbox, "PLUGIN_FOLDER", plugin)
    skills, plug = _sentinel(home / ".agents" / "skills"), _sentinel(plugin)
    credential = _sentinel(home / ".ssh")                     # the user's secrets stay open outside (ssh, git)
    command = _probe_command([("skills-read", "read", skills), ("plugin-read", "read", plug),
                              ("skills-write", "write", skills), ("plugin-write", "write", plug),
                              ("credential", "read", credential)])
    result = await terminal_exec.run(command, cwd=home, sandbox=False, offline=True)
    assert result["sandbox"] == "outside", result.get("error")
    out = _outcome(result["stdout"])
    assert {out[k] for k in ("skills-read", "plugin-read", "skills-write", "plugin-write")} <= REFUSED, out
    assert out["credential"] == "ok", out
    assert skills.read_text() == plug.read_text() == "original"


def _run_wrapped(command: str, args: list[str], env: dict, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run([command, *args], env=env, cwd=cwd, capture_output=True, text=True, timeout=60,
                          stdin=subprocess.DEVNULL)


@pytest.mark.macos
@macos
def test_an_mcp_server_granted_home_keeps_off_cap6b_and_the_caches_and_writes_its_own(home, monkeypatch, tmp_path):
    plugin = home / "plugins"
    monkeypatch.setattr(command_sandbox, "PLUGIN_FOLDER", plugin)
    targets = _targets(home, plugin)
    planted = _sentinel(run_temp.cache("commands"))          # a package a command left in its own cache
    root = tmp_path / "server"
    checks = [*((f"{n}-write", "write", p) for n, p in targets.items()),
              *((f"{n}-read", "read", p) for n, p in targets.items() if n not in ("skills", "plugin")),
              ("commands-cache", "read", planted), ("own-cache", "write", root / "cache" / "pip_cache_dir" / "probe"),
              ("granted", "write", home / "ordinary.txt"), ("own-folder", "write", root / "home" / "x")]
    # Granted HOME and the temp root, which holds the commands cache: only the closures stand in the way.
    granted = [str(home), tempfile.gettempdir()]
    assert planted.is_relative_to(granted[1])
    command, args, env, cwd = capability_sandbox.wrap(
        sys.executable, ["-I", "-c", PROBE, json.dumps([(n, a, str(p)) for n, a, p in checks])],
        {"PATH": "/usr/bin:/bin"},
        {"root": str(root), "folders": granted, "network": False, "read": [sys.prefix, sys.base_prefix]})
    assert Path(env["PIP_CACHE_DIR"]) == root / "cache" / "pip_cache_dir"
    result = _run_wrapped(command, args, env, cwd)
    assert result.returncode == 0, result.returncode
    out = _outcome(result.stdout)
    assert {out[f"{n}-write"] for n in targets} <= REFUSED, out                         # CAP6b and caches
    assert {out[f"{n}-read"] for n in ("npm", "cache", "Library-Caches")} == {"ok"}, out
    assert out["commands-cache"] in REFUSED, out                                        # never the commands'
    assert {out["own-cache"], out["granted"], out["own-folder"]} == {"ok"}, out
    assert all(p.read_text() == "original" for p in [*targets.values(), planted])


@pytest.mark.macos
@macos
def test_run_python_cant_reach_cap6b_even_inside_its_workspace(home, tmp_path):
    """~/.agents links into the workspace, so only the CAP6b rule stands between run_python and the skills."""
    work = tmp_path / "work"
    real = work / "agent-source"
    skills = _sentinel(real / "skills")
    (home / ".agents").symlink_to(real, target_is_directory=True)
    ordinary = _sentinel(work / "data")
    text = code_sandbox.computation_profile(sys.executable, work)
    checks = [("skills-read", "read", skills), ("skills-write", "write", skills),
              ("alias-read", "read", home / ".agents" / "skills" / "sentinel"), ("work", "read", ordinary)]
    result = _run_wrapped("/usr/bin/sandbox-exec", ["-p", text, sys.executable, "-I", "-c", PROBE,
                                                    json.dumps([(n, a, str(p)) for n, a, p in checks])],
                          {"PATH": "/usr/bin:/bin", "HOME": str(home)}, str(work))
    assert result.returncode == 0, result.returncode
    out = _outcome(result.stdout)
    assert {out["skills-read"], out["skills-write"], out["alias-read"]} <= REFUSED, out
    assert out["work"] == "ok", out
    assert skills.read_text() == "original"


@pytest.mark.macos
@macos
def test_a_server_with_an_outside_link_does_not_start_and_starts_once_it_is_gone(home, tmp_path):
    """Under real seatbelt that link would write the outside file (SBX-5p's measurement); wrap() refuses first.
    Without the link the same server starts and writes its own folder."""
    root = tmp_path / "server"
    (root / "lib").mkdir(parents=True)
    outside = _sentinel(tmp_path / "outside")
    os.link(outside, root / "lib" / "planted")
    sandbox = {"root": str(root), "folders": [], "network": False, "read": [sys.prefix, sys.base_prefix]}
    probe = ["-I", "-c", PROBE, json.dumps([("own", "write", str(root / "lib" / "own.txt"))])]
    with pytest.raises(capability_sandbox.OutsideLink):
        capability_sandbox.wrap(sys.executable, probe, {"PATH": "/usr/bin:/bin"}, sandbox)
    assert outside.read_text() == "original"
    (root / "lib" / "planted").unlink()
    result = _run_wrapped(*capability_sandbox.wrap(sys.executable, probe, {"PATH": "/usr/bin:/bin"}, sandbox))
    assert result.returncode == 0 and _outcome(result.stdout) == {"own": "ok"}, result.returncode

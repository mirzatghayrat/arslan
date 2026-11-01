"""SBX-5a (v0.1.64): CAP6b and the Arslan-owned caches (card §1c, "CAP6b").

- The skill and plugin folders (`command_sandbox.cap6b_folders`) are never read or written by a command, inside
  the sandbox or out of it, never written by an MCP server even inside a granted folder, and out of run_python's
  reach. `write_file` / `edit_file` refuse them and Arslan's data folder too.
- The user's ~/.npm, ~/.cache and ~/Library/Caches are read-only to every sandboxed preset; commands and MCP
  servers each write their own Arslan-owned cache, which the other can't see.

Whether what should be denied is denied under real seatbelt is SBX-5p's (Codex).
"""
import os
import stat
import sys
from pathlib import Path

import pytest

from server.services import capability_sandbox, command_sandbox, run_temp, terminal_exec, workspace_paths

macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")


@pytest.fixture
def home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


def test_the_cap6b_folders_are_resolved_and_take_the_plugin_folder(home, tmp_path, monkeypatch):
    real = tmp_path / "elsewhere"
    (real / "skills").mkdir(parents=True)
    (home / ".agents").symlink_to(real, target_is_directory=True)
    assert command_sandbox.cap6b_folders() == [(real / "skills").resolve()]      # the real path, not the link
    plugin = tmp_path / "plugins"
    assert command_sandbox.cap6b_folders(plugin)[-1] == plugin.resolve()
    monkeypatch.setattr(command_sandbox, "PLUGIN_FOLDER", plugin)                 # CAP7 sets it
    assert command_sandbox.cap6b_folders()[-1] == plugin.resolve()


def test_the_commands_cache_is_outside_the_users_and_mcp_has_none_shared():
    commands = run_temp.cache("commands")
    assert not any(commands.is_relative_to(p) for p in command_sandbox.shared_caches())
    for preset in ("mcp", "shared"):                  # #5a review: one cache for every MCP server is a channel
        with pytest.raises(ValueError):
            run_temp.cache(preset)


def test_cache_folders_are_private_and_ours(tmp_path):
    folder = tmp_path / "parent" / "commands"
    command_sandbox.cache_environment(folder)
    for path in (folder, folder.parent):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700, path
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "linked").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    with pytest.raises(OSError, match="folder of ours"):
        command_sandbox.cache_environment(tmp_path / "linked" / "commands")   # a link as the parent
    (tmp_path / "file").write_text("x")
    with pytest.raises(OSError):
        command_sandbox.cache_environment(tmp_path / "file" / "commands")          # a file as the parent
    loose = tmp_path / "loose"
    loose.mkdir(mode=0o755)
    command_sandbox.cache_environment(loose / "commands")
    assert stat.S_IMODE(loose.stat().st_mode) == 0o700                         # tightened, not trusted


async def test_a_sandboxed_run_points_its_tools_at_the_commands_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(command_sandbox, "wrapper", lambda cwd, **kw: ["/usr/bin/env"])
    result = await terminal_exec.run("env", cwd=tmp_path, sandbox=True)
    lines = dict(line.split("=", 1) for line in result["stdout"].splitlines() if "=" in line)
    own = run_temp.cache("commands")
    for name in command_sandbox.CACHE_ENV:
        assert Path(lines[name]).parent == own, name
    assert stat.S_IMODE(own.stat().st_mode) == 0o700


def test_each_mcp_server_starts_with_its_own_cache(tmp_path):
    envs = []
    for name in ("a", "b"):
        _, args, env, _ = capability_sandbox.wrap("/bin/echo", [], {"PATH": "/usr/bin"},
                                                  {"root": str(tmp_path / name), "folders": [], "network": False})
        for variable in command_sandbox.CACHE_ENV:
            assert Path(env[variable]).parent == tmp_path / name / "cache", variable
        envs.append(env)
        text = args[1]
        assert f'(subpath "{(tmp_path / ("b" if name == "a" else "a")).resolve()}")' not in text   # never the other's
    assert envs[0]["npm_config_cache"] != envs[1]["npm_config_cache"]


def test_mcp_cant_see_the_commands_cache_even_inside_a_granted_folder(tmp_path):
    """The commands cache is closed to an MCP server after its grants, so a grant that contains it (a wide
    parent folder) doesn't open a package a command planted there."""
    parent = tmp_path / "wide"
    peer, own = parent / "commands-cache", tmp_path / "mcp-cache"
    peer.mkdir(parents=True)
    text = capability_sandbox.profile(root=tmp_path / "srv", folders=[str(parent)], network=False, read=[],
                                      cache=own, peer_cache=peer)
    lines = text.splitlines()
    grant = next(i for i, line in enumerate(lines) if line.startswith("(allow file-write*") and str(parent.resolve()) in line)
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


def test_the_sbx_harness_claims_cap6b():
    from tests.server.sbx import harness
    assert harness.BUILT_FEATURES == frozenset({"cap6b"})


@pytest.mark.macos
@macos
async def test_a_sandboxed_tool_writes_its_redirected_cache(tmp_path):
    """What should run does run: a tool writes the cache its variable names, inside the sandbox."""
    result = await terminal_exec.run(
        "python3 -c \"import os, pathlib; d = pathlib.Path(os.environ['PIP_CACHE_DIR']); d.mkdir(exist_ok=True); "
        "(d / 'probe').write_text('ok'); print((d / 'probe').read_text())\"", cwd=tmp_path, sandbox=True)
    assert result["sandbox"] == "workspace" and result["ok"], result
    assert result["stdout"].strip() == "ok"
    assert (run_temp.cache("commands") / "pip_cache_dir" / "probe").read_text() == "ok"
    os.remove(run_temp.cache("commands") / "pip_cache_dir" / "probe")

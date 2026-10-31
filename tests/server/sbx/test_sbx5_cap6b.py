"""SBX-5 (v0.1.64), the build half (5a), first part: CAP6b. The skill and plugin folders and Arslan's own folders
are never written by the model (docs/plans/0164/SBX-sandbox.md §CAP6b; CAP card §CAP6b).

- `~/.agents/skills` and the plugin folders (CAP7 adds its own through `PLUGIN_FOLDERS`, without editing a
  profile) are protected paths:
  - closed to reads and writes in the commands profile and under the outside floor;
  - closed inside an MCP server's granted folders;
  - judged where they resolve, so a link to them is no way round.
- `write_file` and `edit_file` refuse them and Arslan's own folders, even when the working folder holds them.

Whether seatbelt refuses a write through either name is Codex's real-seatbelt test (SBX-5p). Here the profile
texts and the file tools' refusal are tested.
"""
from pathlib import Path

import pytest

from server import config
from server.services import capability_sandbox, command_sandbox, workspace_paths


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "ws").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(command_sandbox, "PLUGIN_FOLDERS", [home / "plugins"])
    return home


def _closed_in(text: str, path: Path, verbs: str = "(deny file-read* file-write*") -> bool:
    return any(line.startswith(verbs) and f'"{command_sandbox._real(path)}"' in line for line in text.splitlines())


def test_the_skill_and_plugin_folders_are_protected_paths(home):
    folders = command_sandbox.capability_folders()
    assert folders == [command_sandbox._real(home / ".agents/skills"), command_sandbox._real(home / "plugins")]
    assert all(folder in command_sandbox.default_protected() for folder in folders)


def test_commands_cannot_read_or_write_them_in_or_out_of_the_sandbox(home):
    inside = command_sandbox.commands_profile(home / "ws")
    outside = command_sandbox.minimal_profile()
    for folder in (home / ".agents/skills", home / "plugins"):
        assert _closed_in(inside, folder) and _closed_in(outside, folder), folder


def test_an_mcp_server_granted_the_home_folder_still_cannot_reach_them(home, tmp_path):
    text = capability_sandbox.profile(root=tmp_path / "server", folders=[home], network=False, read=[])
    lines = text.splitlines()
    granted = next(i for i, line in enumerate(lines) if line.startswith("(allow file-read* file-write*")
                   and f'"{command_sandbox._real(home)}"' in line)
    closed = next(i for i, line in enumerate(lines) if line.startswith("(deny file-read* file-write*")
                  and f'"{command_sandbox._real(home / ".agents/skills")}"' in line)
    assert granted < closed                                            # the last rule wins


def test_a_link_to_the_skill_folder_is_judged_where_it_points(home):
    real = home / "ws/agents-real"
    (real / "skills").mkdir(parents=True)
    (home / ".agents").symlink_to(real)
    assert command_sandbox._real(real / "skills") in command_sandbox.capability_folders()
    assert _closed_in(command_sandbox.commands_profile(home / "ws"), real / "skills")


# ── the file tools ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("where, deeper", [
    (".agents/skills/new/SKILL.md", ".agents/skills/made/new/SKILL.md"),
    ("plugins/tool/run.py", "plugins/made/run.py"),
    ("data/arslan.db", "data/made/arslan.db"),
])
def test_the_file_tools_never_write_them_even_inside_the_working_folder(home, monkeypatch, where, deeper):
    """The working folder is the whole home here, so each of these is inside it."""
    monkeypatch.setattr(config, "data_dir", lambda: home / "data")
    for folder in (".agents/skills/new", "plugins/tool", "data"):
        (home / folder).mkdir(parents=True, exist_ok=True)
    with pytest.raises(workspace_paths.NeverWritten) as refused:
        workspace_paths.resolve_in_workspace(where, home, for_write=True)
    assert "never written by a tool" in str(refused.value)
    with pytest.raises(workspace_paths.NeverWritten):                  # folders it would make there, too
        workspace_paths.resolve_in_workspace(deeper, home, for_write=True, make_parents=True)


def test_the_file_tools_still_write_the_rest_of_the_working_folder(home):
    assert workspace_paths.resolve_in_workspace("ws/notes.md", home, for_write=True) == (home / "ws/notes.md").resolve()
    assert workspace_paths.resolve_in_workspace(".agents/skills/x", home) == (home / ".agents/skills/x").resolve()  # reads stay

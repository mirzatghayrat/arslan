"""SBX-5a, second round (#772 review): the protected folders through aliases, moves and an unreadable scan.

- The file tools judge a protected folder by what is on disk, `(st_dev, st_ino)` of every existing ancestor, so a
  case or Unicode spelling of a folder, or another path to the same one, is refused like the folder. A part that
  doesn't exist yet is compared by its folded name (casefold, NFC). The eval's marked folder is exempt by the same
  identity, so its case spelling still writes.
- Seatbelt matches the folder on disk, not the spelling: a deny on a folder refuses its case and NFD spellings
  (measured here). What it can't tell apart is a hard link from the original, which stays a stated limit.
- The folders between a writable root and a protected path are held (`command_sandbox.held_ancestors`): a process
  can't rename one away with the protected folder inside it, remove one and make it again, or put a link where one
  was; writing beside them still works.
- An MCP server's folder that can't be scanned all through doesn't start.

All targets are stand-ins under a scratch HOME. The probe prints one word per check, never contents.
"""
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

import pytest

from server import config
from server.services import capability_sandbox, command_sandbox, terminal_exec, workspace_paths

macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")

PLUGIN = unicodedata.normalize("NFC", "plugíns")          # a configurable name with a composed letter
PLUGIN_NFD = unicodedata.normalize("NFD", PLUGIN)
REFUSED = {"EPERM", "EACCES"}

# (name, action, path[, other]) -> "ok" or the errno's name.
PROBE = """
import errno, json, os, sys
out = {}
for name, action, path, *rest in json.loads(sys.argv[1]):
    try:
        if action == 'read':
            open(path).read()
        elif action == 'write':
            with open(path, 'a') as f:
                f.write('changed')
        elif action == 'create':
            with open(path, 'x') as f:
                f.write('x')
        elif action == 'mkdir':
            os.mkdir(path)
        elif action == 'rmdir':
            os.rmdir(path)
        elif action == 'unlink':
            os.unlink(path)
        elif action == 'rename':
            os.rename(path, rest[0])
        elif action == 'symlink':
            os.symlink(rest[0], path)
        out[name] = 'ok'
    except OSError as exc:
        out[name] = errno.errorcode.get(exc.errno, str(exc.errno))
print(json.dumps(out))
"""


def _sentinel(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "sentinel"
    path.write_text("original")
    return path


@pytest.fixture
def home(monkeypatch, tmp_path):
    """A scratch HOME (Path.home() follows it), a scratch temp root and a scratch data folder two levels down, so
    it has ancestors of its own to hold."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    temp = tmp_path / "t"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    data = home / "state" / "app" / "data"
    data.mkdir(parents=True)
    monkeypatch.setattr(config, "data_dir", lambda: data)
    monkeypatch.setattr(command_sandbox, "PLUGIN_FOLDER", home / "bundles" / PLUGIN)
    return home


def _aliasing(folder: Path) -> bool:
    """Whether this volume folds case (APFS's default does): the aliases below only exist on one that does."""
    return folder.with_name(folder.name.upper()).exists()


# ── the file tools: identity, not spelling ───────────────────────────────────────────

def _file_tools(monkeypatch, root_box: list):
    from server.registry import file_tools

    async def workspace():
        return root_box[0]

    monkeypatch.setattr(file_tools, "_workspace_root", workspace)
    return file_tools.WriteFileExecutor().execute, file_tools.EditFileExecutor().execute


def _spellings(home: Path, sentinel: Path) -> list[tuple[Path, str]]:
    """(working folder, path) pairs that reach `sentinel` by another spelling of its protected folder: the
    folder's name upper-cased, NFD where it has an accent, and on macOS the whole working folder through
    /System/Volumes/Data, the same folders under a prefix no folding of names reaches."""
    relative = sentinel.relative_to(home)
    folder = relative.parent
    out = [(home, str(folder.with_name(folder.name.upper()) / relative.name))]
    if folder.name != unicodedata.normalize("NFD", folder.name):
        out.append((home, str(folder.with_name(unicodedata.normalize("NFD", folder.name)) / relative.name)))
    firmlinked = Path("/System/Volumes/Data" + str(home.resolve()))
    if firmlinked.is_dir():
        out.append((firmlinked, str(relative)))
    return out


@pytest.mark.macos
@pytest.mark.skipif(sys.platform != "darwin", reason="case and normalization aliases need APFS")
async def test_the_file_tools_refuse_every_spelling_of_a_protected_folder(home, monkeypatch):
    data = config.data_dir()
    sentinels = [_sentinel(home / ".agents" / "skills"), _sentinel(home / "bundles" / PLUGIN), _sentinel(data)]
    assert _aliasing(sentinels[0].parent), "this volume does not fold case"
    root = [home]
    write, edit = _file_tools(monkeypatch, root)
    for sentinel in sentinels:
        spellings = _spellings(home, sentinel)
        assert len(spellings) >= 2, spellings
        for root[0], spelling in spellings:
            refused = await write({"path": spelling, "content": "changed"})
            assert refused["ok"] is False and "skills, plugins or data" in refused["error"], spelling
            refused = await edit({"path": spelling, "old_string": "original", "new_string": "changed"})
            assert refused["ok"] is False and "skills, plugins or data" in refused["error"], spelling
            assert sentinel.read_text() == "original", spelling
    # The data folder as the working folder, by another spelling: still Arslan's data.
    root[0] = data.with_name(data.name.upper())
    assert (await write({"path": "ordinary", "content": "x"}))["ok"] is False
    (data / "ordinary").write_text("original")
    assert (await edit({"path": "ordinary", "old_string": "original", "new_string": "x"}))["ok"] is False
    assert (data / "ordinary").read_text() == "original"
    # The eval's marked folder by another spelling is the same folder: it writes (the two former ordinary failures).
    (data / "workspace").mkdir()
    root[0] = data / "WORKSPACE"
    assert (await write({"path": "brief.md", "content": "ok"}))["ok"] is True
    assert (await edit({"path": "brief.md", "old_string": "ok", "new_string": "fine"}))["ok"] is True
    assert (data / "workspace" / "brief.md").read_text() == "fine"
    # Ordinary files beside them still write.
    root[0] = home
    assert (await write({"path": "notes.md", "content": "ok"}))["ok"] is True


def test_a_folder_that_doesnt_exist_yet_is_compared_by_its_folded_name(home):
    """No inode to compare yet: `make_parents` would make the folder, so its name is folded and compared. Holds on
    a case-sensitive volume too, where it refuses a name that would be a different folder (closed, not open)."""
    (home / ".agents").mkdir()                                    # skills itself not made yet
    (home / "bundles").mkdir()                                    # nor the plugin folder
    for path in (".agents/SKILLS/x/SKILL.md", ".agents/Skills/new.md", f"bundles/{PLUGIN_NFD}/x.md",
                 f"bundles/{PLUGIN.upper()}/x.md", "state/APP/DATA/x.db"):
        with pytest.raises(workspace_paths.PathEscape, match="skills, plugins or data"):
            workspace_paths.resolve_in_workspace(path, home, for_write=True, make_parents=True)
    for path in (".agents/skillset/x.md", "bundles/plugin/x.md", "state/app/database/x.db"):    # look-alikes
        assert workspace_paths.resolve_in_workspace(path, home, for_write=True, make_parents=True)


def test_the_identity_walk_reaches_a_folder_through_any_existing_ancestor(home):
    """A deeper path inside the protected folder, a spelling of an ancestor, and a missing part below it."""
    (home / ".agents" / "skills" / "deep").mkdir(parents=True)
    if not _aliasing(home / ".agents"):
        pytest.skip("this volume does not fold case")
    for path in (".AGENTS/skills/deep/x.md", ".agents/SKILLS/deep/new/x.md"):
        with pytest.raises(workspace_paths.PathEscape, match="skills, plugins or data"):
            workspace_paths.resolve_in_workspace(path, home, for_write=True, make_parents=True)


# ── the MCP scan fails closed ─────────────────────────────────────────────────────────

@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="root reads a mode-0 folder")
def test_a_server_folder_the_scan_cant_read_all_through_does_not_start(home, tmp_path):
    root = tmp_path / "srv"
    locked = root / "lib" / "locked"
    locked.mkdir(parents=True)
    outside = _sentinel(tmp_path / "outside")
    os.link(outside, locked / "planted")
    sandbox = {"root": str(root), "folders": [], "network": False}
    locked.chmod(0)
    try:
        with pytest.raises(capability_sandbox.OutsideLink, match="can't be checked"):
            capability_sandbox.wrap("/bin/echo", [], {"PATH": "/usr/bin"}, sandbox)
    finally:
        locked.chmod(0o700)
    (locked / "planted").unlink()
    capability_sandbox.wrap("/bin/echo", [], {"PATH": "/usr/bin"}, sandbox)       # readable and clean: starts


# ── the held ancestors (portable: what the profiles are made of) ─────────────────────

def test_held_ancestors_are_the_folders_between_a_writable_root_and_a_protected_path(home, tmp_path):
    skills = home / ".agents" / "skills"
    skills.mkdir(parents=True)
    held = command_sandbox.held_ancestors([home], [skills])
    assert held == [home.resolve(), (home / ".agents").resolve()]
    assert command_sandbox.held_ancestors([home / "work"], [skills]) == []                 # a narrow root: none
    assert command_sandbox.held_ancestors([home], [home / ".nothing" / "here"]) == []      # nothing to move
    # A CAP6b folder that isn't there yet is held all the same, and by the link on its way as well as the target.
    elsewhere = home / "elsewhere"
    elsewhere.mkdir()
    link = home / "linked"
    link.symlink_to(elsewhere, target_is_directory=True)
    planted = command_sandbox.held_ancestors([home], [], planted=[link / "skills"])
    assert {home.resolve() / "linked", elsewhere.resolve()} <= set(planted)


# ── macOS: real seatbelt ─────────────────────────────────────────────────────────────

def _probe(checks) -> list[str]:
    return [sys.executable, "-I", "-c", PROBE, json.dumps([[str(part) for part in check] for check in checks])]


def _outcome(stdout: str) -> dict:
    return json.loads(stdout.strip().splitlines()[-1])


async def _commands(home: Path, checks, *, sandbox: bool = True) -> dict:
    command = " ".join(shlex.quote(part) for part in _probe(checks))
    result = await terminal_exec.run(command, cwd=home, sandbox=sandbox, offline=True)
    assert result["sandbox"] == ("workspace" if sandbox else "outside"), result.get("error")
    return _outcome(result["stdout"])


def _mcp(home: Path, tmp_path: Path, checks) -> dict:
    command, args, env, cwd = capability_sandbox.wrap(
        sys.executable, _probe(checks)[1:], {"PATH": "/usr/bin:/bin"},
        {"root": str(tmp_path / "server"), "folders": [str(home)], "network": False,
         "read": [sys.prefix, sys.base_prefix]})
    result = subprocess.run([command, *args], env=env, cwd=cwd, capture_output=True, text=True, timeout=60,
                            stdin=subprocess.DEVNULL)
    assert result.returncode == 0, result.returncode
    return _outcome(result.stdout)


async def _run(surface: str, home: Path, tmp_path: Path, checks) -> dict:
    if surface == "mcp":
        return _mcp(home, tmp_path, checks)
    return await _commands(home, checks, sandbox=surface == "commands")


@pytest.mark.macos
@macos
async def test_seatbelt_matches_the_folder_on_disk_not_the_spelling(home):
    """The measurement item 3 of the review asked for: a case or NFD spelling of a closed folder is refused, so the
    kernel's remaining aliases are hard links, which a path rule can't tell from the original."""
    skills, plugin = _sentinel(home / ".agents" / "skills"), _sentinel(home / "bundles" / PLUGIN)
    assert _aliasing(skills.parent), "this volume does not fold case"
    spellings = {"skills-case": home / ".agents" / "SKILLS" / "sentinel",
                 "plugin-case": home / "bundles" / PLUGIN.upper() / "sentinel",
                 "plugin-nfd": home / "bundles" / PLUGIN_NFD / "sentinel"}
    out = await _commands(home, [*((f"{n}-read", "read", p) for n, p in spellings.items()),
                                 *((f"{n}-write", "write", p) for n, p in spellings.items())])
    assert set(out.values()) <= REFUSED, out
    assert skills.read_text() == plugin.read_text() == "original"


# Each stand-in, the ancestor moved away (inside the wide root), and the surfaces that protect it.
_MOVES = {"skills": (".agents/skills", ".agents"), "plugin": (f"bundles/{PLUGIN}", "bundles"),
          "data": ("state/app/data", "state"), "data-parent": ("state/app/data", "state/app"),
          "Library-Caches": ("Library/Caches", "Library")}
_SURFACES = {"commands": tuple(_MOVES), "mcp": tuple(_MOVES), "outside": ("skills", "plugin", "data", "data-parent")}


@pytest.mark.macos
@macos
@pytest.mark.parametrize("surface,target", [(s, t) for s, targets in _SURFACES.items() for t in targets])
async def test_an_ancestor_of_a_protected_folder_cant_be_moved_away(home, tmp_path, surface, target):
    folder, ancestor = _MOVES[target]
    sentinel = _sentinel(home / folder)
    moved = home / "moved"
    spelt = home / ancestor
    spelt = spelt.with_name(spelt.name.upper())                     # the same folder, by another spelling
    out = await _run(surface, home, tmp_path, [
        ("rename", "rename", home / ancestor, moved), ("rename-case", "rename", spelt, moved),
        ("beside-create", "create", home / ancestor / "beside.txt"), ("beside-mkdir", "mkdir", home / ancestor / "d"),
        ("beside-unlink", "unlink", home / ancestor / "beside.txt")])
    assert {out["rename"], out["rename-case"]} <= REFUSED, out
    assert (out["beside-create"], out["beside-mkdir"], out["beside-unlink"]) == ("ok", "ok", "ok"), out
    assert not moved.exists() and sentinel.read_text() == "original"


@pytest.mark.macos
@macos
@pytest.mark.parametrize("surface", ["commands", "mcp", "outside"])
async def test_an_ancestor_cant_be_replaced_by_a_new_folder_or_a_link(home, tmp_path, surface):
    """No skills folder yet, so nothing to rename: the attack is to put one where Arslan will look. Removing the
    empty ~/.agents and making it again, linking a missing one to a folder of the process's own, or retargeting a
    link already on the way are all refused; making folders and links beside them still works."""
    (home / ".agents").mkdir()                                       # its own ~/.agents, no skills in it
    fake = home / "fake"
    (fake / "skills").mkdir(parents=True)
    real_bundles = home / "real-bundles"                             # the plugin folder's parent is a link
    real_bundles.mkdir()
    (home / "bundles").symlink_to(real_bundles, target_is_directory=True)
    out = await _run(surface, home, tmp_path, [
        ("rmdir", "rmdir", home / ".agents"), ("relink-plugin-parent", "unlink", home / "bundles"),
        ("rename-plugin-parent", "rename", home / "bundles", home / "moved"),
        ("plugin-in-target", "mkdir", real_bundles / PLUGIN),
        ("beside-mkdir", "mkdir", home / "other"), ("beside-link", "symlink", home / "other-link", fake)])
    assert {out["rmdir"], out["relink-plugin-parent"], out["rename-plugin-parent"],
            out["plugin-in-target"]} <= REFUSED, out
    assert (out["beside-mkdir"], out["beside-link"]) == ("ok", "ok"), out
    (home / ".agents").rmdir()                                       # now missing: no link and no folder there
    out = await _run(surface, home, tmp_path, [("link-missing", "symlink", home / ".agents", fake),
                                               ("mkdir-missing", "mkdir", home / ".agents")])
    assert set(out.values()) <= REFUSED, out
    assert not (home / ".agents").exists() and (home / "bundles").resolve() == real_bundles.resolve()

"""HR-1 review delta 9 (v0.1.64) under real seatbelt: consumer aliases.

A held name (`.vscode/settings.json`, `.envrc`, a git hook) or a held folder (`.vscode`) that is a link whose real
path is in a dependency folder: seatbelt sees the real path, which the node_modules exemption leaves open, while the
consumer (an editor, git, an agent) reads the file through the held name. The fix, measured here in the commands
preset, an MCP server's granted folder and the outside floor that holds them:

- a link that exists when the profile is built (part 1): when a held name or held folder name links out of its folder
  (into node_modules or anywhere), that profile has no dependency exemption, and the link's real path and the folders
  above it are held in place; a write through it is refused and the target stays as it was;
- a link made during the run (part 2): `file-write-create` of a SYMLINK at a held name or held folder name is
  refused, by `symlink` or by renaming a link made elsewhere onto it; an ordinary file or folder of those names, and
  an ordinary link elsewhere, are made as before.

The measurement the rule rests on (2026-11-11, macOS 26.6.2): sandbox-exec accepts `(deny file-write-create
(require-all (vnode-type SYMLINK) (regex ...)))`, refuses `symlink` at a matching name, and refuses the rename of a
link made under an ordinary name onto one; a file and a folder renamed onto those names, and `mkdir`, are not refused.

Stand-in names and plain paths only.
"""
import json
import os
import sys

import pytest

from server.services import command_sandbox, run_later
from tests.server.sbx.test_hr1_run_later_kernel import _floor_profile

STAND_IN = "zz-stand-in-word"
DEPENDENCY = f"node_modules/{STAND_IN}"
macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")

#: Each step a list: ["write", path] | ["symlink", target, path] | ["rename", source, target] | ["mkdir", path].
#: Paths are relative to the folder given first; the result is "done", "refused" (EPERM) or "error <errno>".
_OPS = """
import json, os, sys
folder, steps = sys.argv[1], json.loads(sys.argv[2])
out = []
for op, *args in steps:
    paths = [a if op == 'symlink' and i == 0 else os.path.join(folder, a) for i, a in enumerate(args)]
    try:
        if op == 'write':
            with open(paths[0], 'w') as handle:
                handle.write('zz')
        elif op == 'symlink':
            os.symlink(paths[0], paths[1])
        elif op == 'rename':
            os.rename(paths[0], paths[1])
        elif op == 'mkdir':
            os.mkdir(paths[0])
    except PermissionError:
        out.append('refused')
    except OSError as error:
        out.append(f'error {error.errno}')
    else:
        out.append('done')
print(json.dumps(out))
"""

PRESETS = ["commands", "mcp", "outside-floor"]


def _folder(sbx):
    """The folder the preset makes writable: the work folder, or the MCP server's granted folder."""
    if sbx.base == "mcp":
        granted = sbx.root / "granted"
        granted.mkdir(exist_ok=True)
        sbx.granted_folders = [granted]
        return granted
    return sbx.work


def _profile(sbx) -> str:
    """The preset's profile, built now (after the test laid out its folder: the walk runs at build)."""
    return _floor_profile(sbx) if sbx.base == "outside-floor" else sbx.profile()


def _run(sbx, folder, steps) -> list[str]:
    ran = sbx.python(_OPS, folder, json.dumps(steps), probe="hr1-alias", profile=_profile(sbx))
    assert ran.returncode == 0, ran.stderr
    return json.loads(ran.stdout)


def _file(path, content="old") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _link(folder, name: str, target: str) -> None:
    """`folder/name` -> `folder/target`, as a relative link (as a package manager or a user makes one)."""
    link = folder / name
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(os.path.relpath(folder / target, link.parent))


#: The seven alias shapes: (the held name or held folder that is a link, its target in a dependency folder, the held
#: name written through it). The six families by a held name, and a held folder.
SHAPES = {
    "git": (".git/hooks/pre-commit", f"{DEPENDENCY}/.git/hooks/pre-commit", ".git/hooks/pre-commit"),
    "envrc": (".envrc", f"{DEPENDENCY}/.envrc", ".envrc"),
    "editor": (".vscode/settings.json", f"{DEPENDENCY}/.vscode/settings.json", ".vscode/settings.json"),
    "agent": (".claude/settings.json", f"{DEPENDENCY}/.claude/settings.json", ".claude/settings.json"),
    "package": (".npmrc", f"{DEPENDENCY}/.npmrc", ".npmrc"),
    "hooks": (".pre-commit-config.yaml", f"{DEPENDENCY}/.pre-commit-config.yaml", ".pre-commit-config.yaml"),
    "held-folder": (".vscode", f"{DEPENDENCY}/.vscode", ".vscode/tasks.json"),
}
#: A held name in another dependency, no link to it: held too once the exemption is off.
OTHER = f"node_modules/{STAND_IN}-other/.vscode/launch.json"


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", PRESETS, indirect=True)
@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_a_held_name_linked_into_a_dependency_is_refused_and_so_is_the_dependencys(sbx, shape):
    """Part 1: a write through the link is refused and its target is unchanged on disk; with the exemption off, a held
    name in another dependency is refused too (before #813 review 9 both were written). The target is held in place,
    so it can't be renamed away, written under another name and renamed back."""
    folder = _folder(sbx)
    name, target, written = SHAPES[shape]
    if name == written:
        _file(folder / target)
    else:
        _file(folder / target / os.path.relpath(written, name))
    _link(folder, name, target)
    _file(folder / OTHER)
    steps = [["write", written], ["write", OTHER], ["rename", target, f"{target}-{STAND_IN}"]]
    assert _run(sbx, folder, steps) == ["refused"] * 3
    assert (folder / written).read_text() == "old" and (folder / OTHER).read_text() == "old"


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", PRESETS, indirect=True)
def test_a_held_name_linked_into_an_ordinary_sibling_folder_is_refused_and_turns_the_exemption_off(sbx):
    """Part 1, "leaves its folder for any reason": a held name linked to an ordinary file in a sibling folder (its real
    path held in place), and a held folder linked to a sibling's held folder, are refused through the link; with no
    link into node_modules at all, a dependency's held name is refused too."""
    folder = _folder(sbx)
    _file(folder / f"{STAND_IN}-sibling" / f"{STAND_IN}-envrc")
    _link(folder, ".envrc", f"{STAND_IN}-sibling/{STAND_IN}-envrc")
    _file(folder / f"{STAND_IN}-sibling" / ".vscode" / "tasks.json")
    _link(folder, ".vscode", f"{STAND_IN}-sibling/.vscode")
    _file(folder / DEPENDENCY / ".vscode" / "tasks.json")
    steps = [["write", ".envrc"], ["write", ".vscode/tasks.json"], ["write", f"{DEPENDENCY}/.vscode/tasks.json"]]
    assert _run(sbx, folder, steps) == ["refused"] * 3
    assert (folder / f"{STAND_IN}-sibling" / f"{STAND_IN}-envrc").read_text() == "old"
    assert (folder / DEPENDENCY / ".vscode" / "tasks.json").read_text() == "old"


#: Held folder names, then held names, where a link may not be made during the run.
NEW_LINKS = [".vscode", ".git", ".claude", ".cursor", ".envrc", ".npmrc", ".mcp.json", ".pre-commit-config.yaml",
             ".husky"]


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", PRESETS, indirect=True)
def test_no_link_is_made_at_a_held_name_during_the_run_and_ordinary_ones_are(sbx):
    """Part 2: `symlink` at each held folder name and held name is refused, and so is renaming a link made under an
    ordinary name onto one; nothing is left at those names. Controls: with no alias, a dependency's held name is
    written (the exemption still works), the ordinary link is made, and an ordinary folder of a held folder's name
    is made (what git init and a first .vscode do)."""
    folder = _folder(sbx)
    _file(folder / DEPENDENCY / ".vscode" / "settings.json")
    into = f"{DEPENDENCY}/.vscode"
    steps = [["write", f"{DEPENDENCY}/.vscode/settings.json"], ["symlink", into, f"{STAND_IN}-link"],
             *(["symlink", into, name] for name in NEW_LINKS),
             *(["rename", f"{STAND_IN}-link", name] for name in NEW_LINKS),
             ["mkdir", ".vscode"], ["mkdir", ".git"]]
    assert _run(sbx, folder, steps) == ["done", "done", *["refused"] * (2 * len(NEW_LINKS)), "done", "done"]
    assert not any(os.path.islink(folder / name) for name in NEW_LINKS)
    assert os.path.islink(folder / f"{STAND_IN}-link") and (folder / ".vscode").is_dir()
    assert (folder / DEPENDENCY / ".vscode" / "settings.json").read_text() == "zz"


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", ["commands"], indirect=True)
def test_the_symlink_rule_alone_refuses_links_and_nothing_else(sbx):
    """The measurement, on a profile that allows everything but `symlink_filters`: (a) sandbox-exec accepts it,
    (b) `symlink` at a held name and a held folder name is refused, (c) so is renaming a link made under an ordinary
    name onto either; a file and a folder renamed onto them, `mkdir` and an ordinary link are not."""
    text = ("(version 1)\n(allow default)\n(deny file-write-create " + " ".join(run_later.symlink_filters()) + ")\n")
    _file(sbx.work / f"{STAND_IN}.txt")
    (sbx.work / f"{STAND_IN}-dir").mkdir()
    steps = [["symlink", "x", ".envrc"], ["symlink", "x", ".vscode"], ["symlink", "x", f"{STAND_IN}-a"],
             ["symlink", "x", f"{STAND_IN}-b"], ["rename", f"{STAND_IN}-a", ".envrc"],
             ["rename", f"{STAND_IN}-b", ".vscode"], ["rename", f"{STAND_IN}.txt", ".envrc"],
             ["rename", f"{STAND_IN}-dir", ".vscode"], ["mkdir", ".claude"]]
    ran = sbx.python(_OPS, sbx.work, json.dumps(steps), probe="hr1-alias-measure", profile=text)
    assert ran.returncode == 0, ran.stderr                                                       # (a)
    assert json.loads(ran.stdout) == ["refused", "refused", "done", "done",                      # (b)
                                      "refused", "refused",                                      # (c)
                                      "done", "done", "done"]

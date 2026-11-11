"""HR-1 review delta 10 (v0.1.64) under real seatbelt: link targets.

git stores links, so a repository can check out `.vscode` as a link to `vsc` with no action in the sandbox at all.
Seatbelt matches the real path, `vsc/settings.json`, which has no held name, while VS Code reads it as
`.vscode/settings.json`. The fix (`run_later.link_filters`), measured here in the commands preset, an MCP server's
granted folder and the outside floor that holds them: when the walk finds a held name or held folder name that is a
link, the profile denies the held names at its real path, mapped through the link (`.vscode -> vsc`: `vsc`'s four
files; `.husky -> h`: all of `h`; `.claude -> c`: `c/settings*.json` and `c/launch.json`; `.git -> gd`: its hooks
and configs), and only those; a broken link's target can't be made.

Stand-in names and plain paths only.
"""
import os
import sys

import pytest

from server.services import command_sandbox
from tests.server.sbx.test_hr1_run_later_aliases import PRESETS, STAND_IN, _file, _folder, _link, _run
from tests.server.sbx.test_hr1_run_later_kernel import _git

macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")

SIB = f"{STAND_IN}-sib/deeper"

#: (the link, its target, relative to the folder, whether the target is a folder made before the run), then the files
#: written through the target: (path, "refused" or "done").
LAYOUTS = {
    "vscode": ((".vscode", "vsc", True), [("vsc/settings.json", "refused"), ("vsc/tasks.json", "refused"),
                                         ("vsc/mcp.json", "refused"), ("vsc/other.json", "done")]),
    "husky": ((".husky", "h", True), [("h/pre-commit", "refused"), ("h/_/husky.sh", "refused")]),
    "envrc": ((".envrc", "envrc.real", False), [("envrc.real", "refused"), (f"{STAND_IN}.real", "done")]),
    "claude": ((".claude", "c", True), [("c/settings.json", "refused"), ("c/settings.local.json", "refused"),
                                       ("c/launch.json", "refused"), ("c/notes.md", "done"),
                                       ("c/sub/settings.json", "done")]),
    "npmrc-deeper": ((".npmrc", f"{SIB}/npmrc", False), [(f"{SIB}/npmrc", "refused"), (f"{SIB}/other", "done")]),
    "vscode-deeper": ((".vscode", f"{SIB}/v", True), [(f"{SIB}/v/launch.json", "refused"),
                                                     (f"{SIB}/v/other.json", "done")]),
    "cursor-deeper": ((".cursor", f"{SIB}/cur", True), [(f"{SIB}/cur/rules.json", "refused"),
                                                       (f"{SIB}/cur/notes.md", "done"),
                                                       (f"{SIB}/cur/sub/x.json", "done")]),
    "vscode-file-link": ((".vscode/settings.json", f"{STAND_IN}-x.json", False),
                         [(f"{STAND_IN}-x.json", "refused"), (".vscode/other.json", "done")]),
}


def _lay_out(folder, link: str, target: str, is_folder: bool, writes) -> None:
    for path, _ in writes:
        _file(folder / path)
    if is_folder:
        (folder / target).mkdir(parents=True, exist_ok=True)
    _link(folder, link, target)


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", PRESETS, indirect=True)
@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_a_held_name_or_folder_that_is_a_link_has_the_held_names_at_its_target_held(sbx, layout):
    """The link exists before the profile is built, as a checkout leaves it. A held name at the target, by the link's
    mapping, is refused and stays as it was; the target's other files are written (not the whole subtree)."""
    folder = _folder(sbx)
    (link, target, is_folder), writes = LAYOUTS[layout]
    _lay_out(folder, link, target, is_folder, writes)
    assert _run(sbx, folder, [["write", path] for path, _ in writes]) == [want for _, want in writes]
    for path, want in writes:
        assert (folder / path).read_text() == ("old" if want == "refused" else "zz"), path


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", PRESETS, indirect=True)
def test_a_link_inside_a_linked_folder_at_a_held_name_is_followed(sbx):
    """Two hops, both checked out: `.claude -> c` with `c/settings.local.json` a link on (a `*` name, so not by its
    real path alone), `.husky -> h` with `h/pre-commit` a link on, `.cursor -> cur` with `cur/mcp.json` a link on.
    The files the consumer reaches are refused; an ordinary file beside them is written."""
    folder = _folder(sbx)
    for name in (f"{STAND_IN}-x.json", f"{STAND_IN}-hook", f"{STAND_IN}-cur.json", "c/notes.md", "h/.keep",
                 "cur/.keep"):
        _file(folder / name)
    for link, target in ((".claude", "c"), ("c/settings.local.json", f"{STAND_IN}-x.json"), (".husky", "h"),
                         ("h/pre-commit", f"{STAND_IN}-hook"), (".cursor", "cur"),
                         ("cur/mcp.json", f"{STAND_IN}-cur.json")):
        _link(folder, link, target)
    steps = [["write", f"{STAND_IN}-x.json"], ["write", f"{STAND_IN}-hook"], ["write", f"{STAND_IN}-cur.json"],
             ["write", "c/notes.md"]]
    assert _run(sbx, folder, steps) == ["refused"] * 3 + ["done"]
    assert (folder / f"{STAND_IN}-x.json").read_text() == "old"


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", PRESETS, indirect=True)
def test_a_broken_link_at_a_held_name_cannot_have_its_target_made(sbx):
    """A held folder and a held file linked to paths that don't exist (deeper too): making them is refused, as a
    file, a folder or a link, so nothing can appear there that a consumer would read through the link."""
    folder = _folder(sbx)
    _link(folder, ".vscode", "vsc-missing")
    _link(folder, ".envrc", "envrc-missing")
    _link(folder, ".husky", f"{STAND_IN}-gone/deeper/h")
    steps = [["mkdir", "vsc-missing"], ["write", "envrc-missing"], ["symlink", "elsewhere", "envrc-missing"],
             ["mkdir", f"{STAND_IN}-gone"], ["mkdir", f"{STAND_IN}-made"]]
    assert _run(sbx, folder, steps) == ["refused"] * 4 + ["done"]
    assert not any(os.path.lexists(folder / name) for name in ("vsc-missing", "envrc-missing", f"{STAND_IN}-gone"))


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", PRESETS, indirect=True)
def test_an_ordinary_link_and_a_folder_named_like_a_target_are_unaffected(sbx):
    """Controls: a link at an ordinary name to a folder holds nothing there; a `vsc` folder no held name links to is
    an ordinary folder."""
    folder = _folder(sbx)
    _file(folder / "vsc-free" / "settings.json")
    _link(folder, f"{STAND_IN}-link", "vsc-free")
    _file(folder / "vsc" / "settings.json")
    _file(folder / "c" / "settings.json")
    steps = [["write", "vsc-free/settings.json"], ["write", "vsc/settings.json"], ["write", "c/settings.json"]]
    assert _run(sbx, folder, steps) == ["done"] * 3


@pytest.mark.macos
@macos
@pytest.mark.parametrize("sbx", PRESETS, indirect=True)
def test_a_git_folder_that_is_a_link_has_its_hooks_and_config_held(sbx):
    """`.git -> gd`, a real repository's folder under another name (the link form; a `.git` file is HR-1c's): its
    hooks, config and a submodule's config are refused, its objects and the submodule's other files are written, and
    git still reads the repository through the link."""
    folder = _folder(sbx)
    assert _git(folder, "init", "-q").returncode == 0
    os.rename(folder / ".git", folder / "gd")
    (folder / ".git").symlink_to("gd")
    _file(folder / "gd" / "modules" / STAND_IN / "config")
    _file(folder / "gd" / "modules" / STAND_IN / f"{STAND_IN}.txt")
    config = (folder / "gd" / "config").read_text()
    steps = [["write", "gd/hooks/pre-commit"], ["write", "gd/config"], ["write", "gd/config.worktree"],
             ["write", f"gd/modules/{STAND_IN}/config"], ["write", f"gd/objects/{STAND_IN}"],
             ["write", f"gd/modules/{STAND_IN}/{STAND_IN}.txt"], ["rename", "gd", f"gd-{STAND_IN}"]]
    assert _run(sbx, folder, steps) == ["refused"] * 4 + ["done"] * 2 + ["refused"]
    assert (folder / "gd" / "config").read_text() == config
    assert not (folder / "gd" / "hooks" / "pre-commit").exists()
    assert _git(folder, "status", "--porcelain").returncode == 0

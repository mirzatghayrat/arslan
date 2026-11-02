"""SMART-8 delete cards (docs/plans/0164/SMART-feels-smart.md, "Delete cards"): allowing a delete outside the
working folder moves its targets to the Trash, when the delete reads with certainty and runs outside the sandbox.

A delete that can't be read runs as it always has, and its card says it is permanent; one the sandbox holds keeps
the sandbox's limits. Arslan never deletes from the Trash or empties it.
"""
import os
import re
from pathlib import Path

import pytest

from server.orchestrator import tool_loop
from server.services import command_sandbox, delete_to_trash as dt, terminal_exec, terminal_policy as tp


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


def _folder(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "notes.txt").write_text("keep me")
    return path


# ── what reads with certainty ────────────────────────────────────────────────

@pytest.mark.parametrize("command,targets", [
    ("rm -r /tmp/x", ("/tmp/x",)), ("rm -rf ~/old", ("~/old",)), ("rm a '/b c'", ("a", "/b c")),
    ("rm -- -odd", ("-odd",)), ("/bin/rm -Rv x", ("x",)), ("rm --recursive --force x", ("x",)),
    ("rmdir /tmp/empty", ("/tmp/empty",)), ("unlink /tmp/f", ("/tmp/f",)), ("rm -d /tmp/e", ("/tmp/e",)),
])
def test_a_plain_delete_reads_with_certainty(command, targets):
    assert dt.plan(command).targets == targets


@pytest.mark.parametrize("command", [
    "rm -rf ~/x/*", "rm -rf ~/x/[ab]", 'rm -rf "$DIR"', "rm $(cat list)", "rm `cat list`", "ls | xargs rm",
    "rm a; echo done", "rm a && ls", "rm a > log", "find ~/x -delete", "rm -i ~/x", "rm -P ~/x", "rmdir -p a/b",
    "unlink a b", "rm ~bob/x", "rm ~/x/", "rm ..", "rm ~/x/.", "rm", "rm -rf", "sudo rm x", "command rm x",
    "rm 'a\nb'", "rm a\\ b", "srm ~/x", "trash ~/x", "rm {a,b}", "rm 'unclosed",
])
def test_anything_else_does_not(command):
    assert dt.plan(command) is None


# ── the move itself ──────────────────────────────────────────────────────────

def test_allow_moves_the_targets_to_the_trash_and_the_originals_are_gone(home, tmp_path):
    old = _folder(tmp_path / "outside" / "old")
    (tmp_path / "outside" / "a.log").write_text("x")
    out = dt.move(f"rm -r {old} {tmp_path / 'outside' / 'a.log'}", tmp_path)
    assert out["ok"] and not old.exists() and not (tmp_path / "outside" / "a.log").exists()
    assert (home / ".Trash" / "old" / "notes.txt").read_text() == "keep me"
    assert (home / ".Trash" / "a.log").exists()
    assert [Path(m["to"]).name for m in out["trashed"]] == ["old", "a.log"]


def test_a_name_already_in_the_trash_gets_a_number(home, tmp_path):
    (home / ".Trash").mkdir()
    (home / ".Trash" / "a.log").write_text("earlier")
    (tmp_path / "a.log").write_text("now")
    dt.move(f"rm {tmp_path / 'a.log'}", tmp_path)
    assert (home / ".Trash" / "a.log").read_text() == "earlier"
    assert (home / ".Trash" / "a 2.log").read_text() == "now"


def test_a_link_is_moved_itself_never_what_it_points_to(home, tmp_path):
    real = _folder(tmp_path / "real")
    (tmp_path / "link").symlink_to(real)
    dt.move(f"rm {tmp_path / 'link'}", tmp_path)
    assert (home / ".Trash" / "link").is_symlink() and (real / "notes.txt").exists()


@pytest.mark.parametrize("command,why", [
    ("rm {d}", "is a directory"), ("rmdir {d}", "Directory not empty"), ("rm -d {d}", "Directory not empty"),
    ("unlink {d}", "is a directory"), ("rm {missing}", "No such file or directory"),
])
def test_a_target_the_command_would_fail_on_is_left_where_it_is(home, tmp_path, command, why):
    d = _folder(tmp_path / "d")
    out = dt.move(command.format(d=d, missing=tmp_path / "missing"), tmp_path)
    assert not out["ok"] and why in out["stderr"] and (d / "notes.txt").exists()
    assert not (home / ".Trash").exists() or not any((home / ".Trash").iterdir())


def test_rm_f_on_nothing_is_quiet(home, tmp_path):
    out = dt.move(f"rm -f {tmp_path / 'missing'}", tmp_path)
    assert out["ok"] and out["trashed"] == []


def test_another_disk_without_a_trash_is_refused_and_nothing_is_copied(home, tmp_path, monkeypatch):
    target = _folder(tmp_path / "ext" / "x")
    real_lstat = os.lstat

    class Stat:
        def __init__(self, st, dev):
            self.st_dev, self._st = dev, st

        def __getattr__(self, name):
            return getattr(self._st, name)

    def lstat(path, *a, **k):     # everything under ext/ is on another device, and that disk has no .Trashes
        st = real_lstat(path, *a, **k)
        return Stat(st, 999) if str(tmp_path / "ext") in str(path) else st
    monkeypatch.setattr(dt.os, "lstat", lstat)
    out = dt.move(f"rm -r {target}", tmp_path)
    assert not out["ok"] and "no Trash" in out["stderr"] and (target / "notes.txt").exists()


# ── Arslan never empties the Trash ───────────────────────────────────────────

@pytest.mark.parametrize("command", [
    "rm -rf ~/.Trash/*", "rm ~/.Trash/old.txt", "rm -rf ~/.Trash", "rm -r '/Volumes/X/.Trashes/501'",
    "find ~/.Trash -mindepth 1 -delete", "find ~/.Trash -exec rm {} +", "unlink ~/.Trash/x",
    "osascript -e 'tell application \"Finder\" to empty trash'", "osascript -e 'tell app \"Finder\" to empty the trash'",
])
def test_a_delete_from_the_trash_or_emptying_it_is_forbidden(command):
    assert (tp.assess(command).level, tp.assess(command).rule) == ("forbid", "trash")


@pytest.mark.parametrize("command", ["ls ~/.Trash", "mv old.txt ~/.Trash/", "du -sh ~/.Trash", "rm notes-on-trash.txt"])
def test_looking_at_or_moving_into_the_trash_is_not(command):
    assert tp.assess(command).rule != "trash"


def test_the_move_refuses_a_target_in_the_trash(home, tmp_path):
    inside = _folder(home / ".Trash" / "kept")
    out = dt.move(f"rm -r {inside}", tmp_path)
    assert not out["ok"] and "never deletes from the Trash" in out["stderr"] and inside.exists()


_DETECTORS = {"terminal_policy.py", "hands_service.py"}


def test_no_server_code_deletes_from_or_empties_the_trash():
    """Source pin: nothing names the Trash next to a delete, except the patterns that detect one (the forbid rule
    here, and the Hands script rule that gives `empty trash` in an AppleScript its card)."""
    root = Path(__file__).resolve().parents[2] / "server"
    deletes = re.compile(r"rmtree|\.unlink\(|os\.remove|os\.rmdir|empty\s+(?:the\s+)?trash", re.I)
    hits = []
    for path in root.rglob("*.py"):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if ".Trash" in line and deletes.search(line):
                hits.append(f"{path.relative_to(root)}:{n}")
            elif re.search(r"empty\s+(?:the\s+)?trash", line, re.I) and path.name not in _DETECTORS:
                hits.append(f"{path.relative_to(root)}:{n}")
    assert hits == []


# ── the tool loop: which card, and what allow does ───────────────────────────

class _Exec:
    key = "run_command"

    def __init__(self, denied_first=False):
        self.ran: list[bool] = []
        self.denied_first = denied_first

    async def execute(self, args):
        self.ran.append(dt.TRASH.get())
        if self.denied_first and len(self.ran) == 1:
            return {"ok": False, "exit_code": 1, "stdout": "", "stderr": "", "sandbox_denied": True}
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""}


async def _run(monkeypatch, args, *, sandbox_on, available=True, exec_=None):
    ex = exec_ or _Exec()
    monkeypatch.setitem(tool_loop.EXECUTORS, "run_command", ex)

    async def sandbox():
        return sandbox_on

    async def no():
        return False

    async def no_network(*a, **k):
        return {}
    monkeypatch.setattr(tool_loop, "_sandbox_enabled", sandbox)
    monkeypatch.setattr(tool_loop, "_asks_for_everything", no)
    monkeypatch.setattr(tool_loop, "_network_after_outside_content", no_network)
    monkeypatch.setattr(command_sandbox, "available", lambda: available)
    asked: list[dict] = []

    async def cards(command, argv, **kw):
        asked.append(kw)
        return True

    async def resolve():
        return [{"key": "run_command", "description": "run"}]
    await tool_loop._dispatch_tool("run_command", args, "{}", resolve_tools=resolve, emit=lambda e: None,
                                   tool_timeout_s=5, tool_trace=[], convo=[], confirm_command=cards,
                                   conversation_id="c1")
    return ex, asked


async def test_with_no_sandbox_an_allowed_delete_goes_to_the_trash(monkeypatch):
    ex, asked = await _run(monkeypatch, {"command": "rm -r /tmp/smart8-old"}, sandbox_on=False)
    assert asked == [{"delete": "trash"}] and ex.ran == [True]


async def test_the_outside_card_moves_it_to_the_trash_too(monkeypatch):
    ex, asked = await _run(monkeypatch, {"command": "rm -r /tmp/smart8-old", "outside_sandbox": True},
                           sandbox_on=True)
    assert asked == [{"sandbox": "outside", "why": "", "delete": "trash"}] and ex.ran == [True]


async def test_in_the_sandbox_it_keeps_the_sandboxs_limits(monkeypatch):
    """The server never moves for a sandboxed command what the sandbox would refuse; the card says it's permanent
    there. When the sandbox stops it, the retry card runs it outside, and then it goes to the Trash."""
    ex, asked = await _run(monkeypatch, {"command": "rm -r /tmp/smart8-old"}, sandbox_on=True,
                           exec_=_Exec(denied_first=True))
    assert asked == [{"delete": "sandboxed"}, {"sandbox": "retry", "delete": "trash"}]
    assert ex.ran == [False, True]


@pytest.mark.parametrize("command", ["rm -rf ~/smart8/*", "ls | xargs rm", "find ~/smart8 -delete", 'rm -rf "$D"'])
async def test_a_delete_that_cant_be_read_runs_as_before_and_its_card_says_permanent(monkeypatch, command):
    ex, asked = await _run(monkeypatch, {"command": command}, sandbox_on=False)
    assert asked == [{"delete": "permanent"}] and ex.ran == [False]


async def test_a_delete_inside_the_working_folder_is_unchanged(monkeypatch):
    ex, asked = await _run(monkeypatch, {"command": "rm -r build"}, sandbox_on=False)
    assert all("delete" not in kw for kw in asked) and ex.ran == [False]


async def test_the_executor_moves_and_never_runs_the_command(home, tmp_path, monkeypatch):
    from server.registry.executors import RunCommandExecutor
    from server.services import checkpoints
    from tests.server.test_workspace_tool_gate import _wire
    ws = tmp_path / "ws"
    ws.mkdir()
    await _wire(tmp_path, monkeypatch, workspace=str(ws))

    async def nothing(*a, **k):
        return None

    async def never(*a, **k):
        raise AssertionError("the command ran")
    monkeypatch.setattr(checkpoints, "ensure", nothing)
    monkeypatch.setattr(terminal_exec, "run", never)
    old = _folder(tmp_path / "outside" / "old")
    token = dt.TRASH.set(True)
    try:
        out = await RunCommandExecutor().execute({"command": f"rm -r {old}"})
    finally:
        dt.TRASH.reset(token)
    assert out["ok"] and not old.exists() and (home / ".Trash" / "old" / "notes.txt").exists()


# ── what the card says ───────────────────────────────────────────────────────

@pytest.mark.parametrize("mode,words", [
    ("trash", "moves them to the Trash"), ("permanent", "deletes permanently; it can't go to the Trash"),
    ("sandboxed", "deleted permanently"),
])
async def test_the_card_says_how_allow_deletes(tmp_path, monkeypatch, mode, words):
    from server.services import command_confirm, permissions
    from tests.server.test_workspace_tool_gate import _wire
    await _wire(tmp_path, monkeypatch, workspace=str(tmp_path))
    seen = []

    async def decide(request, context):
        seen.append(request)
        return permissions.Decision(allowed=False, by="user")
    monkeypatch.setattr(permissions, "decide", decide)
    assert await command_confirm.Confirmations("c1").command("rm -rf ~/smart8/old", [], delete=mode) is False
    assert words in seen[0].title and words in seen[0].frame["reason"]

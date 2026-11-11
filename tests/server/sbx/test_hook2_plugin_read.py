"""HOOK-2 (docs/plans/0164/HOOK-plugin-hooks.md, rule 1): `commands_profile(plugin_read=...)` reopens one plugin's
own folder, read-only, for that plugin's hook. CAP6b keeps every other plugin folder, and the plugin root itself,
closed; writes stay denied everywhere under the root.

The macOS cases run the profile under real seatbelt with a probe that prints, per check, "ok" or the errno's name.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from server.services import command_sandbox

macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")

PROBE = """
import errno, json, pathlib, sys
out = {}
for name, action, path in json.loads(sys.argv[1]):
    p = pathlib.Path(path)
    try:
        if action == 'read':
            p.read_text()
        elif action == 'list':
            list(p.iterdir())
        else:
            p.write_text('changed')
        out[name] = 'ok'
    except OSError as exc:
        out[name] = errno.errorcode.get(exc.errno, str(exc.errno))
print(json.dumps(out))
"""
REFUSED = {"EPERM", "EACCES"}


@pytest.fixture
def plugins(monkeypatch, tmp_path):
    """A scratch HOME and temp root, a plugin root (CAP7's `PLUGIN_FOLDER`) holding plugins `a` and `b`, each with a
    sentinel, and in `a` a link to `b`'s sentinel."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    temp = tmp_path / "t"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    root = home / "plugins"
    for name in ("a", "b"):
        (root / name).mkdir(parents=True)
        (root / name / "sentinel").write_text("original")
    (root / "a" / "link").symlink_to(root / "b" / "sentinel")
    (root / "top").write_text("original")                      # a file in the root itself
    monkeypatch.setattr(command_sandbox, "PLUGIN_FOLDER", root)
    return root.resolve()


def _probe(profile: str, checks: list[tuple[str, str, Path]]) -> dict:
    path = command_sandbox.write_profile(profile)
    try:
        result = subprocess.run([command_sandbox._SANDBOX_EXEC, "-f", str(path), sys.executable, "-I", "-c", PROBE,
                                 json.dumps([(n, a, str(p)) for n, a, p in checks])],
                                capture_output=True, text=True, timeout=30)
    finally:
        command_sandbox.remove_profile(path)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


# ── portable: what the parameter accepts and where its rule goes ─────────────────────

def test_a_path_outside_the_plugin_root_or_the_root_itself_is_refused(plugins, tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "alias").symlink_to(plugins / "a", target_is_directory=True)
    for path in (plugins, elsewhere, plugins.parent, tmp_path / "alias", Path("plugins/a"), plugins / "a" / ".." / "b"):
        with pytest.raises(ValueError, match="plugin"):
            command_sandbox.commands_profile(work, offline=True, plugin_read=path)
    monkeypatch.setattr(command_sandbox, "PLUGIN_FOLDER", None)               # no plugin root: nothing to reopen
    with pytest.raises(ValueError, match="plugin"):
        command_sandbox.commands_profile(work, offline=True, plugin_read=plugins / "a")


def test_a_path_that_isnt_an_existing_folder_is_refused(plugins, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    for path in (plugins / "a" / "sentinel", plugins / "missing"):           # a file; nothing there
        with pytest.raises(ValueError, match="plugin"):
            command_sandbox.commands_profile(work, offline=True, plugin_read=path)


def test_a_folder_holding_a_closed_or_protected_path_is_refused(plugins, tmp_path, monkeypatch):
    """The allow comes after every deny, so it would reopen a closed or protected path at or under it."""
    from server import config
    work = tmp_path / "work"
    work.mkdir()
    (plugins / "a" / "inner").mkdir()
    for closed in ([plugins / "a"], [plugins / "a" / "inner"]):
        with pytest.raises(ValueError, match="closed or protected"):
            command_sandbox.commands_profile(work, offline=True, closed=closed, plugin_read=plugins / "a")
    command_sandbox.commands_profile(work, offline=True, closed=[plugins / "b"], plugin_read=plugins / "a")
    monkeypatch.setattr(config, "data_dir", lambda: plugins / "a" / "inner")   # Arslan's data, protected
    with pytest.raises(ValueError, match="closed or protected"):
        command_sandbox.commands_profile(work, offline=True, plugin_read=plugins / "a")


def test_one_read_only_rule_after_the_cap6b_deny_and_before_the_held_block(plugins, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    lines = command_sandbox.commands_profile(work, offline=True, plugin_read=plugins / "a").splitlines()
    rule = f'(allow file-read* (subpath "{plugins / "a"}"))'
    assert lines.count(rule) == 1
    assert [line for line in lines if str(plugins / "a") in line] == [rule]   # nothing else names it
    closing = max(i for i, line in enumerate(lines) if line.startswith("(deny file-read*") and str(plugins) in line)
    held = min(i for i, line in enumerate(lines) if line.startswith("(deny file-write-create"))
    assert closing < lines.index(rule) < held
    plain = command_sandbox.commands_profile(work, offline=True).splitlines()
    assert [line for line in lines if line != rule] == plain                  # the only difference


# ── macOS: under real seatbelt ───────────────────────────────────────────────────────

@pytest.mark.macos
@macos
@pytest.mark.parametrize("closed", [False, True], ids=["open-home", "work-in-a-closed-folder"])
def test_the_hooks_own_folder_is_readable_and_nothing_else_opens(plugins, tmp_path, closed):
    """With the work folder inside a closed folder, the profile reopens it and closes the protected paths again; the
    plugin's rule must come after that too."""
    shut = tmp_path / "Documents"
    work = (shut if closed else tmp_path) / "work"
    work.mkdir(parents=True)
    temp = tmp_path / "hook-temp"
    temp.mkdir()
    profile = command_sandbox.commands_profile(work, temp=temp, offline=True, closed=[shut] if closed else [],
                                               readable=[work], plugin_read=plugins / "a")
    out = _probe(profile, [("own-read", "read", plugins / "a" / "sentinel"), ("own-list", "list", plugins / "a"),
                           ("own-write", "write", plugins / "a" / "sentinel"), ("own-new", "write", plugins / "a" / "new"),
                           ("sibling-read", "read", plugins / "b" / "sentinel"),
                           ("link-read", "read", plugins / "a" / "link"), ("root-read", "read", plugins / "top"),
                           ("root-list", "list", plugins)])
    assert out["own-read"] == out["own-list"] == "ok"
    for name in ("own-write", "own-new", "sibling-read", "link-read", "root-read", "root-list"):
        assert out[name] in REFUSED, (name, out[name])
    assert (plugins / "a" / "sentinel").read_text() == "original" and not (plugins / "a" / "new").exists()


@pytest.mark.macos
@macos
def test_with_no_parameter_the_plugin_folder_stays_closed(plugins, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    out = _probe(command_sandbox.commands_profile(work, offline=True),
                 [("own-read", "read", plugins / "a" / "sentinel"), ("own-list", "list", plugins / "a")])
    assert out["own-read"] in REFUSED and out["own-list"] in REFUSED, out

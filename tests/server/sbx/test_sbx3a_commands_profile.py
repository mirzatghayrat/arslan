"""SBX-3 (v0.1.64), the commands' build half (3a), first part: what does not wait for SBX-2's base.

- `available()` starts the real commands profile, not `(allow default)`. A profile this macOS cannot start
  then reads as "unavailable" (today's card path) instead of failing every command.
- The writable roots come tagged (§1b): `in_scope` (the work folder), `shared_cache` (temp and the caches),
  `device` (the narrowed /dev entries). Temp is the run's own folder (test_sbx3_run_temp.py), in scope.
  `in_scope()` judges a path where it resolves.
- `deny_write_after_roots` (§e) is HR's parameter. It is written after the writable roots and before the
  protected paths, so the last rule wins.
- /dev is narrowed (§1) to the null and zero devices, the terminal, the descriptors and ptys.
- Mail, Messages and Photos data are closed (§1, the user's Q3), like Desktop/Documents/Downloads while that
  setting is off. Safari's data is already a protected path.
- The flip: commands run on SBX-2's default-deny base (`sandbox_profile.default_deny_profile`), with the user's
  D1 (listening stays denied) and D2 (online is any-declared until SBX-6, offline is none). What the base
  closes last, 3a reopens after it: the work and project folders inside a closed folder, then the protected
  paths again, then the saved copies.

Whether what should be denied is denied is not tested here. Those are Codex's real-seatbelt tests (SBX-3p).
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.services import command_sandbox, sandbox_profile, terminal_exec
from server.services.sandbox_profile import NetworkMode

macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")


# ── available() starts what commands run under ───────────────────────────────

def test_available_starts_the_real_commands_profile(monkeypatch, tmp_path):
    exe = tmp_path / "sandbox-exec"
    exe.write_text("")
    texts, calls = [], []
    written = command_sandbox.commands_profile

    def recorded(workspace, **kw):
        assert Path(workspace).is_dir()            # a real scratch folder while it starts
        texts.append(written(workspace, **kw))
        return texts[-1]

    monkeypatch.setattr(command_sandbox, "_SANDBOX_EXEC", str(exe))
    monkeypatch.setattr(command_sandbox.sys, "platform", "darwin")
    monkeypatch.setattr(command_sandbox, "commands_profile", recorded)
    monkeypatch.setattr(command_sandbox.subprocess, "run",
                        lambda argv, **kw: calls.append(argv) or SimpleNamespace(returncode=0))
    command_sandbox._reset_for_tests()
    try:
        assert command_sandbox.available() is True
    finally:
        command_sandbox._reset_for_tests()
    assert calls == [[str(exe), "-p", texts[0], "/usr/bin/true"]]
    assert texts[0].startswith("(version 1)\n(deny default)\n")     # the commands profile, on the base


def test_a_command_starts_under_the_same_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    assert command_sandbox.wrapper(tmp_path) == [command_sandbox._SANDBOX_EXEC, "-p",
                                                 command_sandbox.commands_profile(tmp_path)]


# ── §1b: tagged roots and the classifier's scope ─────────────────────────────

def test_the_writable_roots_are_tagged(tmp_path):
    roots = command_sandbox.writable_roots(tmp_path)
    assert [r for r in roots if r.tag == "in_scope"] == [command_sandbox.Root(str(tmp_path.resolve()), "in_scope")]
    tags = {r.path: r.tag for r in roots}
    home = Path.home()
    assert {path for path, tag in tags.items() if tag == "shared_cache"} == {
        str(command_sandbox._real(home / name)) for name in ("Library/Caches", ".cache", ".npm")}
    assert {r.path for r in roots if r.tag == "device"} == {
        "/dev/null", "/dev/zero", "/dev/tty", "/dev/ptmx", "/dev/fd", r"^/dev/ttys[0-9]+$"}
    assert "/dev" not in tags                                        # no longer all of /dev


@pytest.fixture
def work(tmp_path):
    """A work folder under <tmp>/private/var, with <tmp>/var linked to <tmp>/private/var as on macOS, and
    links out of it to a shared root and to the home folder."""
    ws = tmp_path / "private/var/ws"
    ws.mkdir(parents=True)
    (tmp_path / "var").symlink_to(tmp_path / "private/var")
    roots = command_sandbox.writable_roots(ws)
    (ws / "to-shared").symlink_to(next(r.path for r in roots if r.tag == "shared_cache"))
    (ws / "to-home").symlink_to(Path.home())
    return tmp_path, ws, roots


def test_in_scope_judges_a_path_where_it_resolves(work):
    T, ws, roots = work
    assert command_sandbox.in_scope(ws / "a.txt", roots)
    assert command_sandbox.in_scope(T / "var/ws/a.txt", roots)              # /var vs /private/var
    assert command_sandbox.in_scope(ws / "new/dir/file.txt", roots)         # a missing tail
    assert command_sandbox.in_scope(ws / "sub/../a.txt", roots)
    assert not command_sandbox.in_scope(ws / "../outside.txt", roots)       # `..` out of it
    assert not command_sandbox.in_scope(ws / "to-shared/pkg.tgz", roots)    # a link to a shared root
    assert not command_sandbox.in_scope(ws / "to-home/.zshrc", roots)       # a link to ~
    assert not command_sandbox.in_scope(Path(next(r.path for r in roots if r.tag == "shared_cache")) / "x", roots)


# ── §e: HR's parameter, and the order of the rules ───────────────────────────

def test_hrs_denies_come_after_the_writable_roots_and_before_the_protected_paths(tmp_path):
    for folder in ("ws", "closed/ws", "prot"):
        (tmp_path / folder).mkdir(parents=True)
    text = command_sandbox.profile(
        [tmp_path / "ws", tmp_path / "closed/ws"], [tmp_path / "prot"], closed=[tmp_path / "closed"],
        devices=('(literal "/dev/null")',), deny_write_after_roots=[tmp_path / "ws/placeholder"])
    assert text.replace(os.path.realpath(tmp_path), "<T>") == """\
(version 1)
(allow default)
(deny appleevent-send)
(deny file-write* (subpath "/"))
(allow file-write* (subpath "<T>/ws") (subpath "<T>/closed/ws"))
(allow file-write* (literal "/dev/null"))
(deny file-read* file-write* (subpath "<T>/closed"))
(allow file-read* file-write* (subpath "<T>/closed/ws"))
(deny file-write* (subpath "<T>/ws/placeholder"))
(deny file-read* file-write* (subpath "<T>/prot"))
(deny network-outbound (subpath "<T>/prot"))
"""


# ── §1 and the flip: the commands profile is the default-deny base ────────────

@pytest.fixture
def home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    (home / "ws").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


def _base_for(home, network, **kw):
    roots = command_sandbox.writable_roots(home / "ws")
    return sandbox_profile.default_deny_profile(
        [Path(r.path) for r in roots if r.tag != "device"], command_sandbox.default_protected(),
        closed=command_sandbox.app_data(), network=network, **kw)


def test_the_commands_profile_starts_with_the_base_text(home):
    assert command_sandbox.commands_profile(home / "ws", offline=True) == _base_for(home, NetworkMode.NONE)
    online = command_sandbox.commands_profile(home / "ws", proxy_port=41000, bound_ports=[], system_proxies=[])
    assert online == _base_for(home, NetworkMode.PROXY, proxy_port=41000)    # nothing to reopen: exactly the base


def test_online_is_the_proxy_and_offline_is_none(home):
    online = command_sandbox.commands_profile(home / "ws", proxy_port=41000, bound_ports=[], system_proxies=[])
    offline = command_sandbox.commands_profile(home / "ws", offline=True)
    assert '(allow network-outbound (remote tcp "localhost:41000"))' in online   # SBX-6 retires D2's any-declared
    assert '"*:*"' not in online and "mDNSResponder" not in online
    assert "(deny network*)" in offline and '"*:*"' not in offline
    for text in (online, offline):
        assert "(deny network-bind network-inbound)" in text                 # D1: listening stays denied


def test_the_writable_devices_are_the_bases_and_other_apps_data_is_closed(home):
    text = command_sandbox.commands_profile(home / "ws")
    assert '(subpath "/dev")' not in text
    closed = next(line for line in text.splitlines() if "Library/Mail" in line)
    assert closed.startswith("(deny file-read* file-write* file-map-executable ")
    for name in ("Library/Mail", "Library/Containers/com.apple.mail", "Library/Messages",
                 "Library/Containers/com.apple.MobileSMS", "Pictures/Photos Library.photoslibrary",
                 "Library/Photos", "Library/Containers/com.apple.Photos"):
        assert f'(subpath "{command_sandbox._real(home / name)}")' in closed, name


def test_a_work_folder_inside_a_closed_one_is_reopened_and_its_protected_paths_closed_again(home):
    desk = home / "Desktop"
    for folder in ("Desktop/ws/.ssh", "Desktop/proj", "Library/Application Support/Arslan"):
        (home / folder).mkdir(parents=True)
    copy = home / "Library/Application Support/Arslan/out.txt"
    copy.write_text("x")
    text = command_sandbox.commands_profile(desk / "ws", closed=[desk], readable=[desk / "proj"], copies=[copy])
    base = _base_for(home, NetworkMode.ANY_DECLARED)
    assert not text.startswith(base)                        # the closed Desktop is part of the base's text
    shown = text.replace(os.path.realpath(home), "<H>").splitlines()
    tail = shown[len(shown) - 4:]
    assert tail[0] == '(allow file-read* file-write* file-map-executable (subpath "<H>/Desktop/ws"))'
    assert tail[1] == '(allow file-read* file-map-executable (subpath "<H>/Desktop/proj"))'
    assert tail[2].startswith("(deny file-read* file-write* file-map-executable ") and '"<H>/.ssh"' in tail[2]
    assert tail[3] == '(allow file-read* (literal "<H>/Library/Application Support/Arslan/out.txt"))'
    assert shown[len(shown) - 5].startswith("(deny network-outbound ")   # the base's protected sockets, before


def test_the_sbx_harness_registers_the_product_preset():
    from tests.server.sbx.harness import BUILT_BASES, Harness
    assert BUILT_BASES["commands"] is not Harness._measurement_profile
    assert BUILT_BASES["commands"].__name__ == "_commands_profile"


# ── what should run does run (macOS) ─────────────────────────────────────────

@pytest.mark.macos
@macos
async def test_the_work_folder_the_devices_and_a_pty_still_work(tmp_path):
    result = await terminal_exec.run(
        "echo hi > made.txt && echo x > /dev/null && head -c 4 /dev/zero | wc -c && "
        "python3 -c 'import os, pty; m, s = pty.openpty(); os.write(s, b\"ok\"); print(os.read(m, 2).decode())'",
        cwd=tmp_path, sandbox=True)
    assert result["sandbox"] == "workspace" and result["ok"], result
    assert (tmp_path / "made.txt").read_text() == "hi\n"
    assert result["stdout"].split() == ["4", "ok"]



@pytest.mark.macos
@macos
async def test_a_work_folder_inside_a_closed_folder_and_a_saved_copy_still_work(tmp_path):
    """0.1.59 and S2a-1 piece 5 on the base: the base closes `closed` and the protected paths last, and 3a's
    rules after it reopen the work folder and the copy, under real seatbelt."""
    desk = tmp_path / "Desktop"
    ws = desk / "ws"
    ws.mkdir(parents=True)
    copy = tmp_path / "saved-output.txt"
    copy.write_text("kept")
    result = await terminal_exec.run(f"echo hi > made.txt && cat made.txt '{copy}'", cwd=ws, sandbox=True,
                                     closed=[desk, tmp_path], copies=[copy])
    assert result["sandbox"] == "workspace" and result["ok"], result
    assert result["stdout"].split() == ["hi", "kept"]

def test_only_sbx2s_harness_calls_the_baseline_helpers():
    """`default_writable` and `temp_roots` stay only for the harness's historical baseline (DELETE-BY in
    command_sandbox.py); no product path writes a profile from them."""
    import re
    root = Path(__file__).resolve().parents[3]
    callers = sorted(str(p.relative_to(root)) for folder in ("server", "arslan", "scripts", "tests")
                     for p in (root / folder).rglob("*.py")
                     if re.search(r"\b(default_writable|temp_roots)\(", p.read_text(encoding="utf-8")))
    assert callers == ["server/services/command_sandbox.py", "tests/server/sbx/harness.py"]

"""SBX-3 (v0.1.64), the commands' build half (3a), first part: what does not wait for SBX-2's base.

- `available()` starts the real commands profile, not `(allow default)`. A profile this macOS cannot start
  then reads as "unavailable" (today's card path) instead of failing every command.
- The writable roots come tagged (§1b): `in_scope` (the work folder), `shared_cache` (temp and the caches),
  `device` (the narrowed /dev entries). Temp is the run's own folder (test_sbx3_run_temp.py), in scope.
  `in_scope()` judges a path where it resolves.
- HR's write denies (§e) come after every grant and reopen (HR-1's `RUN_LATER_TEXT` below), so the last rule wins.
  The pre-SBX-3 text and its `deny_write_after_roots` parameter are gone (v0.1.64); the checks they carried that the
  live profile needs are below, against `commands_profile`.
- /dev is narrowed (§1) to the null and zero devices, the terminal, the descriptors and ptys.
- Mail, Messages and Photos data are closed (§1, the user's Q3), like Desktop/Documents/Downloads while that
  setting is off. Safari's data is already a protected path.
- The flip: commands run on SBX-2's default-deny base (`sandbox_profile.default_deny_profile`), with the user's
  D1 (listening stays denied) and D2 (online is the proxy since SBX-6, offline is none). What the base
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
from tests.server.sbx.profile_files import read_profile

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
    started = []                    # #813 review 11: the profile file's text while sandbox-exec runs

    def run(argv, **kw):
        calls.append(argv)
        started.append(Path(argv[2]).read_text())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(command_sandbox.subprocess, "run", run)
    command_sandbox._reset_for_tests()
    try:
        assert command_sandbox.available() is True
    finally:
        command_sandbox._reset_for_tests()
    assert len(calls) == 1 and calls[0][:2] == [str(exe), "-f"] and calls[0][3:] == ["/usr/bin/true"]
    assert started == [texts[0]] and not os.path.lexists(calls[0][2])     # read as written, gone after
    assert texts[0].startswith("(version 1)\n(deny default)\n")     # the commands profile, on the base


def test_a_command_starts_under_the_same_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    prefix = command_sandbox.wrapper(tmp_path)
    assert prefix[:2] == [command_sandbox._SANDBOX_EXEC, "-f"] and len(prefix) == 3
    assert read_profile(prefix) == command_sandbox.commands_profile(tmp_path)
    command_sandbox.remove_profile(command_sandbox.profile_path(prefix))


# ── §1b: tagged roots and the classifier's scope ─────────────────────────────

def test_the_writable_roots_are_tagged(tmp_path):
    roots = command_sandbox.writable_roots(tmp_path)
    assert [r for r in roots if r.tag == "in_scope"] == [command_sandbox.Root(str(tmp_path.resolve()), "in_scope")]
    tags = {r.path: r.tag for r in roots}
    home = Path.home()
    from server.services import run_temp
    # SBX-5 §1c: the one cache a command writes is Arslan's own; the user's are read-only.
    assert {path for path, tag in tags.items() if tag == "shared_cache"} == {
        str(command_sandbox._real(run_temp.cache("commands")))}
    assert not {str(command_sandbox._real(home / n)) for n in ("Library/Caches", ".cache", ".npm")} & set(tags)
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
        [Path(r.path) for r in roots if r.tag != "device"],
        [*command_sandbox.default_protected(), *command_sandbox.cap6b_folders()],
        closed=command_sandbox.app_data(), network=network, **kw)


def _shared_caches_read_only() -> str:
    """SBX-5 §1c: the rule 3a's preset always adds after the base, then HR-1's run-later denies."""
    from tests.server.test_hr1_run_later import RUN_LATER_TEXT
    return ("(deny file-write* " + " ".join(f'(subpath "{p}")' for p in command_sandbox.shared_caches()) + ")\n"
            + RUN_LATER_TEXT)


def test_the_commands_profile_starts_with_the_base_text(home):
    assert command_sandbox.commands_profile(home / "ws", offline=True) == (
        _base_for(home, NetworkMode.NONE) + _shared_caches_read_only())
    online = command_sandbox.commands_profile(home / "ws", proxy_port=41000, bound_ports=[], system_proxies=[])
    assert online == _base_for(home, NetworkMode.PROXY, proxy_port=41000) + _shared_caches_read_only()


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
    base = _base_for(home, NetworkMode.NONE)
    assert not text.startswith(base)                        # the closed Desktop is part of the base's text
    from tests.server.test_hr1_run_later import RUN_LATER_TEXT
    later = RUN_LATER_TEXT.splitlines()
    shown = text.replace(os.path.realpath(home), "<H>").splitlines()
    tail = shown[len(shown) - 5 - len(later):]
    assert tail[0] == '(allow file-read* file-write* file-map-executable (subpath "<H>/Desktop/ws"))'
    assert tail[1] == '(allow file-read* file-map-executable (subpath "<H>/Desktop/proj"))'
    assert tail[2].startswith("(deny file-read* file-write* file-map-executable ") and '"<H>/.ssh"' in tail[2]
    assert '"<H>/.agents/skills"' in tail[2]                               # SBX-5: CAP6b closes again too
    assert tail[3] == '(deny file-write* (subpath "<H>/Library/Caches") (subpath "<H>/.cache") (subpath "<H>/.npm"))'
    assert tail[4:4 + len(later)] == later                                 # HR-1: after the reopen, before the copies
    assert tail[-1] == '(allow file-read* (literal "<H>/Library/Application Support/Arslan/out.txt"))'
    assert shown[len(shown) - 6 - len(later)].startswith("(deny network-outbound ")   # the base's protected sockets


# ── checks moved from the pre-SBX-3 text (v0.1.64, when `command_sandbox.profile` went) ──

def test_a_closed_folder_with_nothing_inside_to_reopen_stays_closed(home):
    """The default case for the user's closed folders (Desktop, Documents, Downloads while the setting is off):
    no work or project folder inside them, so nothing is reopened after the base closes them, and a project
    folder elsewhere adds not a single rule."""
    desk, other = home / "Desktop", home / "other"
    for folder in (desk, other):
        folder.mkdir()
    shut = command_sandbox._resolved([desk, *command_sandbox.app_data()])
    roots = command_sandbox.writable_roots(home / "ws")
    expected = sandbox_profile.default_deny_profile(
        [Path(r.path) for r in roots if r.tag != "device"],
        [*command_sandbox.default_protected(), *command_sandbox.cap6b_folders()],
        closed=shut, network=NetworkMode.NONE) + _shared_caches_read_only()
    assert command_sandbox.commands_profile(home / "ws", offline=True, closed=[desk]) == expected
    assert command_sandbox.commands_profile(home / "ws", offline=True, closed=[desk], readable=[other]) == expected


def test_a_folder_name_cannot_add_rules_to_the_commands_profile(home):
    """A work folder's name is one SBPL string (`sbpl_string`): with every quoted string blanked, the profile for
    a folder named like a rule has exactly the shape of one for a plain name."""
    import re
    evil = home / 'a") (allow default) (allow file-write* (subpath "/'
    plain = home / "plain"
    for folder in (evil, plain):
        folder.mkdir()
    texts = [command_sandbox.commands_profile(folder, offline=True) for folder in (evil, plain)]
    assert sandbox_profile.sbpl_string(str(command_sandbox._real(evil))) in texts[0]
    shapes = [re.sub(r'"(?:\\.|[^"\\])*"', '""', text) for text in texts]
    assert "(allow default)" not in shapes[0]
    assert shapes[0] == shapes[1]


def test_the_commands_profile_resolves_links_and_closes_a_protected_file_as_a_literal(home, monkeypatch):
    """Seatbelt matches real paths: a work folder reached through a link is granted where it resolves, and so is a
    protected path; a protected file is closed exactly (`literal`), a folder with everything under it (`subpath`)."""
    key, data = home / "updater.key", home / "data"
    key.write_text("k")
    data.mkdir()
    for name, target in (("ws-link", home / "ws"), ("key-link", key), ("data-link", data)):
        (home / name).symlink_to(target)
    monkeypatch.setattr(command_sandbox, "default_protected", lambda: [home / "key-link", home / "data-link"])
    text = command_sandbox.commands_profile(home / "ws-link", offline=True)
    grant = next(line for line in text.splitlines() if line.startswith("(allow file-write* "))
    assert f'(subpath "{command_sandbox._real(home / "ws")}")' in grant
    closing = [line for line in text.splitlines() if line.startswith("(deny file-read* file-write* ")][-1]
    assert f'(literal "{command_sandbox._real(key)}")' in closing
    assert f'(subpath "{command_sandbox._real(data)}")' in closing
    for name in ("ws-link", "key-link", "data-link"):
        assert f'"{home / name}"' not in text, name


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

def test_the_pre_sbx3_profile_and_its_harness_baseline_are_gone(tmp_path):
    """v0.1.64 (SBX-2 harness retention, DELETE-BY reached): the allow-default commands text, the shared temp roots
    it granted and SBX-2's `legacy-commands` base built from them are gone, so nothing can start a command, or
    measure one, on the old policy again."""
    from tests.server.sbx.harness import BUILT_BASES, MEASUREMENT_BASES, Harness
    for name in ("profile", "default_writable", "temp_roots", "_darwin_user_dir", "_CS_DARWIN_USER_TEMP_DIR"):
        assert not hasattr(command_sandbox, name), name
    assert "legacy-commands" not in MEASUREMENT_BASES and "legacy-commands" not in BUILT_BASES
    with pytest.raises(NotImplementedError):
        Harness(tmp_path, "legacy-commands")._measurement_profile()

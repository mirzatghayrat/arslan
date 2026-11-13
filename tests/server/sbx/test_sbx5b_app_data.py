"""SBX-5b (the user's "C lite", 2026-11-11): other apps' private data, one named list (`command_sandbox._APP_DATA`)
closed to commands for reads and writes; `commands_profile(open_once=...)` reopens one listed folder, read-only, for
one command the user allowed on its once-only card.

The macOS cases run the profile under real seatbelt with a probe that prints, per check, "ok" or the errno's name.
A scratch HOME holds the folders, so TCC or a missing folder can't pass for a denial.
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

#: Written out, not derived from `_APP_DATA`: the folders the approved list names (the card's table, checked against
#: where macOS and each app keep their data). Removing one from the product list fails this file.
LISTED = {
    "Mail": ("Library/Mail", "Library/Containers/com.apple.mail"),
    "Messages": ("Library/Messages", "Library/Containers/com.apple.MobileSMS"),
    "Photos": ("Pictures/Photos Library.photoslibrary", "Library/Photos", "Library/Containers/com.apple.Photos"),
    "Chromium": ("Library/Application Support/Chromium",),
    "Vivaldi": ("Library/Application Support/Vivaldi",),
    "Opera": ("Library/Application Support/com.operasoftware.Opera",
              "Library/Application Support/com.operasoftware.OperaGX"),
    "1Password": ("Library/Group Containers/2BUA8C4S2C.com.1password", "Library/Group Containers/2BUA8C4S2C.com.agilebits",
                  "Library/Containers/com.1password.1password", "Library/Containers/com.agilebits.onepassword7"),
    "Bitwarden": ("Library/Application Support/Bitwarden", "Library/Containers/com.bitwarden.desktop"),
    "Slack": ("Library/Application Support/Slack", "Library/Containers/com.tinyspeck.slackmacgap"),
    "Discord": ("Library/Application Support/discord",),
    "WhatsApp": ("Library/Containers/net.whatsapp.WhatsApp", "Library/Group Containers/group.net.whatsapp.WhatsApp.shared",
                 "Library/Application Support/WhatsApp"),
    "Telegram": ("Library/Application Support/Telegram Desktop", "Library/Group Containers/6N38VWS5BX.ru.keepcoder.Telegram",
                 "Library/Containers/ru.keepcoder.Telegram"),
    "Signal": ("Library/Application Support/Signal",),
    "WeChat": ("Library/Containers/com.tencent.xinWeChat",),
    "Notes": ("Library/Group Containers/group.com.apple.notes", "Library/Containers/com.apple.Notes"),
    "Reminders": ("Library/Group Containers/group.com.apple.reminders",),
    "Calendar": ("Library/Calendars", "Library/Group Containers/group.com.apple.calendar"),
    "Contacts": ("Library/Application Support/AddressBook",),
}
ENTRIES = [(app, rel) for app, rels in LISTED.items() for rel in rels]


@pytest.fixture
def home(monkeypatch, tmp_path):
    """A scratch HOME holding every listed folder with a sentinel, one unlisted Application Support folder, and a
    work folder; a scratch temp root."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    temp = tmp_path / "t"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    for _, rel in ENTRIES:
        (home / rel).mkdir(parents=True, exist_ok=True)
        (home / rel / "sentinel").write_text("original")
    (home / "Library/Application Support/Foo").mkdir(parents=True)
    (home / "Library/Application Support/Foo/sentinel").write_text("original")
    (home / "work").mkdir()
    return home.resolve()


def _probe(profile: str, checks) -> dict:
    path = command_sandbox.write_profile(profile)
    try:
        result = subprocess.run([command_sandbox._SANDBOX_EXEC, "-f", str(path), sys.executable, "-I", "-c", PROBE,
                                 json.dumps([(n, a, str(p)) for n, a, p in checks])],
                                capture_output=True, text=True, timeout=60)
    finally:
        command_sandbox.remove_profile(path)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


# ── portable: the list, and what `open_once` accepts ────────────────────────────────────

def test_the_list_is_the_approved_one_with_its_apps(home):
    got = {(app, str(p.relative_to(home))) for app, p in command_sandbox.app_data_folders()}
    assert got == set(ENTRIES)
    assert command_sandbox.app_data() == [p for _, p in command_sandbox.app_data_folders()]
    secrets = set(command_sandbox.default_protected())
    assert not secrets & set(command_sandbox.app_data())            # nothing listed twice (`_SECRETS` has Safari)


def test_a_path_is_placed_in_its_apps_listed_folder(home):
    messages = home / "Library/Messages"
    assert command_sandbox.app_data_entry(messages / "chat.db") == ("Messages", messages)
    assert command_sandbox.app_data_entry(messages) == ("Messages", messages)
    assert command_sandbox.app_data_entry(home / "Library/Application Support/Foo/x") is None
    assert command_sandbox.app_data_entry(home / "Library") is None                  # a parent is not an app's folder
    assert command_sandbox.app_data_named("sqlite3 ~/Library/Messages/chat.db 'select 1'") == ("Messages", messages)
    assert command_sandbox.app_data_named(f"cat {home}/Library/Calendars/x") == ("Calendar", home / "Library/Calendars")
    assert command_sandbox.app_data_named("ls ~/Library/Application Support/Foo") is None


def test_open_once_is_refused_unless_a_real_closed_folder(home, tmp_path):
    work = home / "work"
    messages = home / "Library/Messages"
    (tmp_path / "alias").symlink_to(messages, target_is_directory=True)
    unlisted = home / "Library/Application Support/Foo"
    for folder in (tmp_path / "alias", Path("Library/Messages"), messages / ".." / "Messages", messages / "missing",
                   messages / "sentinel", unlisted, home / "Library", home):
        with pytest.raises(ValueError, match="open_once"):
            command_sandbox.commands_profile(work, offline=True, open_once=folder)
    (messages / "Attachments").mkdir()
    command_sandbox.commands_profile(work, offline=True, open_once=messages / "Attachments")    # inside one: fine
    shut = home / "Documents"
    shut.mkdir()
    command_sandbox.commands_profile(work, offline=True, closed=[shut], open_once=shut)        # a user-closed folder


def test_open_once_holding_or_inside_a_protected_path_is_refused(home, monkeypatch):
    from server import config
    work = home / "work"
    messages = home / "Library/Messages"
    monkeypatch.setattr(config, "data_dir", lambda: messages / "arslan-data")      # Arslan's data, protected
    (messages / "arslan-data").mkdir()
    with pytest.raises(ValueError, match="open_once.*protected"):
        command_sandbox.commands_profile(work, offline=True, open_once=messages)
    monkeypatch.setattr(config, "data_dir", lambda: home / "Library/Calendars")     # now the folder is inside it
    with pytest.raises(ValueError, match="open_once.*protected"):
        command_sandbox.commands_profile(work, offline=True, open_once=home / "Library/Calendars")


def test_open_once_holding_another_closed_folder_is_refused(home):
    work = home / "work"
    shut = home / "Library/Containers"                  # holds Mail's, Messages' and other apps' containers
    with pytest.raises(ValueError, match="open_once.*another closed"):
        command_sandbox.commands_profile(work, offline=True, closed=[shut], open_once=shut)


def test_open_once_already_inside_the_writable_work_folder_is_refused(home):
    """Only what is actually closed is reopened: with home as the work folder, a listed folder is inside it."""
    with pytest.raises(ValueError, match="open_once.*writable"):
        command_sandbox.commands_profile(home, offline=True, open_once=home / "Library/Messages")


def test_one_read_only_rule_after_the_app_data_deny_and_before_the_held_block(home):
    work = home / "work"
    messages = home / "Library/Messages"
    lines = command_sandbox.commands_profile(work, offline=True, open_once=messages).splitlines()
    rule = f'(allow file-read* (subpath "{messages}"))'
    assert lines.count(rule) == 1
    assert not [line for line in lines if str(messages) in line and "allow" in line and line != rule]
    assert not [line for line in lines if "allow" in line and "file-write" in line and str(messages) in line]
    closing = max(i for i, line in enumerate(lines) if line.startswith("(deny file-read*") and str(messages) in line)
    held = min(i for i, line in enumerate(lines) if line.startswith("(deny file-write-create"))
    assert closing < lines.index(rule) < held
    plain = command_sandbox.commands_profile(work, offline=True).splitlines()
    assert [line for line in lines if line != rule] == plain                  # the only difference


def test_the_wrapper_passes_it_through(home, monkeypatch):
    seen = {}

    def built(*args, **kw):
        seen.update(kw)
        return "(version 1)\n(allow default)\n"
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    monkeypatch.setattr(command_sandbox, "commands_profile", built)
    prefix = command_sandbox.wrapper(home / "work", offline=True, open_once=home / "Library/Messages")
    try:
        assert seen["open_once"] == home / "Library/Messages"
    finally:
        command_sandbox.remove_profile(command_sandbox.profile_path(prefix))     # releases its pins too


# ── macOS: under real seatbelt ───────────────────────────────────────────────────────

@pytest.mark.macos
@macos
def test_each_listed_folder_is_closed_to_a_command_and_an_unlisted_one_is_not(home):
    profile = command_sandbox.commands_profile(home / "work", offline=True)
    checks = []
    for app, rel in ENTRIES:
        checks += [(f"{rel}:read", "read", home / rel / "sentinel"), (f"{rel}:list", "list", home / rel),
                   (f"{rel}:write", "write", home / rel / "sentinel"), (f"{rel}:new", "write", home / rel / "new")]
    foo = home / "Library/Application Support/Foo"
    checks += [("foo:read", "read", foo / "sentinel"), ("foo:list", "list", foo)]
    out = _probe(profile, checks)
    for name, *_ in checks[:-2]:
        assert out[name] in REFUSED, (name, out[name])
    assert out["foo:read"] == out["foo:list"] == "ok"                       # C lite: nothing else is closed
    assert all((home / rel / "sentinel").read_text() == "original" and not (home / rel / "new").exists()
               for _, rel in ENTRIES)


@pytest.mark.macos
@macos
@pytest.mark.parametrize("closed", [False, True], ids=["open-home", "work-in-a-closed-folder"])
def test_open_once_reads_that_folder_only_and_never_writes_it(home, tmp_path, closed):
    """With the work folder inside a closed folder, the profile reopens it and closes the protected paths again; the
    open-once rule comes after that too."""
    shut = home / "Documents"
    work = (shut if closed else home) / "w"
    work.mkdir(parents=True)
    messages, slack = home / "Library/Messages", home / "Library/Application Support/Slack"
    (messages / "Attachments").mkdir()
    (messages / "Attachments" / "a.txt").write_text("original")
    profile = command_sandbox.commands_profile(work, offline=True, closed=[shut] if closed else [], readable=[work],
                                               open_once=messages)
    out = _probe(profile, [("read", "read", messages / "sentinel"), ("list", "list", messages),
                           ("deep", "read", messages / "Attachments" / "a.txt"),
                           ("write", "write", messages / "sentinel"), ("new", "write", messages / "new"),
                           ("deep-write", "write", messages / "Attachments" / "a.txt"),
                           ("sibling-app", "read", slack / "sentinel"),
                           ("same-app-other-folder", "read", home / "Library/Containers/com.apple.MobileSMS/sentinel")])
    assert out["read"] == out["list"] == out["deep"] == "ok", out
    for name in ("write", "new", "deep-write", "sibling-app", "same-app-other-folder"):
        assert out[name] in REFUSED, (name, out[name])
    assert (messages / "sentinel").read_text() == "original" and not (messages / "new").exists()


@pytest.mark.macos
@macos
async def test_a_command_run_with_the_cards_folder_reads_it_and_one_without_is_told_how_to_ask(home):
    """Through `terminal_exec.run`, as the run_command executor calls it."""
    from server.services import terminal_exec
    messages = home / "Library/Messages"
    command = f"cat '{messages}/sentinel'"
    allowed = await terminal_exec.run(command, cwd=home / "work", offline=True, sandbox=True, open_once=messages)
    assert allowed["ok"] is True and allowed["stdout"].strip() == "original", allowed
    plain = await terminal_exec.run(command, cwd=home / "work", offline=True, sandbox=True)
    assert plain["ok"] is False and plain.get("sandbox_denied") is True
    assert f'app_data_once: "{messages}"' in plain["note"]
    refused = await terminal_exec.run(command, cwd=home, offline=True, sandbox=True, open_once=messages)
    assert refused["code"] == "app_data_refused" and refused["exit_code"] is None     # writable already: not started


@pytest.mark.macos
@macos
def test_the_next_command_without_the_card_is_closed_again(home):
    messages = home / "Library/Messages"
    once = _probe(command_sandbox.commands_profile(home / "work", offline=True, open_once=messages),
                  [("read", "read", messages / "sentinel")])
    after = _probe(command_sandbox.commands_profile(home / "work", offline=True),
                   [("read", "read", messages / "sentinel")])
    assert once["read"] == "ok" and after["read"] in REFUSED

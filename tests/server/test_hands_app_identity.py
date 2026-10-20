"""0.1.61 §A11/§H.2: an app's name is turned into its bundle id from the installed app's own
Info.plist (never by launching it), the never-list matches both, and an AppleScript that names a
never-list app is refused before any card."""
import plistlib

import pytest

from server.registry import hands_tools
from server.services import hands_service
from tests.server import test_hands_0153 as base

isolated, hands, asks, in_turn, in_job = base.isolated, base.hands, base.asks, base.in_turn, base.in_job



@pytest.fixture
def apps_folder(tmp_path, monkeypatch):
    """An Applications folder with two apps: Notes2, and Vault (a password manager by its bundle id)."""
    for name, bundle in (("Notes2", "com.example.notes2"), ("Vault", "com.1password.vault")):
        contents = tmp_path / f"{name}.app" / "Contents"
        contents.mkdir(parents=True)
        with (contents / "Info.plist").open("wb") as f:
            plistlib.dump({"CFBundleIdentifier": bundle, "CFBundleName": name}, f)
    monkeypatch.setattr(hands_service, "_APP_DIRS", (str(tmp_path),))
    hands_service.app_identity.cache_clear()
    yield tmp_path
    hands_service.app_identity.cache_clear()


def test_a_name_becomes_the_installed_apps_bundle_id(apps_folder):
    assert hands_service.app_identity("Notes2") == {"name": "Notes2", "bundle_id": "com.example.notes2"}
    assert hands_service.app_identity("Notes2.app")["bundle_id"] == "com.example.notes2"
    assert hands_service.app_identity("com.example.other") == {"name": "", "bundle_id": "com.example.other"}
    assert hands_service.app_identity("Nonesuch") is None
    assert hands_service.app_identity("../Notes2") is None


def test_the_never_list_matches_an_apps_name_and_its_bundle_id(apps_folder):
    assert hands_service.never_touched("Vault"), "a password manager by its bundle id, whatever its name"
    assert not hands_service.never_touched("Notes2")
    hands_service.update_settings(never=["com.example.notes2"])
    assert hands_service.never_touched("Notes2"), "the user's own entry, by bundle id"
    hands_service.update_settings(never=["Notes2"])
    assert hands_service.never_touched("com.example.notes2") is False, "a bundle id alone has no name to match"
    assert hands_service.never_touched("Notes2")


def test_the_apps_a_script_names():
    script = ('tell application "Notes" to activate\nusing terms from application id "com.apple.Mail"\n'
              'tell app "Notes"\n  set x to "application"\nend tell')
    assert hands_service.script_apps(script) == ["Notes", "com.apple.Mail"]


async def test_a_script_naming_a_never_list_app_is_refused_before_any_card(hands, asks, in_job, apps_folder,
                                                                          monkeypatch):
    seen, _ = asks
    ran = []

    async def run(argv, *a, **kw):                  # nothing is run (no osascript on Linux CI either)
        ran.append(argv)
        return {"ok": True, "external": False, "text": ""}
    monkeypatch.setattr(hands_tools, "_run", run)
    for script in ('tell application "Keychain Access" to activate', 'tell application "Vault" to quit',
                   'tell application id "com.apple.systempreferences" to activate'):
        result = await hands_tools.MacAppleScriptExecutor().execute({"script": script})
        assert result["code"] == "app_denied", script
    assert seen == []
    ok = await hands_tools.MacAppleScriptExecutor().execute({"script": 'tell application "Notes2" to activate'})
    assert [f["kind"] for f in seen] == ["mac_script"], ok
    assert len(ran) == 1, "only the allowed script ran"


# ── v0.1.63 H4 (②Main): AppleScript takes "X.app" and a full path for the same app ─────────────────

def _bundle(folder, name, bundle_id):
    contents = folder / f"{name}.app" / "Contents"
    contents.mkdir(parents=True)
    with (contents / "Info.plist").open("wb") as f:
        plistlib.dump({"CFBundleIdentifier": bundle_id, "CFBundleName": name}, f)
    return folder / f"{name}.app"


@pytest.mark.parametrize("named", ["Vault.app", "VAULT.APP", "{folder}/Vault.app", "{folder}/Vault.app/"])
def test_a_never_list_app_by_its_app_suffix_or_path_is_refused(apps_folder, named):
    assert hands_service.never_touched(named.format(folder=apps_folder)), named


@pytest.mark.parametrize("named", [
    "/Applications/1Password.app", "/APPLICATIONS/1PASSWORD.APP", "~/Applications/1Password.app",
    "Macintosh HD:Applications:1Password.app:", "/System/Applications/Utilities/Keychain Access.app",
    "/System/Applications/System Settings.app",
])
def test_a_never_list_app_by_path_is_refused_whether_or_not_it_is_installed(apps_folder, named):
    # _APP_DIRS points at a folder without these apps: where one is not installed the name still counts.
    assert hands_service.never_touched(named), named


def test_a_renamed_never_list_app_is_known_by_the_bundle_id_inside_it(apps_folder, tmp_path_factory):
    pm = _bundle(tmp_path_factory.mktemp("elsewhere"), "Pm", "com.1password.1password")
    assert hands_service.never_touched(str(pm)), "its own Info.plist says 1Password, whatever its file name"


def test_a_benign_app_by_path_stays_allowed(apps_folder):
    assert not hands_service.never_touched(str(apps_folder / "Notes2.app"))
    assert not hands_service.never_touched("/System/Applications/Notes.app")
    assert not hands_service.never_touched("/no/such/Bundle.app")


def test_the_users_own_never_entry_counts_however_it_was_written(apps_folder):
    hands_service.update_settings(never=["/Applications/Notes2.app"])
    assert hands_service.never_touched("Notes2")
    hands_service.update_settings(never=["Notes2.app"])
    assert hands_service.never_touched("Notes2") and hands_service.never_touched(str(apps_folder / "Notes2.app"))


def test_every_spelling_of_an_app_is_kept_so_each_is_checked():
    """Folded by key, a path that is really a renamed 1Password hid behind an earlier "Notes" (②Main)."""
    script = ('tell application "Notes" to activate\ntell application "Notes.app" to activate\n'
              'tell application "/System/Applications/Notes.app" to quit\ntell application "Notes" to quit')
    assert hands_service.script_apps(script) == ["Notes", "Notes.app", "/System/Applications/Notes.app"]


async def test_a_renamed_never_list_bundle_after_a_plain_name_of_the_same_key_is_refused(
        hands, asks, in_job, apps_folder, tmp_path_factory, monkeypatch):
    """②Main's probe on #271: a bundle called Notes.app whose Info.plist says 1Password, named by its
    path after a plain "Notes" line. Both share the key "notes"; the path must still be checked."""
    seen, _ = asks
    ran = []

    async def run(argv, *a, **kw):
        ran.append(argv)
        return {"ok": True, "external": False, "text": ""}
    monkeypatch.setattr(hands_tools, "_run", run)
    fake = _bundle(tmp_path_factory.mktemp("lookalike"), "Notes", "com.1password.1password")
    script = f'tell application "Notes" to count notes\ntell application "{fake}" to activate'
    assert str(fake) in hands_service.script_apps(script)
    result = await hands_tools.MacAppleScriptExecutor().execute({"script": script})
    assert result.get("code") == "app_denied", result
    assert seen == [] and ran == []


def test_a_renamed_copy_of_a_high_reach_app_is_still_high_reach(apps_folder, tmp_path_factory):
    term = _bundle(tmp_path_factory.mktemp("copies"), "Tm", "com.apple.Terminal")
    assert hands_service.script_kind(f'tell application "{term}" to activate')[0] == "app_risky"
    _bundle(apps_folder, "Tm2", "com.apple.Terminal")          # a usual folder, under a new name
    hands_service.app_identity.cache_clear()
    assert hands_service.script_kind('tell application "Tm2" to activate')[0] == "app_risky"


async def test_a_script_naming_a_never_list_app_by_path_is_refused_before_any_card(hands, asks, in_job,
                                                                                  apps_folder, monkeypatch):
    seen, _ = asks
    ran = []

    async def run(argv, *a, **kw):
        ran.append(argv)
        return {"ok": True, "external": False, "text": ""}
    monkeypatch.setattr(hands_tools, "_run", run)
    for script in (f'tell application "{apps_folder}/Vault.app" to quit',
                   'tell application "/Applications/1Password.app" to activate',
                   'tell application "Keychain Access.app" to activate',
                   'tell application "Macintosh HD:Applications:1Password.app:" to activate'):
        result = await hands_tools.MacAppleScriptExecutor().execute({"script": script})
        assert result.get("code") == "app_denied", script
    assert seen == [] and ran == [], "refused before any card, and nothing ran"


async def test_a_never_list_app_by_a_path_padded_past_120_characters_is_refused(hands, asks, in_job,
                                                                               apps_folder, monkeypatch):
    """The capture used to stop at 120 characters, so a longer name was no app at all to the check."""
    seen, _ = asks
    ran = []

    async def run(argv, *a, **kw):
        ran.append(argv)
        return {"ok": True, "external": False, "text": ""}
    monkeypatch.setattr(hands_tools, "_run", run)
    padded = "/Applications/" + "./" * 80 + "1Password.app"
    vault = str(apps_folder) + "/" + "./" * 80 + "Vault.app"
    assert len(padded) > 120 and len(vault) > 120
    for target in (padded, vault):
        assert hands_service.script_apps(f'tell application "{target}" to quit') == [target]
        result = await hands_tools.MacAppleScriptExecutor().execute({"script": f'tell application "{target}" to quit'})
        assert result.get("code") == "app_denied", target
    assert seen == [] and ran == []

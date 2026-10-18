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

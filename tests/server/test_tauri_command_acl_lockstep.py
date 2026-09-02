"""Every Tauri command the shell registers must be reachable from the UI.

The window is a REMOTE origin as far as Tauri's ACL is concerned (the SPA is
served by the sidecar over http://127.0.0.1), so an `invoke()` from it is
allowed only if a capability grants `allow-<command>` — and that permission
exists only if build.rs lists the command in the app manifest. Three places,
no guard, and the fourth time this project found such a pair had drifted was
here: v0.1.36 shipped hold-to-talk with `voice_start`/`voice_stop` registered
in `generate_handler!` and in neither of the other two. The committed ACL
manifest (`gen/schemas/acl-manifests.json`) has no `voice` in it; the button
would have shown a raw "not allowed" error on every packaged install.

The list of commands is DERIVED from `generate_handler!` — the one place that
cannot lie, because a command not in it does not exist — and the other two
are asserted against it.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TAURI = ROOT / "desktop" / "src-tauri"


def registered_commands() -> list[str]:
    src = (TAURI / "src" / "lib.rs").read_text()
    m = re.search(r"generate_handler!\[(.*?)\]", src, re.S)
    assert m, "generate_handler! not found in lib.rs"
    names = []
    for item in m.group(1).split(","):
        item = item.strip()
        if item:
            names.append(item.split("::")[-1])   # `listen::voice_start` -> voice_start
    return names


def manifest_commands() -> list[str]:
    src = (TAURI / "build.rs").read_text()
    m = re.search(r"\.commands\(&\[(.*?)\]\)", src, re.S)
    assert m, "AppManifest::commands(&[...]) not found in build.rs"
    return re.findall(r'"([a-z_]+)"', m.group(1))


def granted_permissions() -> set[str]:
    perms: set[str] = set()
    for cap in (TAURI / "capabilities").glob("*.json"):
        perms.update(json.loads(cap.read_text())["permissions"])
    return perms


def test_generate_handler_is_the_source_and_has_the_voice_commands():
    cmds = registered_commands()
    assert "voice_start" in cmds and "voice_stop" in cmds, cmds


def test_every_registered_command_is_in_the_build_manifest():
    missing = [c for c in registered_commands() if c not in manifest_commands()]
    assert missing == [], (
        f"{missing} are registered in generate_handler! but not in build.rs's "
        "AppManifest::commands — tauri-build generates no permission for them, "
        "so no capability can ever grant them")


def test_every_registered_command_is_granted_to_the_remote_ui():
    perms = granted_permissions()
    missing = [c for c in registered_commands()
               if f"allow-{c.replace('_', '-')}" not in perms]
    assert missing == [], (
        f"{missing} are registered but no capability grants allow-<command> to the "
        "127.0.0.1 origin — invoke() from the UI is refused by the ACL")


def test_the_committed_acl_manifest_carries_every_command():
    """The generated artefact is tracked; it is what a build actually ships."""
    manifest = (TAURI / "gen" / "schemas" / "acl-manifests.json").read_text()
    missing = [c for c in registered_commands()
               if f"allow-{c.replace('_', '-')}" not in manifest]
    assert missing == [], f"{missing} absent from gen/schemas/acl-manifests.json — rebuild"

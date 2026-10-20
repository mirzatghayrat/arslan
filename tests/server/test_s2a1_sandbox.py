"""S2a-1 (docs/plans/0162/S2a-command-three-layers.md): the command sandbox gets tighter.

Measured on this Mac before any code (2026-10-20, read-only osascript, exit and error codes only):
any sandbox-exec wrapper blocks Apple Events to every app (-10004 for Reminders and Finder alike,
even under a bare `(allow default)`); with `(deny appleevent-send)` the error is -600. So a
sandboxed command never reaches another app, and Arslan says so honestly instead of sending the
user to the Automation settings (D4's hint, right outside the sandbox, wrong inside it).
"""
import sys
from pathlib import Path

import pytest

from server.services import command_sandbox, task_service, terminal_exec
from server.orchestrator.recovery_hints import hint_for

macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt (sandbox-exec) is macOS-only")
SANDBOX_REFUSAL = "32:43: execution error: Reminders got an error: Application isn’t running. (-600)"


# ── piece 3: what a command can never read, in two lists ──────────────────────────────

def test_protected_paths_are_arslans_own_plus_the_users_secrets():
    from server import config
    from server.services import hands_client
    home, real = Path.home(), command_sandbox._real
    ours, secrets = command_sandbox.arslan_protected(), command_sandbox.user_secrets()
    for path in (config.data_dir(), home / ".arslan", home / ".arslan-updater.key",
                 home / "arslan-signing-backup", hands_client.folder()):
        assert real(path) in ours, path
    for name in (".ssh", "Library/Keychains", ".aws", ".config/gcloud", ".kube", ".docker/config.json", ".netrc",
                 ".npmrc", ".pypirc", ".config/gh", ".git-credentials", ".gnupg", ".azure",
                 "Library/Application Support/Google/Chrome", "Library/Application Support/Firefox",
                 "Library/Application Support/BraveSoftware", "Library/Application Support/Microsoft Edge",
                 "Library/Application Support/Arc", "Library/Safari", "Library/Cookies"):
        assert real(home / name) in secrets, name
    assert not set(ours) & set(secrets)
    assert command_sandbox.default_protected() == [*ours, *secrets]       # existing callers unchanged


# ── piece 1: no Apple Events from the sandbox, and an honest word about it ────────────

def test_the_workspace_profile_denies_apple_events(tmp_path):
    lines = command_sandbox.profile([tmp_path], []).splitlines()
    assert lines[:3] == ["(version 1)", "(allow default)", "(deny appleevent-send)"]


def test_a_sandboxed_apple_event_refusal_gets_an_honest_hint():
    hint = hint_for("run_command", {"ok": False, "exit_code": 1, "sandbox": "workspace", "stderr": SANDBOX_REFUSAL})
    assert hint.startswith("Apple Events can't be sent from inside the command sandbox")
    assert "mac_applescript" in hint and "desktop_" in hint and "Automation" not in hint
    # Outside the sandbox a refusal is still macOS's Automation permission (D4's hint).
    outside = hint_for("run_command", {"ok": False, "exit_code": 1, "sandbox": "off", "stderr":
                                       "execution error: Not authorized to send Apple events to Reminders. (-1743)"})
    assert "Automation" in outside


def test_a_sandboxed_apple_event_refusal_is_a_known_failure_not_an_unknown_outcome():
    args = {"command": "osascript -e 'tell application \"Reminders\" to get name of every list'"}
    refused = {"exit_code": 1, "sandbox": "workspace", "stderr": SANDBOX_REFUSAL}
    assert task_service._apple_events_refused(args, refused)
    # -600 outside the sandbox can mean anything the app did: not judged.
    assert not task_service._apple_events_refused(args, {**refused, "sandbox": "off"})


@pytest.mark.macos
@macos
async def test_an_apple_event_from_the_sandbox_reaches_no_app(tmp_path):
    result = await terminal_exec.run("osascript -e 'tell application \"Finder\" to count windows'",
                                     cwd=tmp_path, sandbox=True)
    assert result["sandbox"] == "workspace" and not result["ok"]
    assert "(-600)" in result["stderr"] and not result.get("sandbox_denied")      # no outside card for this
    assert hint_for("run_command", result).startswith("Apple Events can't be sent")


# ── piece 5: a copy this conversation was given is readable by a command, file by file ──

@pytest.fixture
def outputs(tmp_path, monkeypatch):
    from server import config
    from server.services import tool_outputs
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path / "data")
    tool_outputs._given.clear()
    yield tool_outputs
    tool_outputs._given.clear()


def test_saved_copies_are_remembered_for_their_conversation_newest_last(outputs):
    token = outputs.conversation.set("c1")
    try:
        paths = [outputs.save(f"text {i}", label="command") for i in range(outputs.KEEP_PER_CONVERSATION + 3)]
    finally:
        outputs.conversation.reset(token)
    other = outputs.conversation.set("c2")
    try:
        theirs = outputs.save("other", label="command")
    finally:
        outputs.conversation.reset(other)
    mine = outputs.given("c1")
    assert mine == [p.resolve() for p in paths[3:]] and theirs.resolve() not in mine
    paths[-1].unlink()
    assert paths[-1].resolve() not in outputs.given("c1")         # gone from disk, gone from the set
    assert outputs.given(None) == [] and outputs.given("nobody") == []


def test_copies_are_opened_one_by_one_after_the_protected_paths(tmp_path):
    data = tmp_path / "data"
    copy = data / "tool_outputs" / 'a "quoted" name.txt'
    copy.parent.mkdir(parents=True)
    copy.write_text("x")
    lines = command_sandbox.profile([tmp_path / "ws"], [data], copies=[copy]).splitlines()
    deny = next(i for i, line in enumerate(lines) if line.startswith("(deny file-read* file-write* "))
    allow = [line for line in lines if line.startswith("(allow file-read* (literal")]
    assert allow == ['(allow file-read* (literal ' + __import__("json").dumps(str(copy.resolve())) + '))']
    assert lines.index(allow[0]) > deny and "subpath" not in allow[0] and "write" not in allow[0]


async def test_the_executor_passes_this_conversations_copies(outputs, monkeypatch, tmp_path):
    from server.registry import executors
    from server.services import settings_service
    seen = {}

    async def fake_run(command, **kwargs):
        seen.update(kwargs)
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""}

    async def workspace(db):
        return tmp_path

    async def yes(db):
        return True
    monkeypatch.setattr(terminal_exec, "run", fake_run)
    monkeypatch.setattr(settings_service, "workspace_dir", workspace)
    monkeypatch.setattr(settings_service, "terminal_sandbox_enabled", yes)
    monkeypatch.setattr(settings_service, "default_read_enabled", yes)
    token = outputs.conversation.set("c1")
    try:
        copy = outputs.save("long output", label="command")
        await executors.RunCommandExecutor().execute({"command": "cat x"})
    finally:
        outputs.conversation.reset(token)
    assert seen["copies"] == [copy.resolve()]


@pytest.mark.macos
@macos
async def test_a_command_reads_its_own_copy_and_nothing_else_there(outputs, tmp_path):
    token = outputs.conversation.set("c1")
    try:
        mine = outputs.save("MINE", label="command")
    finally:
        outputs.conversation.reset(token)
    other = outputs.conversation.set("c2")
    try:
        theirs = outputs.save("THEIRS", label="command")
    finally:
        outputs.conversation.reset(other)
    ws = tmp_path / "ws"
    ws.mkdir()
    copies = outputs.given("c1")
    read = await terminal_exec.run(f"cat '{mine}'", cwd=ws, sandbox=True, copies=copies)
    assert read["ok"] and read["stdout"].strip() == "MINE"
    listed = await terminal_exec.run(f"ls '{mine.parent}'", cwd=ws, sandbox=True, copies=copies)
    assert not listed["ok"]                                         # the folder itself stays closed
    blocked = await terminal_exec.run(f"cat '{theirs}'", cwd=ws, sandbox=True, copies=copies)
    assert not blocked["ok"] and not blocked.get("sandbox_denied")  # no outside card for a copy
    assert "read_file" in blocked["note"]

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
    assert task_service._apple_events_refused(args, {**refused, "sandbox": "outside"})   # the minimal profile
    # -600 with no wrapper at all can mean anything the app did: not judged.
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


# ── piece 4 (U11): outside the sandbox, a minimal profile; an approved AE/Shortcut runs bare, once ──

def test_the_outside_profile_closes_arslans_own_paths_but_not_the_users_secrets(tmp_path):
    profile = command_sandbox.minimal_profile()
    lines = profile.splitlines()
    assert lines[:3] == ["(version 1)", "(allow default)", "(deny appleevent-send)"]
    deny = next(line for line in lines if line.startswith("(deny file-read* file-write* "))
    for path in command_sandbox.arslan_protected():
        assert __import__("json").dumps(str(path)) in deny
    for path in command_sandbox.user_secrets():
        assert __import__("json").dumps(str(path)) not in profile
    assert "(deny network*)" not in profile and "(deny network*)" in command_sandbox.minimal_profile(offline=True)
    assert "(allow file-write" not in profile and "file-write* (subpath \"/\")" not in profile   # writes stay open
    copy = tmp_path / "copy.txt"
    copy.write_text("x")
    opened = command_sandbox.minimal_profile(copies=[copy]).splitlines()
    assert opened[-1] == f"(allow file-read* (literal {__import__('json').dumps(str(copy.resolve()))}))"


async def test_an_outside_run_gets_the_minimal_profile_and_an_exempt_one_none(tmp_path, monkeypatch):
    seen = []

    class Proc:
        returncode, pid = 0, 0
        stdout = stderr = None

    async def fake_exec(*argv, **kwargs):
        seen.append(argv)
        raise RuntimeError("stop here")                  # the prefix is all this test needs
    monkeypatch.setattr(command_sandbox, "available", lambda: True)
    monkeypatch.setattr(terminal_exec.asyncio, "create_subprocess_exec", fake_exec)
    for kwargs in ({}, {"unwrapped": True}, {"offline": True}):
        with pytest.raises(RuntimeError):
            await terminal_exec.run("echo hi", cwd=tmp_path, sandbox=False, **kwargs)
    outside, bare, offline = seen
    assert outside[0] == "/usr/bin/sandbox-exec" and "(deny appleevent-send)" in outside[2]
    assert bare[0] != "/usr/bin/sandbox-exec"
    assert offline[0] == "/usr/bin/sandbox-exec" and "(deny network*)" in offline[2]
    assert not hasattr(terminal_exec, "offline_wrapper")           # replaced by the minimal profile


@pytest.mark.parametrize("command, bare", [
    ("osascript -e 'tell application \"Reminders\" to get name of every list'", True),
    ("osascript <<'EOF'\ntell application \"Reminders\"\n  make new reminder with properties {name:\"x\"}\nend tell\nEOF", True),
    ("shortcuts run \"Morning\"", True),
    ("/usr/bin/shortcuts run Morning -i ~/in.txt", True),
    ("osascript -e 'do shell script \"ls\"'", False),                        # an unconfined shell
    ("osascript -e 'tell application \"Notes\" to «event sysoexec» \"ls\"'", False),
    ("osascript -e 'tell application \"Finder\" to move file \"a\" to trash'", False),
    ("osascript -e 'tell application \"Reminders\" to count lists'; curl https://x.test", False),
    ("osascript -e \"tell application \\\"$APP\\\" to quit\"", False),       # the shell expands first
    ("shortcuts run \"Morning\" | cat", False),
    ("shortcuts run \"$NAME\"", False),
    ("shortcuts list", False),
])
def test_only_one_plain_apple_events_or_shortcuts_call_runs_bare(command, bare):
    assert task_service.unwrapped_once(command) is bare


def test_a_shortcut_card_says_it_runs_as_the_user_outside_the_sandbox():
    from server.services import approvals
    req = approvals._command_request("shortcuts run \"Morning\"", ["shortcuts"], None)
    assert req.once_only and "runs as you, outside the sandbox" in req.title
    osa = approvals._command_request("osascript -e 'tell application \"Reminders\" to count lists'",
                                     ["apple-events"], None)
    assert "outside the sandbox" in osa.title
    shell = approvals._command_request("osascript -e 'do shell script \"ls\"'", ["apple-events"], None)
    assert "outside the sandbox" not in shell.title                # it will not run bare


# ── the tool loop: who runs bare, who is kept wrapped ──────────────────────────────────

class _Exec:
    """Stand-in run_command executor: records how the loop let it run."""
    key = "run_command"

    def __init__(self, result=None):
        self.runs: list[tuple[bool, bool]] = []
        self.result = result or {"ok": True, "exit_code": 0, "stdout": "done", "stderr": ""}

    async def execute(self, args):
        self.runs.append((terminal_exec.OUTSIDE_SANDBOX.get(), terminal_exec.UNWRAPPED.get()))
        return dict(self.result)


class _Cards:
    honours_session_grants = True

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    async def __call__(self, command, argv, **kw):
        self.calls.append(kw)
        return self.answers.pop(0) if self.answers else False


async def _dispatch(monkeypatch, command, executor, cards, **args):
    from server.orchestrator import tool_loop

    async def resolve():
        return [{"key": "run_command", "description": "run"}]

    async def yes():
        return True

    async def no():
        return False
    monkeypatch.setattr(tool_loop, "_sandbox_enabled", yes)
    monkeypatch.setattr(tool_loop, "_asks_for_everything", no)
    monkeypatch.setitem(tool_loop.EXECUTORS, "run_command", executor)
    return await tool_loop._dispatch_tool(
        "run_command", {"command": command, **args}, "{}", resolve_tools=resolve, emit=lambda e: None,
        tool_timeout_s=5, tool_trace=[], convo=[], confirm_command=cards, conversation_id="c1")


PLAIN_OSA = "osascript -e 'tell application \"Reminders\" to count lists'"
SHELL_OSA = "osascript -e 'do shell script \"ls ~\"'"


async def test_an_approved_plain_osascript_runs_bare_once(monkeypatch):
    ex, cards = _Exec(), _Cards(True)
    result = await _dispatch(monkeypatch, PLAIN_OSA, ex, cards)
    assert ex.runs == [(True, True)] and result["ran_outside_sandbox"] is True


async def test_an_approved_script_that_acts_elsewhere_is_kept_wrapped(monkeypatch):
    refused = {"ok": False, "exit_code": 1, "stdout": "", "sandbox": "workspace",
               "stderr": "0:20: execution error: Not authorized to send Apple events. (-600)"}
    ex, cards = _Exec(refused), _Cards(True)
    result = await _dispatch(monkeypatch, SHELL_OSA, ex, cards)
    assert ex.runs == [(False, False)] and result.get("kept_wrapped") is True
    assert hint_for("run_command", result).startswith("This AppleScript acts beyond its app")


async def test_a_declined_apple_events_card_runs_nothing(monkeypatch):
    ex, cards = _Exec(), _Cards(False)
    result = await _dispatch(monkeypatch, PLAIN_OSA, ex, cards)
    assert ex.runs == [] and not result["ok"]


async def test_an_approved_apple_events_card_never_becomes_a_standing_grant(execution_db, monkeypatch):
    from unittest.mock import AsyncMock

    from server.services import approvals, permission_store, run_registry, settings_service
    monkeypatch.setattr(settings_service, "shell_confirm_policy", AsyncMock(return_value="ask_risky"))
    asked = []

    def window(frame):
        if frame["type"] == "propose_run_command":
            asked.append(frame["options"])
            approvals.answer({"type": "confirm_run_command", "call_id": frame["call_id"], "scope": "conversation"})
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: window)
    job = approvals.JobConfirmations("job-c", job_id="job-1")
    assert await job.command(PLAIN_OSA, []) is True
    assert await job.command(PLAIN_OSA, []) is True                 # asked again: nothing was kept
    assert asked == [["once"], ["once"]]
    async with execution_db() as db:
        assert await permission_store.find_grant(db, "job-c", "", "command", "rules:apple-events") is None


@pytest.mark.macos
@macos
async def test_outside_the_sandbox_arslans_data_stays_closed_and_the_users_secrets_open(tmp_path, monkeypatch):
    from server import config
    data, home, ws = tmp_path / "data", tmp_path / "home", tmp_path / "ws"
    (home / ".ssh").mkdir(parents=True)
    data.mkdir()
    ws.mkdir()
    (data / "arslan.db").write_text("db")
    (home / ".ssh" / "id").write_text("key")
    monkeypatch.setattr(config, "data_dir", lambda: data)
    monkeypatch.setenv("HOME", str(home))
    ours = await terminal_exec.run(f"cat '{data / 'arslan.db'}'", cwd=ws, sandbox=False)
    assert ours["sandbox"] == "outside" and not ours["ok"] and "Arslan's own data" in ours["note"]
    secret = await terminal_exec.run(f"cat '{home / '.ssh' / 'id'}'", cwd=ws, sandbox=False)
    assert secret["ok"] and secret["stdout"].strip() == "key"            # ssh, git push, gh need these
    inside = await terminal_exec.run(f"cat '{home / '.ssh' / 'id'}'", cwd=ws, sandbox=True)
    assert not inside["ok"]                                               # but never from the sandbox
    events = await terminal_exec.run("osascript -e 'tell application \"Finder\" to count windows'",
                                     cwd=ws, sandbox=False)
    assert "(-600)" in events["stderr"]                                    # only an approved plain call runs bare


# ── piece 2: after outside content, no network unless the user says so ────────────────

class _NetExec(_Exec):
    async def execute(self, args):
        self.runs.append((terminal_exec.OUTSIDE_SANDBOX.get(), terminal_exec.OFFLINE.get()))
        return dict(self.result)


class _Asker:
    def __init__(self, approve=True, scope="once"):
        self.frames, self.approve, self.scope = [], approve, scope

    async def __call__(self, frame):
        self.frames.append(frame)
        return {"approved": self.approve, "scope": self.scope, "by": "user", "call_id": frame["call_id"]}


async def _after_outside_content(monkeypatch, command, *, asker=None, outside=False, **args):
    from server.orchestrator import untrusted
    from server.services import permissions
    seen = untrusted.track_turn()
    untrusted.mark_external()                  # this turn read a web page
    ex = _NetExec()
    if outside:
        command_sandbox.grant("c1")            # "for the rest of this conversation" outside the sandbox
    try:
        with permissions.asking_with(asker):
            result = await _dispatch(monkeypatch, command, ex, _Cards(True), **args)
    finally:
        untrusted.end_turn(seen)
        command_sandbox._reset_for_tests()
    return ex, result


async def test_after_outside_content_a_command_in_the_sandbox_runs_offline(execution_db, monkeypatch):
    ex, result = await _after_outside_content(monkeypatch, "python3 report.py")
    assert ex.runs == [(False, True)] and result["ok"]


async def test_without_outside_content_nothing_changes(execution_db, monkeypatch):
    from server.orchestrator import untrusted
    seen = untrusted.track_turn()              # a turn that read nothing from outside
    ex = _NetExec()
    try:
        await _dispatch(monkeypatch, "curl -s https://example.test", ex, _Cards(True))
    finally:
        untrusted.end_turn(seen)
    assert ex.runs == [(False, False)]


async def test_a_command_that_reaches_the_network_asks_first_and_keeps_it_on_yes(execution_db, monkeypatch):
    asker = _Asker()
    ex, result = await _after_outside_content(monkeypatch, "curl -s https://example.test/data.json", asker=asker)
    [frame] = asker.frames
    assert frame["perm_kind"] == "network" and frame["options"] == ["once", "conversation"]
    assert ex.runs == [(False, False)] and result["ok"]
    from server.services import approvals
    assert not approvals.island_may_answer(frame)                  # answered in Arslan, never the island


async def test_a_no_on_the_network_card_runs_nothing(execution_db, monkeypatch):
    ex, result = await _after_outside_content(monkeypatch, "curl -s https://example.test", asker=_Asker(approve=False))
    assert ex.runs == [] and not result["ok"]


async def test_the_model_can_say_a_script_needs_the_network(execution_db, monkeypatch):
    asker = _Asker()
    ex, _ = await _after_outside_content(monkeypatch, "python3 fetch.py", asker=asker, network=True,
                                         why="downloads the price list")
    assert [f["perm_kind"] for f in asker.frames] == ["network"] and asker.frames[0]["why"] == "downloads the price list"
    assert ex.runs == [(False, False)]


async def test_outside_the_sandbox_the_network_card_is_this_time_only_and_ignores_a_grant(execution_db, monkeypatch):
    from server.services import permission_store
    async with execution_db() as db:
        await permission_store.add_grant(db, "c1", "", "network", "network:*")
        await db.commit()
    asker = _Asker()
    ex, _ = await _after_outside_content(monkeypatch, "curl -s https://example.test", asker=asker, outside=True)
    assert [f["options"] for f in asker.frames] == [["once"]]       # asked again, this time only
    assert ex.runs == [(True, False)]


async def test_with_nobody_to_ask_a_network_command_in_the_sandbox_runs_offline(execution_db, monkeypatch):
    ex, result = await _after_outside_content(monkeypatch, "curl -s https://example.test")
    assert ex.runs == [(False, True)] and "without network" in result["network_note"]


def test_run_command_takes_network_and_why():
    from server.orchestrator import tool_loop
    props = tool_loop._NATIVE_PARAM_SCHEMAS["run_command"]["properties"]
    assert props["network"]["type"] == "boolean" and "why" in props

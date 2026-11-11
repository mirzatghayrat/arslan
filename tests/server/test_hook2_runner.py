"""HOOK-2 (docs/plans/0164/HOOK-plugin-hooks.md): the plugin hook runner.

Portable: Claude Code's input in its shape, the answer read from exit codes and JSON, errors mapped to "ask" for
PreToolUse and UserPromptSubmit and to nothing elsewhere, "allow" never an approval, the time limit only lowered.
macOS: real hooks under real seatbelt: a deny from a script in the plugin's own folder, the time limit killing the
process group, a crash, no network, no write outside the hook's temp folder, and the output cap.
"""
import asyncio
import json
import os
import shlex
import sys
import tempfile
import time

import pytest

from server.services import command_sandbox, plugin_hook_runner as runner

macos = pytest.mark.skipif(sys.platform != "darwin" or not command_sandbox.available(),
                           reason="seatbelt is macOS-only")
GUARDS = ("PreToolUse", "UserPromptSubmit")
OTHERS = ("PostToolUse", "SessionStart", "Stop")


def _row(command: str, event: str = "PreToolUse", timeout=10, args=None) -> dict:
    return {"event": event, "type": "command", "command": command, "args": args, "timeout": timeout}


# ── portable: input ──────────────────────────────────────────────────────────────────

def test_the_input_is_claude_codes_with_its_tool_names(tmp_path):
    def tool(name, args):
        data = runner.hook_input("PreToolUse", workspace=tmp_path, session_id="s1", tool=name, args=args)
        return data["tool_name"], data["tool_input"]

    assert tool("run_command", {"command": "ls", "why": "list", "timeout_s": 5, "outside_sandbox": True}) == (
        "Bash", {"command": "ls", "description": "list", "timeout": 5000})
    assert tool("write_file", {"path": "a/b.txt", "content": "x"}) == (
        "Write", {"file_path": str(tmp_path / "a" / "b.txt"), "content": "x"})
    assert tool("edit_file", {"path": "/abs/c.py", "old_string": "1", "new_string": "2"}) == (
        "Edit", {"file_path": "/abs/c.py", "old_string": "1", "new_string": "2"})
    assert tool("read_file", {"path": "r.md", "offset": 3}) == ("Read", {"file_path": str(tmp_path / "r.md"),
                                                                        "offset": 3})
    assert tool("mcp:tools:read", {"q": 1}) == ("mcp__tools__read", {"q": 1})
    base = {"session_id": "s1", "cwd": str(tmp_path), "permission_mode": "default"}
    post = runner.hook_input("PostToolUse", workspace=tmp_path, session_id="s1", tool="run_command",
                             args={"command": "ls"}, response={"ok": True})
    assert post == {**base, "hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"},
                    "tool_response": {"ok": True}}
    assert runner.hook_input("UserPromptSubmit", workspace=tmp_path, session_id="s1", prompt="hi") == {
        **base, "hook_event_name": "UserPromptSubmit", "prompt": "hi"}
    assert runner.hook_input("SessionStart", workspace=tmp_path, session_id="s1")["source"] == "startup"
    assert runner.hook_input("Stop", workspace=tmp_path, session_id="s1", stop_active=True)["stop_hook_active"] is True


def test_a_hooks_own_timeout_can_only_lower_the_limit():
    assert runner.limit_of({"timeout": 60}) == 10
    assert runner.limit_of({"timeout": 2}) == 2
    for value in (None, 0, -1, "5", True):
        assert runner.limit_of({"timeout": value}) == 10


# ── portable: the answer ─────────────────────────────────────────────────────────────

def _json(**fields) -> str:
    return json.dumps(fields)


def test_pretooluse_deny_and_ask():
    assert runner.parse("PreToolUse", 2, "", "no rm here\n") == runner.HookResult(runner.DENY, "no rm here")
    deny = _json(hookSpecificOutput={"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                     "permissionDecisionReason": "dangerous"})
    assert runner.parse("PreToolUse", 0, deny, "") == runner.HookResult(runner.DENY, "dangerous")
    ask = _json(hookSpecificOutput={"permissionDecision": "ask", "permissionDecisionReason": "check"})
    assert runner.parse("PreToolUse", 0, ask, "") == runner.HookResult(runner.ASK, "check")
    assert runner.parse("PreToolUse", 0, _json(decision="block", reason="old form"), "").decision == runner.DENY
    assert runner.parse("PreToolUse", 0, _json(**{"continue": False, "stopReason": "halt"}), "") == runner.HookResult(
        runner.DENY, "halt")


def test_allow_is_no_answer_never_an_approval():
    for out in (_json(hookSpecificOutput={"permissionDecision": "allow", "permissionDecisionReason": "fine",
                                          "updatedInput": {"command": "rm -rf /"}}),
                _json(decision="approve", reason="fine"), "", "plain text", _json(suppressOutput=True)):
        assert runner.parse("PreToolUse", 0, out, "") == runner.HookResult(), out
    assert {runner.NONE, runner.DENY, runner.ASK, runner.BLOCK, runner.CONTINUE} == {
        "none", "deny", "ask", "block", "continue"}                       # no value that approves


@pytest.mark.parametrize("event", GUARDS)
@pytest.mark.parametrize("case", ["timeout", "exit-1", "exit-3", "signal", "bad-json", "json-list", "unknown-value",
                                  "wrong-type"])
def test_an_error_asks_for_a_guard(event, case):
    code, out, timed_out = {"timeout": (None, "", True), "exit-1": (1, "", False), "exit-3": (3, "", False),
                            "signal": (-11, "", False), "bad-json": (0, "{not json", False),
                            "json-list": (0, "[1]", False),
                            "unknown-value": (0, _json(hookSpecificOutput={"permissionDecision": "maybe"},
                                                       decision="maybe"), False),
                            "wrong-type": (0, _json(hookSpecificOutput={"additionalContext": 5,
                                                                        "permissionDecisionReason": 5}), False)}[case]
    result = runner.parse(event, code, out, "", timed_out=timed_out)
    assert (result.decision, result.reason) == (runner.ASK, runner.DIDNT_ANSWER), case
    assert result.error


@pytest.mark.parametrize("event", OTHERS)
@pytest.mark.parametrize("case", [(None, "", True), (1, "", False), (-9, "", False), (0, "{not json", False)])
def test_an_error_adds_nothing_elsewhere_and_is_recorded(event, case):
    code, out, timed_out = case
    result = runner.parse(event, code, out, "context?", timed_out=timed_out)
    assert (result.decision, result.reason, result.context) == (runner.NONE, "", "")
    assert result.error


def test_user_prompt_submit_blocks_or_adds_context():
    assert runner.parse("UserPromptSubmit", 2, "", "secret in it") == runner.HookResult(runner.BLOCK, "secret in it")
    assert runner.parse("UserPromptSubmit", 0, _json(decision="block", reason="no"), "") == runner.HookResult(
        runner.BLOCK, "no")
    add = _json(hookSpecificOutput={"hookEventName": "UserPromptSubmit", "additionalContext": "today is Monday"})
    assert runner.parse("UserPromptSubmit", 0, add, "") == runner.HookResult(context="today is Monday")
    assert runner.parse("UserPromptSubmit", 0, "plain note\n", "") == runner.HookResult(context="plain note")


def test_post_tool_use_and_session_start_only_add_context():
    out = _json(hookSpecificOutput={"hookEventName": "PostToolUse", "additionalContext": "lint: 2 warnings",
                                    "updatedToolOutput": "replaced", "updatedMCPToolOutput": "replaced"})
    assert runner.parse("PostToolUse", 0, out, "") == runner.HookResult(context="lint: 2 warnings")
    assert runner.parse("PostToolUse", 0, _json(decision="block", reason="tests fail"), "") == runner.HookResult(
        context="tests fail")
    assert runner.parse("PostToolUse", 2, "", "fix it") == runner.HookResult(context="fix it")
    assert runner.parse("SessionStart", 0, "branch main\n", "") == runner.HookResult(context="branch main")
    assert runner.parse("SessionStart", 2, "", "x") == runner.HookResult()
    for event in OTHERS:                    # nothing but context, whatever they say
        said = runner.parse(event, 0, _json(hookSpecificOutput={"permissionDecision": "deny"}), "")
        assert said.decision == runner.NONE


def test_stop_continues_with_a_reason():
    assert runner.parse("Stop", 0, _json(decision="block", reason="tests not run"), "") == runner.HookResult(
        runner.CONTINUE, "tests not run")
    assert runner.parse("Stop", 2, "", "keep going") == runner.HookResult(runner.CONTINUE, "keep going")
    assert runner.parse("Stop", 0, _json(decision="block", reason="x", **{"continue": False}), "") == runner.HookResult()
    assert runner.parse("Stop", 0, "", "") == runner.HookResult()


def test_a_refused_write_or_connection_is_named_and_counts_as_an_error():
    write = "bash: /Users/x/out.txt: Operation not permitted"
    net = "urllib.error.URLError: <urlopen error [Errno 8] nodename nor servname provided, or not known>"
    result = runner.parse("PreToolUse", 0, "", write)
    assert (result.decision, result.reason, result.tried) == (runner.ASK, runner.DIDNT_ANSWER, (runner.TRIED_WRITE,))
    assert runner.parse("PostToolUse", 1, "", net).tried == (runner.TRIED_NETWORK,)
    assert runner.parse("PostToolUse", 0, "note", net) == runner.HookResult(error=runner.TRIED_NETWORK,
                                                                            tried=(runner.TRIED_NETWORK,))
    connect = "    sock.connect(sa)\nPermissionError: [Errno 1] Operation not permitted"     # a traceback's end
    assert runner.parse("UserPromptSubmit", 1, "", connect).tried == (runner.TRIED_NETWORK,)
    assert runner.parse("Stop", 7, "", "curl: (7) Failed to connect to 1.1.1.1 port 443").tried == (
        runner.TRIED_NETWORK,)
    denied = runner.parse("PreToolUse", 2, "", f"refused\n{write}")       # a denial stays a denial
    assert (denied.decision, denied.tried) == (runner.DENY, (runner.TRIED_WRITE,))


def test_reasons_and_context_are_capped():
    long = "x" * (runner.TEXT_CAP * 3)
    assert len(runner.parse("PreToolUse", 2, "", long).reason) == runner.TEXT_CAP
    assert len(runner.parse("SessionStart", 0, long, "").context) == runner.TEXT_CAP


async def test_no_sandbox_means_ask_and_nothing_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(command_sandbox, "available", lambda: False)
    marker = tmp_path / "ran"
    for event in GUARDS + OTHERS:
        result = await runner.run(_row(f"touch {marker}", event), {}, plugin_dir=tmp_path, workspace=tmp_path)
        assert result.error and (result.decision == (runner.ASK if event in GUARDS else runner.NONE))
    assert not marker.exists()


async def test_only_the_five_events_and_the_command_type(tmp_path):
    for row in (_row("true", "PermissionRequest"), {**_row("true"), "type": "http"}, {**_row("true"), "command": None}):
        with pytest.raises(ValueError):
            await runner.run(row, {}, plugin_dir=tmp_path, workspace=tmp_path)


# ── macOS: real hooks under real seatbelt ───────────────────────────────────────────

@pytest.fixture
def setup(monkeypatch, tmp_path):
    """A scratch HOME and temp root, a plugin root with plugins `a` (the hook's) and `b`, and a work folder."""
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
    monkeypatch.setattr(command_sandbox, "PLUGIN_FOLDER", root)
    work = tmp_path / "work"
    work.mkdir()
    return root.resolve() / "a", work.resolve()


@pytest.fixture
def parsed(monkeypatch):
    """What each run handed `parse`: (exit code, stdout, stderr)."""
    seen = []
    real = runner.parse

    def spy(event, code, stdout, stderr, **kw):
        seen.append((code, stdout, stderr))
        return real(event, code, stdout, stderr, **kw)

    monkeypatch.setattr(runner, "parse", spy)
    return seen


async def _run(setup, command, event="PreToolUse", payload=None, **row):
    plugin, work = setup
    payload = payload or runner.hook_input(event, workspace=work, session_id="s", tool="run_command",
                                           args={"command": "rm -rf build"}, prompt="hi")
    return await runner.run(_row(command, event, **row), payload, plugin_dir=plugin, workspace=work)


DENY_SCRIPT = """#!/bin/sh
input=$(cat)
case "$input" in
  *'rm -rf'*) echo '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"rm -rf is not allowed"}}' ;;
  *) echo '{"hookSpecificOutput":{"permissionDecision":"allow"}}' ;;
esac
"""


@pytest.mark.macos
@macos
async def test_a_script_in_the_plugins_own_folder_denies_from_its_input(setup):
    plugin, work = setup
    (plugin / "guard.sh").write_text(DENY_SCRIPT)
    (plugin / "guard.sh").chmod(0o755)
    assert await _run(setup, '/bin/sh "${CLAUDE_PLUGIN_ROOT}/guard.sh"') == runner.HookResult(
        runner.DENY, "rm -rf is not allowed")
    safe = runner.hook_input("PreToolUse", workspace=work, session_id="s", tool="run_command", args={"command": "ls"})
    assert await _run(setup, '/bin/sh "${CLAUDE_PLUGIN_ROOT}/guard.sh"', payload=safe) == runner.HookResult()
    exec_form = await runner.run(_row("/bin/sh", args=["${CLAUDE_PLUGIN_ROOT}/guard.sh"]),
                                 runner.hook_input("PreToolUse", workspace=work, session_id="s", tool="run_command",
                                                   args={"command": "rm -rf x"}),
                                 plugin_dir=plugin, workspace=work)
    assert exec_form.decision == runner.DENY


@pytest.mark.macos
@macos
async def test_the_input_arrives_and_the_work_folder_is_readable_and_the_cwd(setup):
    plugin, work = setup
    (work / "notes.md").write_text("from the work folder")
    script = ('import json, sys; d = json.load(sys.stdin); '
              'print(json.dumps({"hookSpecificOutput": {"additionalContext": json.dumps([d, open("notes.md").read()])}}))')
    result = await _run(setup, f"{shlex.quote(sys.executable)} -I -c {shlex.quote(script)}", event="SessionStart",
                        payload=runner.hook_input("SessionStart", workspace=work, session_id="s"))
    data, notes = json.loads(result.context)
    assert data["hook_event_name"] == "SessionStart" and data["cwd"] == str(work)
    assert notes == "from the work folder" and result.error is None


@pytest.mark.macos
@macos
async def test_the_time_limit_asks_and_the_process_group_is_gone(setup, tmp_path):
    start = time.monotonic()
    result = await _run(setup, "sleep 30 & echo $!; sleep 30", timeout=1)
    assert (result.decision, result.reason, result.error) == (runner.ASK, runner.DIDNT_ANSWER, "timed out")
    assert time.monotonic() - start < 8


@pytest.mark.macos
@macos
async def test_a_timed_out_hooks_children_are_killed(setup, parsed):
    await _run(setup, "sleep 30 & echo $!; sleep 30", event="PostToolUse", timeout=1)
    child = int(parsed[0][1].split()[0])
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail(f"the hook's child {child} outlived the time limit")


@pytest.mark.macos
@macos
@pytest.mark.parametrize("command", ["exit 1", "kill -SEGV $$", "echo '{broken'"])
async def test_a_crash_or_bad_output_asks(setup, command):
    result = await _run(setup, command)
    assert (result.decision, result.reason) == (runner.ASK, runner.DIDNT_ANSWER) and result.error


@pytest.mark.macos
@macos
async def test_no_network(setup):
    script = ("import socket, urllib.request\n"
              "try:\n    urllib.request.urlopen('https://example.com', timeout=3)\nexcept Exception as e: print(e)\n"
              "socket.create_connection(('1.1.1.1', 443), timeout=3)\n")
    path = setup[0] / "net.py"
    path.write_text(script)
    result = await _run(setup, f'{shlex.quote(sys.executable)} -I "${{CLAUDE_PLUGIN_ROOT}}/net.py"')
    assert (result.decision, result.reason) == (runner.ASK, runner.DIDNT_ANSWER)
    assert runner.TRIED_NETWORK in result.tried, result


@pytest.mark.macos
@macos
async def test_a_write_outside_its_temp_fails_and_is_recorded(setup):
    plugin, work = setup
    result = await _run(setup, 'echo x > "$TMPDIR/scratch" && cat "$TMPDIR/scratch" && echo x > "$CLAUDE_PROJECT_DIR/out"',
                        event="PostToolUse")
    assert not (work / "out").exists()
    assert result.tried == (runner.TRIED_WRITE,) and result.error and result.context == ""
    for target in ('"${CLAUDE_PLUGIN_ROOT}/sentinel"', '"${CLAUDE_PLUGIN_ROOT}/../b/sentinel"', '"$HOME/out"'):
        result = await _run(setup, f"echo changed > {target}")
        assert (result.decision, result.tried) == (runner.ASK, (runner.TRIED_WRITE,)), target
    assert (plugin / "sentinel").read_text() == "original"
    assert (plugin.parent / "b" / "sentinel").read_text() == "original"
    sibling = await _run(setup, 'cat "${CLAUDE_PLUGIN_ROOT}/../b/sentinel"')     # a sibling plugin isn't readable
    assert sibling.decision == runner.ASK and "original" not in sibling.context
    ok = await _run(setup, 'echo x > "$TMPDIR/f" && cat "${CLAUDE_PLUGIN_ROOT}/sentinel" >/dev/null', event="Stop")
    assert ok == runner.HookResult()                                               # temp written, own folder read


@pytest.mark.macos
@macos
async def test_the_output_is_capped(setup, parsed):
    flood = "head -c 3000000 /dev/zero | tr '\\0' x"
    result = await _run(setup, f"{flood}; {flood} >&2", event="SessionStart")
    assert result.error is None and 0 < len(result.context) <= runner.TEXT_CAP
    _, stdout, stderr = parsed[0]
    for stream in (stdout, stderr):                     # head and tail kept, the middle dropped while running
        assert runner.OUTPUT_CAP <= len(stream) < runner.OUTPUT_CAP + 100
    big = await _run(setup, f"{flood}; exit 2")
    assert big.decision == runner.DENY

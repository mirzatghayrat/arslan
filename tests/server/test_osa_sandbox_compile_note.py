"""A sandboxed osascript compile error says the sandbox may be why (STY2 r4).

Inside the command sandbox osascript can't load Standard Additions or an app's scripting dictionary, so a
valid script fails to compile with the same text a real typo prints. In the STY2 r4 bench, T1 had 9 such
compile errors under run_command and the model spent about 20 calls guessing syntax over them. The stderr
below is what a real-sandbox probe printed (macOS 26, 2026-11-10), byte for byte.
"""
import pytest

from server.orchestrator import tool_loop
from server.orchestrator.recovery_hints import (KEPT_WRAPPED_HINT, SANDBOX_APPLE_EVENTS_HINT,
                                                SANDBOX_OSA_COMPILE_HINT, hint_for)
from server.orchestrator.untrusted import TOOL_CLOSE

_XPC = ("2026-11-10 12:57:05.755 osascript[20689:70966471] Connection Invalid error for service "
        "com.apple.hiservices-xpcservice.\n2026-11-10 12:57:05.755 osascript[20689:70966470] Error received in "
        "message reply handler: Connection invalid\n")
# `set now to (current date)`: valid, and it compiles once Standard Additions load.
VALID_2741 = "20:24: syntax error: Expected “,” but found class name. (-2741)\n"
# A genuine typo prints the same kind of text.
TYPO_2741 = "10:10: syntax error: Expected expression but found end of script. (-2741)\n"
# `return current date`: valid outside the sandbox.
VALID_2740 = "7:19: syntax error: A class name can’t go after this identifier. (-2740)\n"
# An app's terminology inside a tell block: the dictionary did not load.
APP_2740 = _XPC + "36:44: syntax error: A class name can’t go after this identifier. (-2740)\n"
REFUSED_1728 = _XPC + "36:40: execution error: Can’t get application \"Reminders\". (-1728)\n"

COMPILE_ERRORS = [VALID_2741, TYPO_2741, VALID_2740, APP_2740]


def _failed(stderr: str, sandbox: str | None = "workspace", **extra) -> dict:
    result = {"ok": False, "exit_code": 1, "stdout": "", "stderr": stderr, "cwd": "/w", "error": "exit code 1"}
    if sandbox is not None:
        result["sandbox"] = sandbox
    result.update(extra)
    return result


@pytest.mark.parametrize("stderr", COMPILE_ERRORS)
def test_a_sandboxed_compile_error_gets_the_note(stderr):
    assert hint_for("run_command", _failed(stderr)) == SANDBOX_OSA_COMPILE_HINT


@pytest.mark.parametrize("stderr", COMPILE_ERRORS)
@pytest.mark.parametrize("sandbox", ["off", "outside", "unavailable", None])
def test_the_same_error_outside_the_command_sandbox_gets_no_note(stderr, sandbox):
    assert hint_for("run_command", _failed(stderr, sandbox)) is None


def test_a_successful_run_gets_no_note():
    assert hint_for("run_command", {"ok": True, "exit_code": 0, "stdout": VALID_2741, "stderr": "",
                                    "sandbox": "workspace"}) is None


@pytest.mark.parametrize("kept_wrapped,expected", [(False, SANDBOX_APPLE_EVENTS_HINT), (True, KEPT_WRAPPED_HINT)])
def test_a_sandboxed_refusal_keeps_its_own_hint(kept_wrapped, expected):
    hint = hint_for("run_command", _failed(REFUSED_1728, kept_wrapped=kept_wrapped))
    assert hint == expected and SANDBOX_OSA_COMPILE_HINT not in hint


@pytest.mark.parametrize("stderr", [
    "0:40: execution error: Reminders got an error: Can’t get list 1. (-1728)\n",      # the script's own -1728
    "12:15: execution error: The variable foo is not defined. (-2753)\n",
    "0:9: execution error: “foo” doesn’t understand the “bar” message. (-1708)\n",
])
def test_other_osascript_errors_get_no_note(stderr):
    assert hint_for("run_command", _failed(stderr)) is None


@pytest.mark.parametrize("stderr", [
    "/bin/bash: -c: line 1: syntax error near unexpected token `)'\n",
    "  File \"x.py\", line 1\n    print(\n         ^\nSyntaxError: '(' was never closed\n",
    "error: expected expression (-2741 is not this)\n",
])
def test_other_commands_errors_get_no_note(stderr):
    assert hint_for("run_command", _failed(stderr)) != SANDBOX_OSA_COMPILE_HINT


def test_the_note_names_no_way_out_of_the_sandbox():
    lowered = SANDBOX_OSA_COMPILE_HINT.lower()
    for word in ("outside_sandbox", "outside", "card", "approve"):
        assert word not in lowered
    assert "standard additions" in lowered and "typo" in lowered     # both causes are named


def test_the_model_reads_the_note_after_the_untrusted_frame():
    convo, trace = [], []
    tool_loop._record_tool_result("run_command", {"command": "osascript -e 'return current date'"},
                                  _failed(VALID_2740), lambda e: None, trace, "{}", convo)
    after = convo[-1]["content"].split(TOOL_CLOSE, 1)[1]
    assert after.startswith("\n[Host hint:") and SANDBOX_OSA_COMPILE_HINT in after

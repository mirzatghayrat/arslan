"""0.1.50 P2 S3: concrete alternatives at the moment of failure. Error texts
are the ones captured in the kernel bench traces."""
import pytest

from server.orchestrator import tool_loop
from server.orchestrator.recovery_hints import hint_for
from server.orchestrator.untrusted import DELIM_CLOSE

APPLE = {"ok": False, "exit_code": 1, "stdout": "",
         "stderr": "128:133: execution error: Reminders got an error: A privilege violation occurred. (-10004)"}


@pytest.mark.parametrize("tool,result,fragment", [
    ("run_command", APPLE, "EventKit"),
    ("mac_applescript", {"ok": False, "error": "Not authorized to send Apple events to Reminders. (-1743)"}, "EventKit"),
    ("run_command", {"ok": False, "stderr": "zsh:1: command not found: remindctl", "exit_code": 127}, "not installed"),
    ("run_command", {"ok": False, "stderr": "touch: /Library/x: Permission denied"}, "workspace"),
    ("web_extract", {"ok": False, "error": "no extractable text — do not retry this URL"}, "browser_open"),
    ("web_extract", {"ok": False, "error": "fetch failed: http 403"}, "another source"),
])
def test_known_failures_name_an_alternative(tool, result, fragment):
    assert fragment in hint_for(tool, result)


@pytest.mark.parametrize("tool,result", [
    ("run_command", {"ok": True, "stdout": "privilege violation discussed in docs"}),   # success: no hint
    ("run_command", {"ok": False, "stderr": "ValueError: bad input"}),                 # unknown failure
    ("web_extract", {"ok": False, "error": "fetch failed: timeout"}),
])
def test_no_hint_without_a_known_signature(tool, result):
    assert hint_for(tool, result) is None


def test_hint_is_trusted_text_after_the_untrusted_frame():
    convo, trace = [], []
    tool_loop._record_tool_result("run_command", {"command": "osascript …"}, APPLE,
                                  lambda e: None, trace, "{}", convo)
    content = convo[-1]["content"]
    assert DELIM_CLOSE in content
    after = content.split(DELIM_CLOSE, 1)[1]
    assert after.startswith("\n[Host hint:") and "EventKit" in after


def test_web_extract_steer_no_longer_invites_stopping():
    import inspect
    from server.registry import executors
    src = inspect.getsource(executors.WebExtractExecutor)
    assert "use your web_search result snippets or answer with what you have\"" not in src
    assert "only when sources are exhausted" in src

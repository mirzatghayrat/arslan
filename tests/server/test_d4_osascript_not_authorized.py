"""D4 (docs/plans/0162/D4-osascript-not-authorized.md): an osascript to one app that macOS or the app
refused as "not authorized" is a known failure: nothing happened in that app.

K1's before/after runs, T1: osascript told Reminders to make a list, Reminders answered -10004, the
model switched to EventKit and succeeded, yet the task stopped at "needs your review" because any
failed command matching an outbound rule (apple-events) counted as "outcome unknown".

Verified before writing this (2026-10-20, recorded in the PR): from a sender Reminders refuses, a
read, a write and a read-then-write all fail at the FIRST data access with -10004, and no list was
created. -10004 is therefore all-or-nothing for Reminders; other apps raise it on their own terms
and stay unknown. -1743 (Automation not allowed) blocks every event to the app.
"""
import pytest

from server.services import task_service
from tests.server.test_job_checks_0159 import disk, home, outcome, stopped_in  # noqa: F401

T1_COMMAND = """osascript <<'EOF'
tell application "Reminders"
    set theList to make new list with properties {name:"Bench list"}
    make new reminder at end of theList with properties {name:"Call the bank"}
end tell
EOF"""
PRIVILEGE = "112:157: execution error: Reminders got an error: A privilege violation occurred. (-10004)"
NOT_ALLOWED = "0:58: execution error: Not authorized to send Apple events to Notes. (-1743)"


def refused(stderr, exit_code=1):
    return {"ok": False, "exit_code": exit_code, "stdout": "", "stderr": stderr, "error": f"exit code {exit_code}"}


def known(command, result):
    return task_service.known_local_failure("run_command", {"command": command}, result)


def test_the_t1_command_refused_by_reminders_is_known():
    assert known(T1_COMMAND, refused(PRIVILEGE))


def test_automation_not_allowed_for_one_app_is_known():
    assert known("""osascript -e 'tell application "Notes" to make new note with properties {name:"x"}'""",
                 refused(NOT_ALLOWED))


def test_a_trailing_newline_or_extra_stderr_lines_before_it_are_fine():
    assert known(T1_COMMAND, refused("some warning\n" + PRIVILEGE + "\n"))


@pytest.mark.parametrize("command,stderr", [
    # -10004 is the app's own answer; only Reminders is verified all-or-nothing.
    ("""osascript -e 'tell application "Notes" to make new note'""",
     "0:40: execution error: Notes got an error: A privilege violation occurred. (-10004)"),
    # two apps, one of them nested
    ("""osascript <<'EOF'
tell application "Reminders"
    tell application "System Events" to keystroke "x"
end tell
EOF""", PRIVILEGE),
    # spellings that are not counted
    ("""osascript -e 'tell app "Reminders" to make new list'""", PRIVILEGE),
    ("""osascript -e 'tell application id "com.apple.reminders" to make new list'""", PRIVILEGE),
    ("osascript make_list.scpt", PRIVILEGE),
    ("""osascript -l JavaScript -e 'Application("Reminders").make()'""", PRIVILEGE),
    # scripts that run something else
    ("""osascript -e 'tell application "Reminders" to make new list' -e 'do shell script "rm x"'""", PRIVILEGE),
    ("""osascript -e 'run script "other.scpt"' -e 'tell application "Reminders" to make new list'""", PRIVILEGE),
    ("""osascript -e 'set s to load script "x.scpt"' -e 'tell application "Reminders" to count lists'""", PRIVILEGE),
    # more than one osascript, or more than osascript
    ("""osascript -e 'tell application "Reminders" to make new list' && echo ok""", PRIVILEGE),
    ("""osascript -e 'tell application "Reminders" to count lists'; osascript -e 'tell application "Reminders" to count lists'""",
     PRIVILEGE),
    # another error number, or the error names another app
    ("""osascript -e 'tell application "Reminders" to make new list'""",
     "0:40: execution error: Reminders got an error: Can't get list 1. (-1728)"),
    ("""osascript -e 'tell application "Reminders" to make new list'""", NOT_ALLOWED),
    # the here-doc ends at its FIRST delimiter line: what follows ran as shell, not AppleScript
    ("""osascript <<'EOF'
tell application "Reminders" to make new list
EOF
rm -rf build
EOF""", PRIVILEGE),
    # an unquoted here-doc expands $ and backticks: what ran is not what is written
    ("""osascript <<EOF
tell application "Reminders" to make new list with properties {name:"$NAME"}
EOF""", PRIVILEGE),
])
def test_everything_else_stays_unknown(command, stderr):
    assert not known(command, refused(stderr))


def test_a_refusal_stopped_by_a_time_limit_or_a_signal_stays_unknown():
    command = """osascript -e 'tell application "Notes" to make new note'"""
    assert not known(command, {**stopped_in("unavailable"), "stderr": NOT_ALLOWED})
    assert not known(command, refused(NOT_ALLOWED, exit_code=-9))


async def test_the_t1_task_does_not_ask_for_review(execution_db, disk):  # noqa: F811
    task, _ = await outcome(("run_command", {"command": T1_COMMAND}, refused(PRIVILEGE)))
    assert task.pause_reason != "task_reconciliation_required"


async def test_another_apple_events_failure_still_asks_for_review(execution_db, disk):  # noqa: F811
    command = """osascript -e 'tell application "Reminders" to make new list'"""
    task, _ = await outcome(("run_command", {"command": command},
                             refused("0:40: execution error: Reminders got an error: Can't get list 1. (-1728)")))
    assert (task.phase, task.pause_reason) == ("waiting_user", "task_reconciliation_required")

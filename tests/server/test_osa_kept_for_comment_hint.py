"""An approved osascript kept in the command sandbox only because of a comment says so (0.1.64 pre-tag).

L7-7 pre-tag plain-9, T1 r2 (DeepSeek, 2026-11-18): the model's Reminders script was approved, but its `--`
comments kept it wrapped (`task_service.unwrapped_once`, `_OSA_COMMENT`). Inside the sandbox osascript can't load
Standard Additions, so `current date` failed to compile (-2741). The hint it got didn't say why it stayed wrapped,
so the model asked to leave the sandbox instead of dropping the comments. The decision is unchanged: only the hint
now says it, from the same check that made the decision (`task_service.kept_for_comment`).
"""
import re

import pytest

from server.orchestrator.recovery_hints import (KEPT_FOR_COMMENT_HINT, KEPT_WRAPPED_HINT, SANDBOX_OSA_COMPILE_HINT,
                                                hint_for)
from server.services import task_service
from tests.server.test_s2a1_sandbox import _dispatch, _Exec, _UserClick

# T1 r2's command, byte for byte from the run's card frame (only the run's list name is the bench's).
T1_R2 = """osascript <<'SCRIPT'
set listName to "对比测试-arslan-T1-r2-r64p9-ds-deepseek-v4-pro"
set nowDate to current date

-- 明天上午 9 点
set tomorrowDate to nowDate + 1 * days
set time of tomorrowDate to 9 * hours

-- 下一个周五
set fridayDate to nowDate
repeat
	if (weekday of fridayDate) is Friday then exit repeat
	set fridayDate to fridayDate + 1 * days
end repeat
set time of fridayDate to 9 * hours

-- 下一个周一
set mondayDate to nowDate
repeat
	if (weekday of mondayDate) is Monday then exit repeat
	set mondayDate to mondayDate + 1 * days
end repeat
set time of mondayDate to 9 * hours

tell application "Reminders"
	set targetList to missing value
	repeat with l in lists
		if (name of l) is listName then set targetList to l
	end repeat
	if targetList is missing value then
		set targetList to make new list with properties {name:listName}
	end if
	tell targetList
		make new reminder with properties {name:"交周报", due date:tomorrowDate}
		make new reminder with properties {name:"买牛奶", due date:fridayDate}
		make new reminder with properties {name:"给房东打电话", due date:mondayDate}
	end tell
	set resultText to "列表: " & listName & linefeed
	repeat with r in (reminders of targetList)
		set resultText to resultText & (name of r) & " | " & ((due date of r) as text) & linefeed
	end repeat
	return resultText
end tell
SCRIPT"""
COMPILE_2741 = "84:88: syntax error: Expected end of line, etc. but found class name. (-2741)\n"
REFUSED_1728 = "36:40: execution error: Can\u2019t get application \"Reminders\". (-1728)\n"


def _without_comments(command: str) -> str:
    return "\n".join(line for line in command.split("\n") if not line.lstrip().startswith("--"))


def test_t1_r2_is_kept_wrapped_only_for_its_comments():
    assert task_service.unwrapped_once(T1_R2) is False
    assert task_service.kept_for_comment(T1_R2) is True
    clean = _without_comments(T1_R2)
    assert "--" not in clean and task_service.unwrapped_once(clean) is True
    assert task_service.kept_for_comment(clean) is False          # it runs bare: nothing to explain


@pytest.mark.parametrize("command", [
    # Wrapped for another reason as well as the comment: Finder is not one of the bare apps.
    "osascript -e 'tell application \"Finder\" to get name of startup disk -- which disk'",
    # A delete word keeps it wrapped whatever the comment.
    "osascript -e 'tell application \"Reminders\" to delete list \"Old\" -- tidy'",
    # A script that names no app.
    "osascript -e 'set d to current date -- today'",
    # No comment at all, wrapped for its own reason.
    "osascript -e 'tell application \"Finder\" to get name of startup disk'",
    # Not an inline osascript.
    "osascript add_reminders.applescript",
])
def test_a_script_kept_wrapped_for_another_reason_is_not_put_down_to_its_comment(command):
    assert task_service.unwrapped_once(command) is False
    assert task_service.kept_for_comment(command) is False


def _failed(stderr: str, **extra) -> dict:
    return {"ok": False, "exit_code": 1, "stdout": "", "stderr": stderr, "sandbox": "workspace",
            "error": "exit code 1", **extra}


@pytest.mark.parametrize("stderr", [COMPILE_2741, REFUSED_1728])
def test_the_hint_names_the_comments_and_says_to_retry_without_them(stderr):
    hint = hint_for("run_command", _failed(stderr, kept_wrapped=True, kept_for_comment=True))
    assert hint == KEPT_FOR_COMMENT_HINT
    assert re.search(r"\bcomments?\b", hint) and "without" in hint and "--" in hint


@pytest.mark.parametrize("stderr,expected", [(COMPILE_2741, SANDBOX_OSA_COMPILE_HINT), (REFUSED_1728, KEPT_WRAPPED_HINT)])
def test_kept_wrapped_for_another_reason_keeps_its_old_hint(stderr, expected):
    hint = hint_for("run_command", _failed(stderr, kept_wrapped=True))
    assert hint == expected and "comment" not in hint


async def test_the_approved_t1_r2_run_carries_the_reason_to_its_hint(monkeypatch):
    ex, cards = _Exec(_failed(COMPILE_2741)), _UserClick(True)
    result = await _dispatch(monkeypatch, T1_R2, ex, cards)
    assert ex.runs == [(False, False)]                             # still wrapped: the decision is unchanged
    assert result.get("kept_wrapped") is True and result.get("kept_for_comment") is True
    assert hint_for("run_command", result) == KEPT_FOR_COMMENT_HINT


async def test_an_approved_script_wrapped_for_another_reason_carries_no_comment_flag(monkeypatch):
    command = "osascript -e 'tell application \"Finder\" to get name of startup disk -- which disk'"
    ex, cards = _Exec(_failed(REFUSED_1728)), _UserClick(True)
    result = await _dispatch(monkeypatch, command, ex, cards)
    assert "kept_for_comment" not in result

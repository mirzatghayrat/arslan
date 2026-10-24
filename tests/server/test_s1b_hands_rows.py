"""S1b follow-up (cloud audit, ⓪Plan): in a scheduled run, the four Hands tools that need background work
(acting in the browser, a Shortcut, an AppleScript, a takeover) are refused before any card. Like every other
refusal for want of someone to ask (S1b, test_s1b_unattended_rows.py), each now leaves its ledger row, so the
Inbox lists what the scheduled run could not do; a chat turn's refusal (it can start background work) leaves
none."""
import pytest

from server.db import session as db_session
from server.registry import hands_tools
from server.services import desktop_status, permission_store, permissions
from server.services import personal_context as pc
from tests.server.test_hands_0153 import hands  # noqa: F401 — the faked Hands contract


@pytest.fixture(autouse=True)
def _fresh(execution_db):
    permission_store._reset_for_tests()


async def _rows():
    async with db_session.AsyncSessionLocal() as db:
        return list(reversed(await permission_store.recent(db)))


_CALLS = [
    ("site", lambda: hands_tools.BrowserClickExecutor().execute({"element": "Buy"})),
    ("shortcut", lambda: hands_tools.MacRunShortcutExecutor().execute({"name": "Morning"})),
    ("app_risky", lambda: hands_tools.MacAppleScriptExecutor().execute(
        {"script": 'tell application "Notes" to make new note'})),
    ("takeover", lambda: hands_tools.DesktopTakeoverExecutor().execute({"why": "tidy", "minutes": 5})),
]


@pytest.mark.parametrize("kind,call", _CALLS, ids=[k for k, _ in _CALLS])
async def test_a_scheduled_runs_hands_refusal_is_listed_in_the_inbox(hands, kind, call):  # noqa: F811
    with pc.bind(pc.TaskMemoryContext(task_id="s", run_id="fire-1", conversation_id="scheduled-1")), \
            desktop_status.working("scheduled-1", kind="scheduled"):
        result = await call()
    assert result["executed"] is False and result["code"] == "act_in_background"
    assert "Tell the user" in result["error"]
    [row] = await _rows()
    assert (row.kind, row.decided_by, row.decision, row.conversation_id) == (kind, "policy", "deny", "scheduled-1")
    assert permission_store.could_not_ask(row) and not (row.extra or {}).get(permissions.ALWAYS_KEY)
    assert hands.ops("press") == []


@pytest.mark.parametrize("kind,call", _CALLS, ids=[k for k, _ in _CALLS])
async def test_a_chat_turns_refusal_leaves_no_row(hands, kind, call):  # noqa: F811
    with pc.bind(pc.TaskMemoryContext(task_id="t", run_id="r", conversation_id="c1")), desktop_status.working("c1"):
        result = await call()
    assert result["code"] == "act_in_background" and "start_background_work" in result["error"]
    assert await _rows() == []

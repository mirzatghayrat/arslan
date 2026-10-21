"""S1b (U14 c): what the tool loop refuses because nobody can be asked is listed in the Inbox (card S1).

A scheduled run has no card callbacks, so the tool loop refuses a command that needs a card, a command
asked to run outside the sandbox, a write in the user's own folder, a schedule, another machine, and the
network after outside content, without ever reaching `permissions.decide`. Before S1b those refusals
left no ledger row ("yet", scheduler.py), so the Inbox never showed what a scheduled run could not do.
Now each writes the row decide() writes for the same case: decided by policy, denied, no "Always" set
(⓪Plan Q2), and the model is told to let the user do it in a chat. A turn with someone to ask that has
no callback for the step (none today) is refused as before, with no row: the Inbox lists only what a
run with nobody there could not do.
"""
import pytest

from server.db import session as db_session
from server.db.models import Setting
from server.orchestrator import tool_loop, untrusted
from server.services import permission_store, permissions, task_service


@pytest.fixture(autouse=True)
def _fresh(execution_db, monkeypatch, tmp_path):
    permission_store._reset_for_tests()
    monkeypatch.setenv("ARSLAN_DEFAULT_WORKSPACE", str(tmp_path / "Arslan"))


async def _rows():
    async with db_session.AsyncSessionLocal() as db:
        return list(reversed(await permission_store.recent(db)))


async def _dispatch(key, args):
    async def tools():
        return [{"key": key, "description": key}]
    return await tool_loop._dispatch_tool(key, args, "", resolve_tools=tools, emit=lambda e: None,
                                          tool_timeout_s=5, tool_trace=[], convo=[], conversation_id="conv-u")


def _policy(row, kind):
    return (row.kind, row.decided_by, row.decision, row.conversation_id) == (kind, "policy", "deny", "conv-u") \
        and permission_store.could_not_ask(row) and not (row.extra or {}).get(permissions.ALWAYS_KEY)


async def _ask(frame):
    raise AssertionError("no card in this test")


async def test_a_command_that_needs_a_card_is_listed(tmp_path):
    out = await _dispatch("run_command", {"command": "git push origin main"})
    [row] = await _rows()
    assert out["ok"] is False and "nobody to ask" in out["error"]
    assert _policy(row, "command") and row.target == "rules:git-push" and row.detail == "git push origin main"


async def test_a_command_asked_to_run_outside_the_sandbox_is_listed():
    out = await _dispatch("run_command", {"command": "ls", "outside_sandbox": True})
    [row] = await _rows()
    assert out["ok"] is False and _policy(row, "command") and row.target == "unsandboxed:*"


async def test_a_write_in_the_users_own_folder_is_listed(tmp_path):
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    async with db_session.AsyncSessionLocal() as db:
        db.add(Setting(key="workspace_dir", value=str(chosen)))
        await db.commit()
    out = await _dispatch("write_file", {"path": "a.md", "content": "x"})
    [row] = await _rows()
    assert out["ok"] is False and not (chosen / "a.md").exists()
    assert _policy(row, "workspace_write") and row.target == str(chosen.resolve())


async def test_a_schedule_and_another_machine_are_listed():
    await _dispatch("schedule_task", {"name": "digest", "when": "daily 08:00", "prompt": "x"})
    await _dispatch("ssh_run", {"host": "studio.local", "command": "ls"})
    first, second = await _rows()
    assert _policy(first, "schedule") and _policy(second, "remote") and second.target == "studio.local"


async def test_the_network_after_outside_content_is_listed(monkeypatch):
    monkeypatch.setattr(untrusted, "external_seen", lambda: True)
    monkeypatch.setattr(task_service, "bare_shortcut", lambda command: True)
    out = await tool_loop._network_after_outside_content(
        "shortcuts run Fetch", {}, sandbox_on=True, run_outside=False, unwrapped=True, conversation_id="conv-u")
    [row] = await _rows()
    assert "refused" in out and _policy(row, "network")


async def test_with_someone_to_ask_a_missing_callback_writes_no_row():
    with permissions.asking_with(_ask):
        out = await _dispatch("run_command", {"command": "git push origin main"})
    assert out["ok"] is False and await _rows() == []

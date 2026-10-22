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
    assert out["ok"] is False and _policy(row, "outside") and row.target == "*"      # S4a: its own kind


@pytest.mark.parametrize("key,args", [("write_file", {"path": "a.md", "content": "x"}),
                                      ("edit_file", {"path": "a.md", "old_string": "old", "new_string": "x"})])
async def test_a_write_or_an_edit_in_the_users_own_folder_is_listed(tmp_path, key, args):
    """⓪Plan's condition: the schedule card promises any step that needs an OK is listed in the Inbox."""
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    (chosen / "a.md").write_text("old")
    async with db_session.AsyncSessionLocal() as db:
        db.add(Setting(key="workspace_dir", value=str(chosen)))
        await db.commit()
    out = await _dispatch(key, args)
    [row] = await _rows()
    assert out["ok"] is False and (chosen / "a.md").read_text() == "old"
    assert _policy(row, "workspace_write") and row.target == str(chosen.resolve())


async def test_a_schedule_and_another_machine_are_listed():
    await _dispatch("schedule_task", {"name": "digest", "when": "daily 08:00", "prompt": "x"})
    await _dispatch("ssh_run", {"host": "studio.local", "command": "ls"})
    first, second = await _rows()
    assert _policy(first, "schedule") and _policy(second, "remote") and second.target == "remote:studio.local"


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


async def test_a_connector_and_a_machine_offered_with_nobody_there_are_listed():
    """⓪Plan's review: the schedule card promises every step that needs an OK is listed; offering a
    connector or enrolling a machine needs the user too."""
    await _dispatch("suggest_connector", {"name": "GitHub"})
    await _dispatch("enroll_node", {"host": "studio.local", "user": "me"})
    first, second = await _rows()
    assert _policy(first, "capability") and first.target == "connector:GitHub"
    assert _policy(second, "remote") and second.target == "remote:studio.local"


async def test_a_capability_found_with_nobody_there_is_listed_too(monkeypatch):
    """⓪Plan: the Capabilities page keeps the find as before, and the Inbox lists it too: the Inbox is
    the one list a user checks after a scheduled run. A background job (which has its own card surface)
    only records it, as before."""
    from server.services import capability_flow, capability_search
    found = []
    cand = {"name": "pdf-tools", "kind": "skill"}
    monkeypatch.setattr(capability_search, "seen", lambda conversation, cid: cand)
    monkeypatch.setattr(capability_flow, "installable", lambda c: None)
    monkeypatch.setattr(capability_flow, "card_for", lambda c, **kw: {})

    async def record(c, **kw):
        found.append(c["name"])
    monkeypatch.setattr(capability_flow, "record_find", record)
    out = await capability_flow.propose({"candidate_id": "c1", "why": "read PDFs"}, conversation_id="conv-u",
                                        ask=None, emit=lambda e: None)
    [row] = await _rows()
    assert out["recorded"] is True and found == ["pdf-tools"]
    assert _policy(row, "capability") and row.target == "capability:pdf-tools"
    with permissions.asking_with(_ask):                           # a job: recorded only
        await capability_flow.propose({"candidate_id": "c1"}, conversation_id="conv-u", ask=None,
                                      emit=lambda e: None)
    assert len(await _rows()) == 1 and found == ["pdf-tools", "pdf-tools"]

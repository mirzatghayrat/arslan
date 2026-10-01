"""0.1.41 desktop status: what the shell reads while its window is hidden."""
import time

import pytest

from server.services import desktop_status, scheduler
from tests.server.test_run_command_confirm_flow import (  # noqa: F401 — fixture import
    _collect_until, _enable_shell, _stub_answer_route, _stub_run_command_executor,
    _stub_tool_loop_adapter, app_client)
from tests.server.test_scheduler import _add_inflight, _seed_task, memdb  # noqa: F401


@pytest.fixture(autouse=True)
def fresh():
    desktop_status._reset_for_tests()
    yield
    desktop_status._reset_for_tests()


def test_counts_follow_the_blocks_however_they_exit():
    with desktop_status.working("c1"):
        assert desktop_status.snapshot()["working"] == 1
        with pytest.raises(RuntimeError):
            with desktop_status.working("c2"):
                assert desktop_status.snapshot()["working"] == 2
                raise RuntimeError
        assert desktop_status.snapshot()["working"] == 1
    with desktop_status.awaiting_approval("c1"):
        snap = desktop_status.snapshot()
        assert snap["awaiting"] == 1 and snap["events"][-1]["kind"] == "approval_needed"
    snap = desktop_status.snapshot()
    assert snap["working"] == 0 and snap["awaiting"] == 0


def test_cursor_returns_only_newer_events_and_events_carry_no_text():
    first = desktop_status.push("turn_finished", conversation_id="c1", outcome="ok")
    desktop_status.push("turn_finished", conversation_id="c2", outcome="error")
    snap = desktop_status.snapshot(after=first["id"])
    assert [e["conversation_id"] for e in snap["events"]] == ["c2"]
    assert snap["cursor"] == first["id"] + 1
    assert set(snap["events"][0]) == {"id", "kind", "conversation_id", "outcome", "task_id", "at"}
    with pytest.raises(ValueError):
        desktop_status.push("message_text", conversation_id="c1")
    with pytest.raises(ValueError):
        desktop_status.push("turn_finished", outcome="done: here is your secret")


async def test_status_endpoint_defaults_on_and_names_only_scheduled_tasks(client):
    desktop_status.push("turn_finished", conversation_id="c1", outcome="ok")
    body = (await client.get("/api/v1/desktop/status")).json()
    assert body["keep_awake"] is True and body["notifications"] is True
    assert body["events"][0]["task_name"] == ""          # no conversation text ever
    r = await client.put("/api/v1/settings", json={"keep_awake_enabled": False,
                                                     "desktop_notifications_enabled": False})
    assert r.status_code == 200, r.text
    body = (await client.get(f"/api/v1/desktop/status?after={body['cursor']}")).json()
    assert body["keep_awake"] is False and body["notifications"] is False
    assert body["events"] == []


async def test_scheduler_reports_finish_and_pause(memdb):  # noqa: F811
    task_id = await _seed_task(memdb, name="早报", conversation_id="c-sched")
    row = await _add_inflight(memdb, task_id)
    await scheduler.record_outcome(task_id, True, row_id=row)
    row = await _add_inflight(memdb, task_id)
    await scheduler.record_outcome(task_id, False, row_id=row, reason="x", count_failure=False)
    for _ in range(scheduler.PAUSE_AFTER_FAILURES):
        row = await _add_inflight(memdb, task_id)
        await scheduler.record_outcome(task_id, False, row_id=row, reason="boom")
    kinds = [(e["kind"], e["outcome"]) for e in desktop_status.snapshot()["events"]]
    assert kinds[:2] == [("scheduled_finished", "ok"), ("scheduled_finished", "cancelled")]
    assert kinds[-2:] == [("scheduled_finished", "error"), ("scheduled_paused", None)]
    assert all(e["task_id"] == task_id and e["conversation_id"] == "c-sched"
               for e in desktop_status.snapshot()["events"])


def test_a_sent_confirmation_card_counts_as_awaiting_and_the_turn_reports_done(app_client, monkeypatch):  # noqa: F811
    _enable_shell(app_client)
    _stub_answer_route(monkeypatch)
    _stub_tool_loop_adapter(monkeypatch, "rm", ["old.txt"])      # 0.1.48: deleting shows a card
    _stub_run_command_executor(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "check the repo"})
        call_id = _collect_until(ws, "propose_run_command")[-1]["call_id"]
        snap = desktop_status.snapshot()
        assert snap["awaiting"] == 1 and snap["working"] == 1
        assert [e["kind"] for e in snap["events"]] == ["approval_needed"]
        ws.send_json({"type": "confirm_run_command", "call_id": call_id})
        _collect_until(ws, "stream_end")
        # stream_end is not the end of the turn's bookkeeping: wait, socket still
        # open, for the turn to report itself (closing the socket would cancel it).
        deadline = time.monotonic() + 10
        while (not any(e["kind"] == "turn_finished" for e in desktop_status.snapshot()["events"])
               and time.monotonic() < deadline):
            time.sleep(0.02)
        snap = desktop_status.snapshot()
    assert snap["awaiting"] == 0 and snap["working"] == 0
    assert snap["events"][-1]["kind"] == "turn_finished" and snap["events"][-1]["outcome"] == "ok"


def test_an_auto_approved_command_never_notifies(app_client, monkeypatch):  # noqa: F811
    _enable_shell(app_client, policy="ask_risky")        # LOW-risk read-only runs without a card
    _stub_answer_route(monkeypatch)
    _stub_tool_loop_adapter(monkeypatch, "git", ["status"])
    _stub_run_command_executor(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "check the repo"})
        frames = _collect_until(ws, "stream_end")
    assert not any(f.get("type") == "propose_run_command" for f in frames)
    assert "approval_needed" not in [e["kind"] for e in desktop_status.snapshot()["events"]]


def test_status_polls_are_not_access_logged_but_other_requests_are():
    import logging
    import server.main  # noqa: F401 — installs the filter
    access = logging.getLogger("uvicorn.access")

    def record(path):
        return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1,
                                 '%s - "%s %s HTTP/1.1" %d', ("127.0.0.1:1", "GET", path, 200), None)
    assert not all(f.filter(record("/api/v1/desktop/status?after=3")) for f in access.filters)
    assert all(f.filter(record("/api/v1/runs")) for f in access.filters)

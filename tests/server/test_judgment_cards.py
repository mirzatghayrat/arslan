"""C4 (v0.1.63, decision D8): command cards are no longer shadow-judged. A card in the window and
one in a job are shown and answered as before, and their ledger rows are written as before, but
nothing lands in the judgments table. The judge is patched to answer here, so a shadow call that
came back would write a row."""
import asyncio

import pytest
from sqlalchemy import select

from server.db.models import ApprovalEvent, Judgment
from server.services import judgment
from tests.server.conftest import build_ws_client
from tests.server.test_run_command_confirm_flow import (
    _collect_until, _enable_shell, _stub_run_command_executor, _stub_tool_loop_adapter)


class _Adapter:
    model = "fast-fixture"

    async def chat(self, *, system, user):
        class R:
            content = '{"answer": false, "p": 0.2}'
        return R()


@pytest.fixture
def answering_judge(monkeypatch):
    async def make():
        return _Adapter()
    monkeypatch.setattr(judgment, "_adapter", make)


@pytest.fixture
def app_client(tmp_path, monkeypatch, portal, answering_judge):
    return build_ws_client(portal, tmp_path, monkeypatch, db_name="judge.db")


async def _settled_rows(maker, model):
    await asyncio.sleep(0.3)               # time a fire-and-forget judgment would have had to land
    async with maker() as db:
        return (await db.scalars(select(model).order_by(model.id))).all()


@pytest.mark.parametrize("answer,decision", [("confirm_run_command", "allow"), ("cancel_run_command", "deny")])
def test_a_command_card_in_the_window_is_answered_and_not_judged(app_client, monkeypatch, answer, decision):
    _enable_shell(app_client, policy="ask_risky")
    _stub_tool_loop_adapter(monkeypatch, "rm", ["old.txt"])
    fake = _stub_run_command_executor(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "delete old.txt please"})
        card = _collect_until(ws, "propose_run_command")[-1]
        ws.send_json({"type": answer, "call_id": card["call_id"]})
        _collect_until(ws, "stream_end")
    assert app_client.portal.call(_settled_rows, app_client.db_maker, Judgment) == []
    [event] = app_client.portal.call(_settled_rows, app_client.db_maker, ApprovalEvent)
    assert (event.kind, event.decided_by, event.decision) == ("command", "user", decision)
    assert len(fake.calls) == (1 if decision == "allow" else 0)


@pytest.mark.parametrize("sandbox", [None, "retry"])
async def test_a_jobs_command_card_is_answered_and_not_judged(execution_db, monkeypatch, answering_judge, sandbox):
    """A rule card (decided by permissions.decide, with its ledger row) and a sandbox card (a plain
    card: no ledger row until S4a), each answered by a window on the conversation."""
    from server.services import approvals, run_registry

    def window(frame):
        if frame["type"] == "propose_run_command":
            approvals.answer({"type": "confirm_run_command", "call_id": frame["call_id"]})
    monkeypatch.setattr(run_registry, "make_emit", lambda cid: window)

    async def ask_all(db):
        return "ask_all"
    monkeypatch.setattr("server.services.settings_service.shell_confirm_policy", ask_all)
    job = approvals.JobConfirmations("job-c", job_id="job-1")
    assert await job.command("ls -la", [], sandbox=sandbox) is True
    assert await _settled_rows(execution_db, Judgment) == []
    events = await _settled_rows(execution_db, ApprovalEvent)
    if sandbox is None:
        assert [(e.kind, e.decided_by, e.decision, e.job_id) for e in events] == [("command", "user", "allow", "job-1")]
    else:
        assert events == []

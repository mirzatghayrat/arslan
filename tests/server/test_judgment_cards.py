"""tool.approval in shadow (0.1.52 S2): every command card still appears; the judge's
view is recorded beside it, and the user's real answer is joined to it."""
import asyncio

import pytest
from sqlalchemy import select

from server.db.models import Judgment
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
def app_client(tmp_path, monkeypatch, portal):
    async def make():
        return _Adapter()
    monkeypatch.setattr(judgment, "_adapter", make)
    return build_ws_client(portal, tmp_path, monkeypatch, db_name="judge.db")


def _rows(app_client):
    async def read():
        for _ in range(40):
            async with app_client.db_maker() as db:
                rows = (await db.scalars(select(Judgment))).all()
            if rows and all(r.outcome for r in rows):
                return rows
            await asyncio.sleep(0.1)
        return rows
    return app_client.portal.call(read)


@pytest.mark.parametrize("answer,outcome", [("confirm_run_command", "approved"), ("cancel_run_command", "declined")])
def test_a_command_card_is_shadow_judged_and_the_real_answer_is_joined(app_client, monkeypatch, answer, outcome):
    _enable_shell(app_client, policy="ask_risky")
    _stub_tool_loop_adapter(monkeypatch, "rm", ["old.txt"])
    fake = _stub_run_command_executor(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "delete old.txt please"})
        card = _collect_until(ws, "propose_run_command")[-1]
        ws.send_json({"type": answer, "call_id": card["call_id"]})
        _collect_until(ws, "stream_end")
    (row,) = _rows(app_client)
    assert row.point == "tool.approval" and row.mode == "shadow" and row.ref == card["call_id"]
    assert row.verdict is False and row.outcome == outcome
    assert row.state["user_request"] == "delete old.txt please" and row.state["rule"] == "delete"
    assert len(fake.calls) == (1 if outcome == "approved" else 0)       # shadow changed nothing


async def test_a_background_job_card_is_shadow_judged_too(execution_db, monkeypatch):
    from server.services import approvals
    async def make():
        return _Adapter()
    monkeypatch.setattr(judgment, "_adapter", make)

    async def ask(cid, frame):
        return True
    monkeypatch.setattr(approvals, "ask", ask)
    async def ask_all(db):
        return "ask_all"
    monkeypatch.setattr("server.services.settings_service.shell_confirm_policy", ask_all)
    assert await approvals.JobConfirmations("job-c").command("ls -la", []) is True
    for _ in range(40):
        async with execution_db() as db:
            rows = (await db.scalars(select(Judgment))).all()
        if rows and rows[0].outcome:
            break
        await asyncio.sleep(0.1)
    assert rows[0].point == "tool.approval" and rows[0].outcome == "approved" and rows[0].conversation_id == "job-c"

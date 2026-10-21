"""S1 (⓪Plan's Q4): a scheduled run is told apart two ways, and they must agree.

S1 treats "no card surface bound" (`permissions.current_asker() is None`) as a scheduled run: decide refuses
there, and start_background_work is not offered. Hands tells it by desktop_status' work kind
(`hands_tools._scheduled_run()`). This fires a real scheduled task and checks both, so neither can drift
from the other without a failing test.
"""
from server.db.models import ScheduledTask
from tests.server.test_scheduled_arslan_turn import _task, db  # noqa: F401 — the fixture


async def test_a_scheduled_fire_has_no_card_surface_and_hands_sees_it_scheduled(db, monkeypatch):  # noqa: F811
    from server.orchestrator import arslan as arslan_mod
    from server.registry import hands_tools
    from server.services import permissions, scheduler
    seen = {}

    async def turn(conversation_id, user_message, emit, **kw):
        seen["asker"] = permissions.current_asker()
        seen["scheduled"] = hands_tools._scheduled_run()
        return "done"
    monkeypatch.setattr(arslan_mod, "_handle_answer", turn)
    tid = await _task(db, prompt="check the news", cid="conv-s1")
    async with db() as s:
        task = await s.get(ScheduledTask, tid)
    await scheduler._fire(task)
    assert seen["asker"] is None and seen["scheduled"] is not None

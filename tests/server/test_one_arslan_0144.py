"""0.1.44 one Arslan: with experts switched off (the product default), nothing is
ever handed to an expert — Arslan answers itself — and phases an earlier version
parked in a conversation cannot fire."""
import pytest

import server.db.session as db_session
from server.orchestrator import arslan, router, tool_loop
from server.services import phase_service
from tests.server.test_promise_guard import _SeqAdapter, maker  # noqa: F401

pytestmark = pytest.mark.one_arslan


@pytest.fixture
def no_dispatch(monkeypatch):
    dispatched = []

    async def refuse(*args, **kwargs):
        dispatched.append(args)
        raise AssertionError("an expert was dispatched")
    for name in ("_dispatch_spawn", "dispatch_routed", "confirm_and_execute"):
        monkeypatch.setattr(arslan, name, refuse)
    return dispatched


def test_the_product_default_is_off():
    assert arslan.EXPERTS_ENABLED is False


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["route", "suggest_create", "suggest_update"])
async def test_expert_actions_become_arslan_answering(maker, no_dispatch, monkeypatch, action):  # noqa: F811
    async def fake_route(conv, msg):
        return router.RouterResult(action=action, spawn_id=6, task_brief="make a deck")
    monkeypatch.setattr(arslan.router, "route", fake_route)
    adapter = _SeqAdapter(["Here is the outline I made myself."])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    events = []
    await arslan.handle_user_message("main", "@Deck Master make a deck", events.append)
    streamed = "".join(e.get("content", "") for e in events if e["type"] == "stream_chunk")
    assert "outline I made myself" in streamed
    kinds = {e["type"] for e in events}
    assert not kinds & {"routing", "suggest_create", "suggest_update", "propose_invite", "propose_staffing"}
    assert no_dispatch == []


@pytest.mark.asyncio
async def test_a_parked_invite_from_an_earlier_version_cannot_fire(maker, no_dispatch, monkeypatch):  # noqa: F811
    await phase_service.set_inviting("main", 6, task_brief="make a deck", user_message="make a deck")

    async def fake_route(conv, msg):
        return router.RouterResult(action="answer")
    monkeypatch.setattr(arslan.router, "route", fake_route)
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _SeqAdapter(["Sure."]))
    await arslan.handle_user_message("main", "好", lambda e: None)   # a bare confirm used to accept it
    assert no_dispatch == []
    assert await phase_service.get_pending_invite("main") is None
    assert db_session  # the maker fixture points the session factory at the test database


def test_migration_0056_hands_every_scheduled_task_to_arslan_and_keeps_the_rest(tmp_path):
    import sqlalchemy as sa
    from server.db.migrations.versions._0056_scheduled_tasks_run_as_arslan import upgrade_sync
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE scheduled_tasks (id INTEGER PRIMARY KEY, name TEXT, prompt TEXT, "
                                   "spawn_id INTEGER, target TEXT)"))
        connection.execute(sa.text("INSERT INTO scheduled_tasks VALUES (1, 'digest', 'summarize', 6, 'spawn'), "
                                   "(2, 'mine', 'check', NULL, 'arslan')"))
        upgrade_sync(connection)
        upgrade_sync(connection)
        rows = connection.execute(sa.text("SELECT id, name, prompt, spawn_id, target FROM scheduled_tasks ORDER BY id")).all()
    assert rows == [(1, "digest", "summarize", 6, "arslan"), (2, "mine", "check", None, "arslan")]


def test_an_old_expert_scheduled_row_still_fires_as_arslan():
    from server.db.models import ScheduledTask
    from server.services import scheduler
    assert scheduler._target(ScheduledTask(name="x", prompt="y", spawn_id=6, target="spawn")) == "arslan"


@pytest.mark.asyncio
async def test_an_expert_becomes_a_skill_arslan_can_see_and_read(execution_db):
    from server.db.models import SkillPack, Spawn
    from server.registry.executors import ReadSkillExecutor
    from server.services import expert_conversion
    prompt = "You research local speech models. Always compare WER and memory, cite the model card. " * 3
    async with execution_db() as db:
        db.add(Spawn(id=6, name="Research Analyst", domain_category="researcher", system_prompt=prompt))
        await db.commit()
    assert await arslan._skill_index() == ""                  # no skills yet: nothing offered
    assert [e["converted"] for e in await expert_conversion.list_experts()] == [False]
    first = await expert_conversion.convert(6)
    again = await expert_conversion.convert(6)
    assert first["ok"] and again == {"ok": True, "key": first["key"], "already": True}
    async with execution_db() as db:
        pack = await db.get(SkillPack, first["key"])
    assert pack.status == "registered" and "## Trigger" in pack.body and "compare WER" in pack.body
    assert [e["converted"] for e in await expert_conversion.list_experts()] == [True]
    index = await arslan._skill_index()
    assert first["key"] in index and "Research Analyst" in index
    read = await ReadSkillExecutor().execute({"key": first["key"]})
    assert read["ok"] and "compare WER" in read["body"]


@pytest.mark.asyncio
async def test_converting_a_missing_or_empty_expert_says_why(execution_db):
    from server.db.models import Spawn
    from server.services import expert_conversion
    async with execution_db() as db:
        db.add(Spawn(id=7, name="Tiny", domain_category="x", system_prompt="hi"))
        await db.commit()
    assert (await expert_conversion.convert(99))["code"] == "expert_not_found"
    assert (await expert_conversion.convert(7)) == {"ok": False, "code": "expert_prompt_too_short"}   # no method to keep


@pytest.mark.asyncio
async def test_arslan_is_offered_read_skill_only_when_skills_exist(execution_db):
    from server.db.models import SkillPack
    keys = lambda tools: [t["key"] for t in tools]  # noqa: E731
    assert "read_skill" not in keys(await arslan._arslan_tools())
    async with execution_db() as db:
        db.add(SkillPack(key="weekly-report", name="Weekly report", category="method", description="How I write my weekly report",
                         tier="safe", status="registered", body="# Weekly\n\n## Trigger\nWeekly report.\n\n## Method\n" + "x" * 80))
        await db.commit()
    tools = await arslan._arslan_tools()
    offered = next(t for t in tools if t["key"] == "read_skill")
    assert "weekly-report — Weekly report" in offered["description"]

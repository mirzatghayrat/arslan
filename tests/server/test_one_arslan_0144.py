"""0.1.44 one Arslan: with experts switched off (the product default), nothing is
ever handed to an expert — Arslan answers itself — and phases an earlier version
parked in a conversation cannot fire. Since C7b-4 (v0.1.63) there is no dispatcher left
to hand anything to; these keep checking that Arslan answers and the parked row is inert."""
import pytest

import server.db.session as db_session
from server.orchestrator import arslan, tool_loop
from tests.server import pre_0103
from tests.server.test_promise_guard import _SeqAdapter, maker  # noqa: F401


async def _legacy_spawns(sessions, *rows):
    """C7c-5b: no Spawn model; an upgraded install keeps the expert tables (frozen CREATE text)."""
    from sqlalchemy import text
    async with sessions() as db:
        await db.run_sync(pre_0103.load_sync_session)
        for row in rows:
            await db.execute(text(
                "INSERT INTO spawns (id, name, domain_category, system_prompt, is_default) "
                "VALUES (:id, :name, :domain_category, :system_prompt, :is_default)"), {"is_default": 0, **row})
        await db.commit()



@pytest.mark.asyncio
async def test_naming_an_expert_still_gets_arslan_answering(maker, monkeypatch):  # noqa: F811
    # 0.1.48: there is no router left to suggest a route; the @-name is just text.
    adapter = _SeqAdapter(["Here is the outline I made myself."])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)
    events = []
    await arslan.handle_user_message("main", "@Deck Master make a deck", events.append)
    streamed = "".join(e.get("content", "") for e in events if e["type"] == "stream_chunk")
    assert "outline I made myself" in streamed
    kinds = {e["type"] for e in events}
    assert not kinds & {"routing", "suggest_create", "suggest_update", "propose_invite", "propose_staffing"}


@pytest.mark.asyncio
async def test_a_parked_invite_from_an_earlier_version_cannot_fire(maker, monkeypatch):  # noqa: F811
    # 0.1.63 (C1c-1): phase_service is gone; park the row the way it used to write it.
    import json

    from sqlalchemy import text

    await _legacy_spawns(maker)       # spawn_phases has no model since C7c-5b
    async with db_session.AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO spawn_phases (conversation_id, spawn_id, phase, direction, updated_at) "
            "VALUES ('main', 0, 'inviting', :direction, '')"), {"direction": json.dumps(
                {"spawn_id": 6, "task_brief": "make a deck", "user_message": "make a deck",
                 "needs_proposal": False, "announced": False})})
        await db.commit()

    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _SeqAdapter(["Sure."]))
    await arslan.handle_user_message("main", "好", lambda e: None)   # a bare confirm used to accept it
    # 0.1.63 (C1): the turn no longer clears the parked row (nothing reads it any more);
    # what matters is that it did not fire.
    async with db_session.AsyncSessionLocal() as db:
        parked = (await db.execute(text("SELECT phase FROM spawn_phases WHERE conversation_id = 'main'"))).scalar_one()
    assert parked == "inviting"


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


@pytest.mark.asyncio
async def test_arslan_is_offered_read_skill_only_when_skills_exist(execution_db):
    from server.db.models import SkillPack
    keys = lambda tools: [t["key"] for t in tools]  # noqa: E731
    assert "read_skill" not in keys(await arslan._arslan_tools())
    async with execution_db() as db:
        db.add(SkillPack(key="weekly-report", name="Weekly report", category="authored", description="How I write my weekly report",
                         tier="safe", status="registered", body="# Weekly\n\n## Trigger\nWeekly report.\n\n## Method\n" + "x" * 80))
        await db.commit()
    tools = await arslan._arslan_tools()
    offered = next(t for t in tools if t["key"] == "read_skill")
    assert "weekly-report — Weekly report" in offered["description"]


def test_background_evolution_has_no_automatic_entry():
    """0.1.46: a user who had auto-evolution switched on before experts were removed must
    not keep paying to rewrite prompts nothing reads. C2b-2 removed the watch loop, its
    trigger and the run-recorder ping; C7b-1 (v0.1.63) removed the evolution modules
    themselves, so no code path is left that could start an attempt."""
    import importlib.util
    for mod in ("evolution_watcher", "evolution_loop", "evolution_service",
                "evolution_estimate"):
        assert importlib.util.find_spec(f"server.services.{mod}") is None, f"{mod} is back"


def test_startup_no_longer_seeds_the_example_experts():
    import inspect
    from server import main
    # Behaviour would need the whole lifespan; the call site is the whole contract here.
    assert "seed_default_spawns()" not in inspect.getsource(main.lifespan)


@pytest.mark.asyncio
async def test_the_skill_index_counts_only_skills_with_a_body_before_its_limit(execution_db):
    """0.1.55: the limit applied before the bodyless rows were dropped, so registered
    rows without a body took the slots (fresh install: 44 usable skills, 31 shown)."""
    from server.db.models import SkillPack
    async with execution_db() as db:
        for i in range(45):     # sort before the real ones and outnumber the limit
            db.add(SkillPack(key=f"a-empty-{i:02d}", name=f"Empty {i}", category="x", description="",
                             tier="safe", status="registered", body=None))
        db.add(SkillPack(key="z-real", name="Real one", category="x", description="does a thing",
                         tier="safe", status="registered", body="# Real\nsteps"))
        await db.commit()
    index = await arslan._skill_index(limit=40)
    assert "z-real" in index and "a-empty" not in index

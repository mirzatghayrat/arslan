"""B4 identity-bleed fix: during an active clarifying-create phase, a follow-up
answer must keep clarifying (Arslan's voice) and must NOT route/dispatch to an
existing spawn — even if the router would return action="route"."""
import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn
from server.services import phase_service
from tests.server.conftest import MockAdapter


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'clarify.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with m() as s:
            s.add(
                Spawn(
                    id=7,
                    name="seo-auditor",
                    domain_category="marketing",
                    domain_subcategory="seo",
                    capabilities=["seo-audit"],
                    system_prompt="You are an SEO analyst.",
                )
            )
            await s.commit()

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


def _events(collector):
    return lambda ev: collector.append(ev)


async def _fake_curate(need):
    return {"toolsets": [], "skills": [], "mcps": [], "gaps": []}


async def _incomplete_slots(history_text):
    """Slot extraction returning an under-specified need (gather gate must NOT pass)."""
    return {"domain": None, "capability": None, "first_task": None, "recurrence": None}


async def _ready_slots(history_text):
    """Slot extraction returning a complete need (gate passes → propose)."""
    return {"domain": "marketing.seo", "capability": "seo-audit",
            "first_task": "audit keywords", "recurrence": True}


@pytest.mark.asyncio
async def test_followup_during_clarify_does_not_route(maker, monkeypatch):
    """With a clarifying-create phase pinned, a follow-up that the router would
    route to an existing spawn is overridden to the clarify/answer path — no dispatch."""
    from server.orchestrator import arslan, router, tool_loop

    # 1) Arrange: pin a clarifying-create phase on this conversation.
    await phase_service.set_clarifying("main")

    # 2) Router would route to an existing spawn (this is the leak we suppress).
    async def _fake_route(conv, msg):
        return router.RouterResult(action="route", spawn_id=7, task_brief="audit keywords")

    monkeypatch.setattr(arslan.router, "route", _fake_route)

    # 3) Spy: dispatch must NOT be called during clarify.
    dispatched = []

    async def _spy_dispatch(*args, **kwargs):
        dispatched.append((args, kwargs))

    monkeypatch.setattr(arslan, "_dispatch_spawn", _spy_dispatch)

    adapter = MockAdapter(stream_chunks=["Which ", "site?"], chat_content="Which site?")
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    # 4) Act: a clarify follow-up.
    events = []
    await arslan.handle_user_message("main", "the SEO one", _events(events))

    # 5) Assert: no routing during clarify; an answer/clarify stream was produced.
    assert dispatched == []
    types = [e["type"] for e in events]
    assert "routing" not in types and "spawn_meta" not in types
    assert "stream_start" in types and "stream_end" in types
    # speaks as Arslan, not a spawn
    assert all(e.get("source") != "spawn" for e in events if e["type"] == "stream_start")
    # the clarify addendum reached the system prompt (still gathering)
    captured_system = (adapter.chat_stream_calls + adapter.chat_calls)[0]["system"]
    assert "clarifying questions" in captured_system


@pytest.mark.asyncio
async def test_b3_downgrade_pins_gathering_phase(maker, monkeypatch):
    """A bare under-specified create downgrades to clarify (B3) AND pins the
    `gathering` phase so the next turn keeps gathering (slot-based gate)."""
    from server.orchestrator import arslan, router, tool_loop

    async def _fake_route(conv, msg):
        return router.RouterResult(
            action="suggest_create",
            suggested_spawn={"name": "helper"},  # no domain/caps
            task_brief=None,
        )

    monkeypatch.setattr(arslan.router, "route", _fake_route)
    monkeypatch.setattr(arslan.staffing_gather, "extract_slots", _incomplete_slots)
    monkeypatch.setattr(arslan.equipment_service, "curate", _fake_curate)

    adapter = MockAdapter(stream_chunks=["What ", "kind?"], chat_content="What kind?")
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    events = []
    await arslan.handle_user_message("main", "make me a spawn", _events(events))
    assert "suggest_create" not in [e["type"] for e in events]

    # The slot-based gather phase is now pinned (the next turn keeps gathering).
    p = await phase_service.get_pending("main")
    assert p is not None and p["phase"] == "gathering"


@pytest.mark.asyncio
async def test_sufficient_create_during_clarify_proposes_and_clears(maker, monkeypatch):
    """Once the follow-up gives enough (router returns a sufficient suggest_create),
    the proposal IS allowed and the clarifying phase clears — routing resumes."""
    from server.orchestrator import arslan, router

    await phase_service.set_clarifying("main")

    draft = {
        "name": "seo-auditor-2",
        "domain": "marketing.seo",
        "capabilities": ["seo-audit"],
        "persona_role": "SEO analyst",
    }

    async def _fake_route(conv, msg):
        return router.RouterResult(
            action="suggest_create",
            suggested_spawn=draft,
            task_brief="audit my site's keywords",
        )

    monkeypatch.setattr(arslan.router, "route", _fake_route)
    monkeypatch.setattr(arslan.staffing_gather, "extract_slots", _ready_slots)
    monkeypatch.setattr(arslan.equipment_service, "curate", _fake_curate)

    events = []
    await arslan.handle_user_message("main", "audit example.com for keywords", _events(events))
    # B4: once enough is gathered the spine proposes staffing. With the seeded
    # marketing.seo spawn structurally matching the need, the match-and-propose
    # lands in the picker band (propose_staffing) rather than a bare suggest_create;
    # either way it's a real staffing proposal, and the clarify phase must clear.
    types = [e["type"] for e in events]
    assert any(t in types for t in ("propose_staffing", "suggest_create", "propose_invite"))
    # phase cleared — no lingering clarifying state
    assert await phase_service.get_pending("main") is None


@pytest.mark.asyncio
async def test_clarify_phase_released_when_router_returns_answer(maker, monkeypatch):
    """Invariant: the clarifying phase persists only while the router keeps
    producing an insufficient create-downgrade. A turn where the router returns
    plain `answer` (no create-intent) releases the phase."""
    from server.orchestrator import arslan, router, tool_loop

    await phase_service.set_clarifying("main")

    async def _fake_route(conv, msg):
        return router.RouterResult(action="answer")

    monkeypatch.setattr(arslan.router, "route", _fake_route)

    adapter = MockAdapter(stream_chunks=["sure, here's a thought"], chat_content="sure, here's a thought")
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    events = []
    await arslan.handle_user_message("main", "actually, what's the weather like?", _events(events))
    assert "stream_start" in [e["type"] for e in events]
    # phase released — no lingering clarifying state
    assert await phase_service.get_pending("main") is None


@pytest.mark.asyncio
async def test_route_dispatches_after_clarify_released(maker, monkeypatch):
    """After the clarifying phase is released (router returned answer), a
    subsequent legitimate route actually dispatches — no stale mis-divert."""
    from server.orchestrator import arslan, router, tool_loop

    await phase_service.set_clarifying("main")

    # Turn 1: router returns answer → releases the phase.
    async def _route_answer(conv, msg):
        return router.RouterResult(action="answer")

    monkeypatch.setattr(arslan.router, "route", _route_answer)

    adapter = MockAdapter(stream_chunks=["ok"], chat_content="ok")
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    await arslan.handle_user_message("main", "never mind", _events([]))
    assert await phase_service.get_pending("main") is None

    # Turn 2: a legitimate route now dispatches (no suppression).
    async def _route_spawn(conv, msg):
        return router.RouterResult(action="route", spawn_id=7, task_brief="audit keywords")

    monkeypatch.setattr(arslan.router, "route", _route_spawn)

    dispatched = []

    async def _spy_dispatch(*args, **kwargs):
        dispatched.append((args, kwargs))

    monkeypatch.setattr(arslan, "_dispatch_spawn", _spy_dispatch)

    # Spawn 7 is already in the roster → route dispatches directly (no invite card).
    from server.services import roster_service
    await roster_service.join("main", 7, via="invited")

    await arslan.handle_user_message("main", "audit my site", _events([]))
    assert len(dispatched) == 1


@pytest.mark.asyncio
async def test_routing_resumes_after_clarify_cleared(maker, monkeypatch):
    """Sanity: without a clarifying phase, action=route dispatches normally
    (the suppression is scoped to the clarifying phase, not global)."""
    from server.orchestrator import arslan, router

    async def _fake_route(conv, msg):
        return router.RouterResult(action="route", spawn_id=7, task_brief="audit keywords")

    monkeypatch.setattr(arslan.router, "route", _fake_route)

    dispatched = []

    async def _spy_dispatch(*args, **kwargs):
        dispatched.append((args, kwargs))

    monkeypatch.setattr(arslan, "_dispatch_spawn", _spy_dispatch)

    # Spawn 7 is already in the roster → route dispatches directly (no invite card).
    from server.services import roster_service
    await roster_service.join("main", 7, via="invited")

    events = []
    await arslan.handle_user_message("main", "audit my site", _events(events))
    assert len(dispatched) == 1

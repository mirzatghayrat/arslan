"""B3 staffing spine — triage + gather loop (Part 1).

The spine treats a router create-intent (action="suggest_create") as "① this is
plausibly a staffing need", then runs extract→accumulate→gate over the staffing
slots (server.services.staffing_gather):
  - under-specified slots → clarify (Arslan's voice) + pin the gathering phase,
    emitting NO suggest_create / propose frame;
  - a route-intent follow-up while a gathering phase is active → diverted to
    clarify (NOT dispatched), reusing the B4 suppression mechanism.
"""
import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn
from server.services import phase_service, staffing_gather


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'spine.db'}")
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


@pytest.mark.asyncio
async def test_underspecified_gathers_and_clarifies(maker, monkeypatch):
    """Router signals a create intent; extract_slots fills only `domain` (others
    null) → not ready. The spine must NOT emit suggest_create/propose; it clarifies
    via the answer path and pins the `gathering` phase for the next turn."""
    from server.orchestrator import arslan, router, tool_loop

    async def _fake_route(conv, msg):
        return router.RouterResult(
            action="suggest_create",
            suggested_spawn={"name": "helper"},
            task_brief=None,
        )

    async def _fake_extract(history_text):
        # only the domain is confidently present; the rest still unknown
        return {"domain": "marketing.seo", "capability": None,
                "first_task": None, "recurrence": None}

    monkeypatch.setattr(arslan.router, "route", _fake_route)
    monkeypatch.setattr(arslan.staffing_gather, "extract_slots", _fake_extract)
    monkeypatch.setattr(arslan.equipment_service, "curate", _fake_curate)

    captured = {}

    class _A:
        async def chat_stream(self, system, user, history=None):
            captured["system"] = system
            for piece in ["What ", "exactly?"]:
                yield piece

    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _A())

    events = []
    await arslan.handle_user_message("main", "I need an SEO helper", _events(events))
    types = [e["type"] for e in events]

    # No premature proposal of any kind
    assert "suggest_create" not in types
    assert "proposal" not in types and "propose_invite" not in types
    # Instead it clarifies via the answer path (Arslan's voice)
    assert "stream_start" in types and "stream_end" in types
    assert all(e.get("source") != "spawn" for e in events if e["type"] == "stream_start")
    assert "clarifying questions" in captured["system"]
    # the gathering phase is pinned, carrying the accumulated slots
    p = await phase_service.get_pending("main")
    assert p is not None and p["phase"] == "gathering"
    slots = await phase_service.get_gathered_slots("main")
    assert slots.get("domain") == "marketing.seo"
    assert slots.get("capability") is None


@pytest.mark.asyncio
async def test_route_intent_during_gather_suppressed(maker, monkeypatch):
    """With an active `gathering` phase, a router action="route" follow-up must be
    diverted to clarify (NOT dispatched) — same suppression as the clarifying phase."""
    from server.orchestrator import arslan, router, tool_loop

    # Arrange: an active gathering phase with a partial slot set.
    await phase_service.set_gathering(
        "main",
        {"domain": "marketing.seo", "capability": None,
         "first_task": None, "recurrence": None},
    )

    async def _fake_route(conv, msg):
        return router.RouterResult(action="route", spawn_id=7, task_brief="audit keywords")

    monkeypatch.setattr(arslan.router, "route", _fake_route)

    dispatched = []

    async def _spy_dispatch(*args, **kwargs):
        dispatched.append((args, kwargs))

    monkeypatch.setattr(arslan, "_dispatch_spawn", _spy_dispatch)

    captured = {}

    class _A:
        async def chat_stream(self, system, user, history=None):
            captured["system"] = system
            for piece in ["Which ", "site?"]:
                yield piece

    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _A())

    events = []
    await arslan.handle_user_message("main", "the SEO one", _events(events))

    # Suppressed: no dispatch, no routing/spawn frames; clarify stream produced.
    assert dispatched == []
    types = [e["type"] for e in events]
    assert "routing" not in types and "spawn_meta" not in types
    assert "stream_start" in types and "stream_end" in types
    assert all(e.get("source") != "spawn" for e in events if e["type"] == "stream_start")
    assert "clarifying questions" in captured["system"]

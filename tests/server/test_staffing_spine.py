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


# All four slots filled → is_ready True → the ready branch (B4 match-and-propose) runs.
_READY_SLOTS = {
    "domain": "marketing.seo",
    "capability": "seo-audit",
    "first_task": "audit acme.com keywords",
    "recurrence": True,
}


async def _ready_extract(history_text):
    return dict(_READY_SLOTS)


def _stub_ready_route(monkeypatch, arslan, router):
    """Make the router signal a create-intent with a draft, so the spine reaches
    the staffing slot gate. _ready_extract then fills all 4 slots → ready branch."""
    async def _fake_route(conv, msg):
        return router.RouterResult(
            action="suggest_create",
            suggested_spawn={"name": "seo-helper", "domain": "marketing.seo",
                             "capabilities": ["seo-audit"]},
            task_brief="audit acme.com keywords",
        )
    monkeypatch.setattr(arslan.router, "route", _fake_route)
    monkeypatch.setattr(arslan.staffing_gather, "extract_slots", _ready_extract)


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


# ---------------------------------------------------------------------------
# Part 2 (B4): match-and-propose 3 bands + propose_staffing frame + one-off gate.
# ---------------------------------------------------------------------------

from server.ws import protocol


def test_propose_staffing_frame_shape():
    f = protocol.propose_staffing(
        candidates=[{"spawn_id": 1, "name": "a", "score": 0.6, "why": "x"}],
        create_draft={"name": "n", "domain": "a.b", "capabilities": ["c"]})
    assert f["type"] == "propose_staffing"
    assert f["candidates"][0]["spawn_id"] == 1
    assert f["create_draft"]["name"] == "n"


@pytest.mark.asyncio
async def test_ready_strong_match_emits_propose_invite(maker, monkeypatch):
    """Ready slots + a single strong match → propose_invite (NOT suggest_create / picker)."""
    from server.orchestrator import arslan, router

    _stub_ready_route(monkeypatch, arslan, router)

    async def _fake_score(need, spawns):
        return [{"spawn_id": 7, "name": "seo-auditor", "score": 0.95, "why": "domain 1.0, coverage 0.9"}]

    monkeypatch.setattr(arslan.spawn_match_service, "score_spawns", _fake_score)
    monkeypatch.setattr(arslan.spawn_match_service, "classify_band",
                        lambda ranked: ("invite_one",
                                        {"spawn_id": 7, "name": "seo-auditor", "why": "strong"}))
    monkeypatch.setattr(arslan.equipment_service, "curate", _fake_curate)

    events = []
    await arslan.handle_user_message("main", "I need an SEO auditor", _events(events))
    types = [e["type"] for e in events]

    assert "propose_invite" in types
    assert "suggest_create" not in types and "propose_staffing" not in types
    inv = next(e for e in events if e["type"] == "propose_invite")
    assert inv["spawn_id"] == 7


@pytest.mark.asyncio
async def test_ready_ambiguous_emits_propose_staffing(maker, monkeypatch):
    """Ready slots + two comparable mids → propose_staffing with both candidates + a create_draft."""
    from server.orchestrator import arslan, router

    _stub_ready_route(monkeypatch, arslan, router)

    cands = [
        {"spawn_id": 7, "name": "seo-auditor", "score": 0.6, "why": "domain 1.0, coverage 0.3"},
        {"spawn_id": 9, "name": "seo-writer", "score": 0.55, "why": "domain 1.0, coverage 0.25"},
    ]

    async def _fake_score(need, spawns):
        return cands

    monkeypatch.setattr(arslan.spawn_match_service, "score_spawns", _fake_score)
    monkeypatch.setattr(arslan.spawn_match_service, "classify_band",
                        lambda ranked: ("picker", {"candidates": cands}))
    monkeypatch.setattr(arslan.equipment_service, "curate", _fake_curate)

    async def _fake_draft(description, *, previous=None):
        return {"name": "seo-helper", "domain": "marketing.seo",
                "capabilities": ["seo-audit"], "persona_role": "SEO analyst",
                "tools": [], "skills": [], "mcps": [], "gaps": []}

    monkeypatch.setattr(arslan.spawn_drafter, "draft_from_text", _fake_draft)

    captured = {}

    async def _fake_equipment(spawn_id, *, session=None):
        captured.setdefault("ids", []).append(spawn_id)
        return {"toolsets": [{"key": f"ts_{spawn_id}"}], "skills": [{"key": f"sk_{spawn_id}"}]}

    monkeypatch.setattr(arslan.registry_service, "equipment_for_spawn", _fake_equipment)

    events = []
    await arslan.handle_user_message("main", "I need SEO help", _events(events))
    types = [e["type"] for e in events]

    assert "propose_staffing" in types
    assert "suggest_create" not in types and "propose_invite" not in types
    frame = next(e for e in events if e["type"] == "propose_staffing")
    assert {c["spawn_id"] for c in frame["candidates"]} == {7, 9}
    assert frame["create_draft"]["name"] == "seo-helper"
    # near-match equipment folded into the create draft's seed
    assert "ts_7" in frame["create_draft"]["tools"] and "ts_9" in frame["create_draft"]["tools"]
    assert "sk_7" in frame["create_draft"]["skills"]


@pytest.mark.asyncio
async def test_ready_no_match_emits_suggest_create_fused(maker, monkeypatch):
    """Ready slots + all low scores → suggest_create; draft carries equipment and, when
    near-matches exist, their equipment is folded into the create draft's seed."""
    from server.orchestrator import arslan, router

    _stub_ready_route(monkeypatch, arslan, router)

    near = [{"spawn_id": 7, "name": "seo-auditor", "score": 0.35, "why": "domain 0.5, coverage 0.1"}]

    async def _fake_score(need, spawns):
        return near

    monkeypatch.setattr(arslan.spawn_match_service, "score_spawns", _fake_score)
    monkeypatch.setattr(arslan.spawn_match_service, "classify_band",
                        lambda ranked: ("create", {}))
    monkeypatch.setattr(arslan.equipment_service, "curate", _fake_curate)

    async def _fake_draft(description, *, previous=None):
        return {"name": "seo-helper", "domain": "marketing.seo",
                "capabilities": ["seo-audit"], "persona_role": "SEO analyst",
                "tools": ["web_search"], "skills": ["seo-audit-skill"], "mcps": [], "gaps": []}

    monkeypatch.setattr(arslan.spawn_drafter, "draft_from_text", _fake_draft)

    async def _fake_equipment(spawn_id, *, session=None):
        return {"toolsets": [{"key": "ts_near"}, {"key": "mcp_5"}], "skills": [{"key": "sk_near"}]}

    monkeypatch.setattr(arslan.registry_service, "equipment_for_spawn", _fake_equipment)

    events = []
    await arslan.handle_user_message("main", "I need a fresh SEO agent", _events(events))
    types = [e["type"] for e in events]

    assert "suggest_create" in types
    assert "propose_invite" not in types and "propose_staffing" not in types
    sc = next(e for e in events if e["type"] == "suggest_create")
    draft = sc["draft"]
    # base equipment from the drafter
    assert "web_search" in draft["tools"] and "seo-audit-skill" in draft["skills"]
    # near-match equipment folded in (mcp_* routed to mcps, kind="toolset")
    assert "ts_near" in draft["tools"] and "sk_near" in draft["skills"]
    assert "mcp_5" in draft["mcps"]
    # task_brief carried from the gathered first_task slot
    assert sc["task_brief"] == "audit acme.com keywords"


@pytest.mark.asyncio
async def test_ready_one_off_does_not_staff(maker, monkeypatch):
    """recurrence=False (explicit one-off) → never staffs: no propose_invite /
    propose_staffing / suggest_create. The first_task is handled once (answer path)."""
    from server.orchestrator import arslan, router, tool_loop

    async def _fake_route(conv, msg):
        return router.RouterResult(
            action="suggest_create",
            suggested_spawn={"name": "seo-helper", "domain": "marketing.seo"},
            task_brief="audit acme.com once",
        )

    async def _one_off_extract(history_text):
        return {"domain": "marketing.seo", "capability": "seo-audit",
                "first_task": "audit acme.com once", "recurrence": False}

    monkeypatch.setattr(arslan.router, "route", _fake_route)
    monkeypatch.setattr(arslan.staffing_gather, "extract_slots", _one_off_extract)
    monkeypatch.setattr(arslan.equipment_service, "curate", _fake_curate)

    scored = []

    async def _spy_score(need, spawns):
        scored.append(need)
        return []

    monkeypatch.setattr(arslan.spawn_match_service, "score_spawns", _spy_score)

    class _A:
        async def chat_stream(self, system, user, history=None):
            for piece in ["Done", "."]:
                yield piece

    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: _A())

    events = []
    await arslan.handle_user_message("main", "just audit acme.com this once", _events(events))
    types = [e["type"] for e in events]

    # Never staffs
    assert "propose_invite" not in types
    assert "propose_staffing" not in types
    assert "suggest_create" not in types
    # Did not even score existing spawns
    assert scored == []
    # Instead, handled once via the answer path
    assert "stream_start" in types and "stream_end" in types

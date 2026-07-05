"""Orchestration loop: answer / route / suggest_create + fact saving."""
import anyio
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import ArslanMessage, Base, Spawn, UserFact


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'loop.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with m() as s:
            s.add(
                Spawn(
                    id=7,
                    name="beauty-guru",
                    domain_category="content-creator",
                    capabilities=["content-generation"],
                    system_prompt="You are a beauty expert.",
                )
            )
            await s.commit()

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
    return m


def _events(collector):
    return lambda ev: collector.append(ev)


async def _fake_noop(): pass
async def _fake_list(): return []


async def _force_named(_msg, _sid):
    # Boundary component 2 sends UNNAMED (inferred) routes to doer-first (answer). These route
    # tests exercise the routing/dispatch MECHANICS, so force the explicit-naming path; naming
    # detection itself is covered in test_boundary_doer_first.
    return True


async def _fake_curate(need):
    """Hermetic stub for equipment_service.curate (no outbound LLM call)."""
    return {"toolsets": [], "skills": [], "mcps": [], "gaps": []}


async def _ready_slots(history_text):
    """Hermetic stub for staffing_gather.extract_slots returning a READY slot set —
    drives the spine's ready path (match-and-propose / suggest_create card)."""
    return {"domain": "x.y", "capability": "do-x", "first_task": "run x", "recurrence": True}


class _LLMResp:
    """Native LLMResponse stub: separate content (prose) + tool_calls (structured)."""
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


def _tc(name, args):
    return {"id": "c1", "type": "function", "function": {"name": name, "arguments": args}}


class _NativeAdapter:
    """chat()-based stub (Arslan's answer path uses run_native → a.chat, not chat_stream).
    Returns queued LLMResponses in order; optionally records the system/user it saw."""
    def __init__(self, replies, capture=None):
        self._it = iter(replies)
        self.capture = capture

    async def chat(self, system, user, history=None, tools=None, temperature=0.7):
        if self.capture is not None:
            self.capture["system"] = system
            self.capture["user"] = user
        return next(self._it)


@pytest.mark.asyncio
async def test_answer_path_streams_and_persists(maker, monkeypatch):
    from server.orchestrator import arslan, router

    async def _fake_route(conv, msg):
        return router.RouterResult(action="answer", new_facts=[{"content": "likes brevity"}])

    monkeypatch.setattr(arslan.router, "route", _fake_route)

    captured = {}

    from server.orchestrator import tool_loop

    monkeypatch.setattr(tool_loop, "_get_adapter",
                        lambda: _NativeAdapter([_LLMResp(content="Hi there")], capture=captured))

    events = []
    await arslan.handle_user_message("main", "hello", _events(events))

    types = [e["type"] for e in events]
    assert "stream_start" in types and "stream_end" in types
    assert any(e["type"] == "fact_saved" and "brevity" in e["content"] for e in events)
    # plain answer must NOT carry the clarify addendum (distinguishes it from clarify)
    assert "clarifying questions" not in captured["system"]

    async with db_session.AsyncSessionLocal() as s:
        ams = (await s.execute(select(ArslanMessage).order_by(ArslanMessage.id))).scalars().all()
        facts = (await s.execute(select(UserFact))).scalars().all()
    assert [a.role for a in ams] == ["user", "arslan"]
    assert ams[1].content == "Hi there"
    assert len(facts) == 1


@pytest.mark.asyncio
async def test_arslan_answer_calls_web_tool(maker, monkeypatch):
    # Arslan's answer path runs tool_loop; the model calls web_search, then streams a final answer.
    from server.orchestrator import arslan, router, tool_loop
    from server.registry import executors

    async def _fake_route(conv, msg):
        return router.RouterResult(action="answer")

    monkeypatch.setattr(arslan.router, "route", _fake_route)

    adapter = _NativeAdapter([
        _LLMResp(content="", tool_calls=[_tc("web_search", {"query": "today"})]),
        _LLMResp(content="Fresh info: X happened."),
    ])
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    class _Stub:
        async def execute(self, args):
            return {"ok": True, "results": [{"title": "t", "url": "u"}]}

    monkeypatch.setitem(executors.EXECUTORS, "web_search", _Stub())

    events = []
    await arslan.handle_user_message("main", "what happened today?", _events(events))
    types = [e["type"] for e in events]
    assert "tool_call" in types and "tool_result" in types
    streamed = "".join(e["content"] for e in events if e["type"] == "stream_chunk")
    assert "Fresh info: X happened." in streamed
    assert "stream_end" in types


@pytest.mark.asyncio
async def test_arslan_answer_plain_no_tool(maker, monkeypatch):
    from server.orchestrator import arslan, router, tool_loop

    async def _fake_route(conv, msg):
        return router.RouterResult(action="answer")

    monkeypatch.setattr(arslan.router, "route", _fake_route)

    monkeypatch.setattr(tool_loop, "_get_adapter",
                        lambda: _NativeAdapter([_LLMResp(content="just a friendly reply")]))

    events = []
    await arslan.handle_user_message("main", "哈喽", _events(events))
    types = [e["type"] for e in events]
    assert "tool_call" not in types
    streamed = "".join(e["content"] for e in events if e["type"] == "stream_chunk")
    assert "just a friendly reply" in streamed


@pytest.mark.asyncio
async def test_clarify_streams_arslan_answer_and_does_not_create_or_dispatch(maker, monkeypatch):
    from server.orchestrator import arslan, router

    async def _fake_route(conv, msg):
        return router.RouterResult(action="clarify")

    monkeypatch.setattr(arslan.router, "route", _fake_route)

    captured = {}

    from server.orchestrator import tool_loop

    monkeypatch.setattr(tool_loop, "_get_adapter",
                        lambda: _NativeAdapter([_LLMResp(content="What topic?")], capture=captured))

    events = []
    await arslan.handle_user_message("main", "research stuff", _events(events))
    types = [e["type"] for e in events]
    assert "stream_start" in types and "stream_end" in types
    # speaks as Arslan (never source "spawn"); creates/dispatches nothing
    assert all(e.get("source") != "spawn" for e in events if e["type"] == "stream_start")
    assert "routing" not in types and "spawn_created" not in types and "spawn_meta" not in types
    # genuinely guards the clarify branch: the addendum must reach the system prompt.
    # If the clarify branch were removed (falling into the plain answer path), this fails.
    assert "clarifying questions" in captured["system"]
    assert "under-specified" in captured["system"]


@pytest.mark.asyncio
async def test_answer_path_grounds_real_roster_and_guards_fabrication(maker, monkeypatch):
    """Anti-fabrication: the answer system prompt must inject the REAL spawn roster
    and instruct the model not to invent spawns/tools nor present user-facts as its
    own services. Regression for the '哈喽 -> fake Aletheia/Huan/tools' bug."""
    from server.orchestrator import arslan, router

    async def _fake_route(conv, msg):
        return router.RouterResult(action="answer")

    monkeypatch.setattr(arslan.router, "route", _fake_route)

    captured = {}

    from server.orchestrator import tool_loop

    monkeypatch.setattr(tool_loop, "_get_adapter",
                        lambda: _NativeAdapter([_LLMResp(content="hi")], capture=captured))

    await arslan.handle_user_message("main", "哈喽", _events([]))

    sys_prompt = captured["system"]
    # the actual roster (seeded spawn name) must be grounded in the prompt
    assert "beauty-guru" in sys_prompt
    # explicit guard against inventing teammates/tools
    low = sys_prompt.lower()
    assert "invent" in low or "fabricat" in low or "make up" in low


@pytest.mark.asyncio
async def test_route_path_emits_routing_and_dispatches(maker, monkeypatch):
    from server.orchestrator import arslan, router
    from server.services import roster_service

    async def _fake_route(conv, msg):
        return router.RouterResult(action="route", spawn_id=7, task_brief="draft posts")

    monkeypatch.setattr(arslan.router, "route", _fake_route)

    async def _fake_dispatch(conv, *, spawn_id, task_brief, on_chunk=None, on_event=None, prior_output=None, instruction=None, **kw):
        for piece in ["P1", "P2"]:
            if on_chunk:
                on_chunk(piece)
        return {
            "full_output": "P1P2",
            "spawn_name": "beauty-guru",
            "summary_message_id": 9,
            "assistant_message_id": 8,
            "escalation": None,
        }

    # Spawn 7 is already in the roster → route dispatches directly (no invite card).
    # Insert membership via the REAL join before stubbing it below.
    await roster_service.join("main", 7, via="invited")

    monkeypatch.setattr(arslan.dispatcher, "dispatch", _fake_dispatch)
    monkeypatch.setattr(arslan, "_user_named_spawn", _force_named)
    monkeypatch.setattr(roster_service, "join", lambda c, s, *, via: _fake_noop())
    monkeypatch.setattr(roster_service, "list_roster", lambda c: _fake_list())

    events = []
    await arslan.handle_user_message("main", "make posts", _events(events))
    types = [e["type"] for e in events]
    assert "routing" in types
    routing_ev = next(e for e in events if e.get("type") == "routing")
    # spawn name resolved (via dispatcher.get_spawn_name against the seeded spawn 7) before streaming
    assert routing_ev["spawn_name"] == "beauty-guru"
    assert "stream_start" in types and "stream_end" in types


@pytest.mark.asyncio
async def test_dispatch_to_missing_spawn_emits_error_not_crash(maker, monkeypatch):
    """Defense-in-depth at the dispatch chokepoint: if a spawn_id reaches
    _dispatch_spawn but no longer exists (e.g. deleted mid-conversation, or a stale
    id from any non-route entry point), dispatch must emit a recoverable error frame
    and return — NEVER call RunRecorder.start() with a dangling FK (IntegrityError)."""
    from server.orchestrator import arslan
    from server.services import run_recorder
    from server.db.models import Run

    # Guard against a regression where the recorder is reached anyway.
    monkeypatch.setattr(run_recorder, "schedule_scoring", lambda rid: None)

    events = []
    # spawn 999 does not exist (only id=7 is seeded)
    await arslan._dispatch_spawn("main", 999, "do x", _events(events), user_message="do x")

    types = [e["type"] for e in events]
    assert "error" in types, f"expected an error frame, got {types}"
    err = next(e for e in events if e["type"] == "error")
    assert err.get("recoverable") is True
    # crucially: no routing/stream frames and no Run row was written
    assert "routing" not in types
    async with db_session.AsyncSessionLocal() as s:
        runs = (await s.execute(select(Run))).scalars().all()
    assert runs == []


@pytest.mark.asyncio
async def test_suggest_create_emits_card(maker, monkeypatch):
    from server.orchestrator import arslan, router

    draft = {
        "name": "translator",
        "domain": "personal-assistant.translator",
        "capabilities": ["translation"],
    }

    async def _fake_route(conv, msg):
        return router.RouterResult(
            action="suggest_create", suggested_spawn=draft, task_brief="translate this doc"
        )

    async def _fake_draft(description, *, previous=None):
        # B4 create-band fuses an LLM-drafted spawn; return the draft + equipment keys.
        return {**draft, "tools": [], "skills": [], "mcps": [], "gaps": []}

    monkeypatch.setattr(arslan.router, "route", _fake_route)
    monkeypatch.setattr(arslan.equipment_service, "curate", _fake_curate)
    monkeypatch.setattr(arslan.staffing_gather, "extract_slots", _ready_slots)
    monkeypatch.setattr(arslan.spawn_drafter, "draft_from_text", _fake_draft)

    events = []
    await arslan.handle_user_message("main", "translate things often", _events(events))
    # B4: no existing spawns → create band → suggest_create with the fused draft.
    sc = next(e for e in events if e["type"] == "suggest_create")
    assert sc["draft"]["name"] == "translator"
    assert sc["draft"]["capabilities"] == ["translation"]


@pytest.mark.asyncio
async def test_suggest_create_carries_task_brief_and_overlaps(maker, monkeypatch):
    from server.orchestrator import arslan, router

    draft = {"name": "stock-helper", "domain": "finance.equities", "capabilities": ["equity-research"]}
    overlaps = {"spawn_id": 3, "name": "股小助", "axes": ["a"]}

    async def _fake_route(conv, msg):
        return router.RouterResult(
            action="suggest_create",
            suggested_spawn=draft,
            task_brief="analyze TSLA",
            overlaps=overlaps,
        )

    async def _fake_draft(description, *, previous=None):
        return {**draft, "tools": [], "skills": [], "mcps": [], "gaps": []}

    monkeypatch.setattr(arslan.router, "route", _fake_route)
    monkeypatch.setattr(arslan.equipment_service, "curate", _fake_curate)
    monkeypatch.setattr(arslan.staffing_gather, "extract_slots", _ready_slots)
    monkeypatch.setattr(arslan.spawn_drafter, "draft_from_text", _fake_draft)

    events = []
    await arslan.handle_user_message("main", "look at TSLA", _events(events))
    sc = next(e for e in events if e["type"] == "suggest_create")
    assert sc["draft"]["name"] == "stock-helper"
    # B4: task_brief now carries the gathered first_task slot (not the router brief).
    assert sc["task_brief"] == "run x"
    # No existing spawn matches by name/domain → the router's overlaps passes through.
    assert sc["overlaps"] == overlaps


@pytest.mark.asyncio
async def test_suggest_create_injects_overlap_for_existing_same_name_spawn(maker, monkeypatch):
    from server.orchestrator import arslan, router

    # seed a spawn whose name matches the draft; router will miss the overlap
    async with db_session.AsyncSessionLocal() as s:
        sp = Spawn(
            name="数据研究",
            domain_category="data-analysis",
            domain_subcategory="internet",
            capabilities=["research"],
            system_prompt="You research data.",
        )
        s.add(sp)
        await s.commit()
        seeded_id = sp.id

    draft = {"name": "数据研究", "domain": "data-analysis.report", "capabilities": ["research"]}

    async def _fake_route(conv, msg):
        return router.RouterResult(
            action="suggest_create",
            suggested_spawn=draft,
            task_brief="analyze internet data",
            overlaps=None,  # LLM missed it; deterministic check must inject it
        )

    async def _fake_draft(description, *, previous=None):
        return {**draft, "tools": [], "skills": [], "mcps": [], "gaps": []}

    monkeypatch.setattr(arslan.router, "route", _fake_route)
    monkeypatch.setattr(arslan.equipment_service, "curate", _fake_curate)
    monkeypatch.setattr(arslan.staffing_gather, "extract_slots", _ready_slots)
    monkeypatch.setattr(arslan.spawn_drafter, "draft_from_text", _fake_draft)

    events = []
    await arslan.handle_user_message("main", "research internet data", _events(events))
    sc = next(e for e in events if e["type"] == "suggest_create")
    assert sc["overlaps"] is not None
    assert sc["overlaps"]["spawn_id"] == seeded_id


@pytest.mark.asyncio
async def test_suggest_create_leaves_overlaps_when_no_existing_match(maker, monkeypatch):
    from server.orchestrator import arslan, router

    # seeded spawn (id=7, beauty-guru) does not match this draft by name or full domain
    draft = {"name": "translator", "domain": "personal-assistant.translator", "capabilities": ["translation"]}

    async def _fake_route(conv, msg):
        return router.RouterResult(
            action="suggest_create",
            suggested_spawn=draft,
            task_brief="translate",
            overlaps=None,
        )

    async def _fake_draft(description, *, previous=None):
        return {**draft, "tools": [], "skills": [], "mcps": [], "gaps": []}

    monkeypatch.setattr(arslan.router, "route", _fake_route)
    monkeypatch.setattr(arslan.equipment_service, "curate", _fake_curate)
    monkeypatch.setattr(arslan.staffing_gather, "extract_slots", _ready_slots)
    monkeypatch.setattr(arslan.spawn_drafter, "draft_from_text", _fake_draft)

    events = []
    await arslan.handle_user_message("main", "translate things", _events(events))
    sc = next(e for e in events if e["type"] == "suggest_create")
    assert sc["overlaps"] is None


@pytest.mark.asyncio
async def test_route_path_emits_spawn_meta(maker, monkeypatch):
    from server.orchestrator import arslan, router
    from server.services import roster_service

    async def _fake_route(conv, msg):
        return router.RouterResult(action="route", spawn_id=7, task_brief="do X")

    monkeypatch.setattr(arslan.router, "route", _fake_route)

    async def _fake_dispatch(conv, *, spawn_id, task_brief, on_chunk=None, on_event=None, prior_output=None, instruction=None, **kw):
        if on_chunk:
            on_chunk("P1")
        return {
            "full_output": "P1",
            "spawn_name": "beauty-guru",
            "summary_message_id": 9,
            "assistant_message_id": 8,
            "escalation": None,
        }

    monkeypatch.setattr(arslan.dispatcher, "dispatch", _fake_dispatch)
    monkeypatch.setattr(arslan, "_user_named_spawn", _force_named)
    # Spawn 7 is already in the roster → route dispatches directly (no invite card).
    await roster_service.join("main", 7, via="invited")

    events = []
    await arslan.handle_user_message("main", "make posts", _events(events))
    meta = next(e for e in events if e["type"] == "spawn_meta")
    assert meta["spawn_id"] == 7
    assert meta["task_brief"] == "do X"
    assert isinstance(meta["assistant_message_id"], int)
    end = next(e for e in events if e["type"] == "stream_end")
    assert meta["arslan_message_id"] == end["message_id"]


@pytest.mark.asyncio
async def test_arslan_answer_prompt_has_web_tool_guidance(maker, monkeypatch):
    # Regression: Arslan's answer-path system prompt must bind "unsure about something
    # current" → "search" (not → ask/fabricate), or the model narrates instead of calling
    # the tool. Asserts the guidance + the reconciliation with anti-fabrication are present.
    from server.orchestrator import arslan, router, tool_loop

    async def _fake_route(conv, msg):
        return router.RouterResult(action="answer")

    monkeypatch.setattr(arslan.router, "route", _fake_route)

    captured = {}

    monkeypatch.setattr(tool_loop, "_get_adapter",
                        lambda: _NativeAdapter([_LLMResp(content="ok")], capture=captured))

    await arslan.handle_user_message("main", "今天的新闻", _events([]))
    sys = captured["system"]
    assert "web_search" in sys
    assert "MUST" in sys                       # "you MUST actually CALL web_search"
    assert "INSTEAD of fabricating" in sys     # reconciled with anti-fabrication
    assert "ACT, don't narrate" in sys         # forbid ending a turn with "I'll search"
    assert "Current date/time" in sys          # current time injected → no search needed for 'now'

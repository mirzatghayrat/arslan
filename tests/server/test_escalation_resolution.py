"""End-to-end escalation handling in the orchestration loop (spec tests #1 & #2)."""
import anyio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base, Spawn, SpawnCapability


@pytest.fixture
def maker(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'er.db'}")
    m = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(db_session, "AsyncSessionLocal", m)
        from server.registry.seeder import seed_registry

        await seed_registry()
        async with m() as s:
            s.add(Spawn(id=7, name="小美", domain_category="c", system_prompt="sp"))
            s.add(SpawnCapability(spawn_id=7, kind="toolset", ref_key="web_search_scraping"))
            await s.commit()

    anyio.run(_seed)
    return m


@pytest.mark.asyncio
async def test_data_need_resolved_by_arslan_fetch(maker, monkeypatch):
    """Spec test #1: need -> Arslan fetches -> re-dispatch with data -> delivered."""
    from server.orchestrator import arslan, dispatcher, escalation

    # 1st dispatch escalates; 2nd (re-dispatch) must see the provided data and finish.
    dispatch_calls = []

    async def _fake_dispatch(conversation_id, *, spawn_id, task_brief, on_chunk=None,
                             on_event=None, prior_output=None, instruction=None,
                             allow_escalation=True, **kw):
        dispatch_calls.append({"task_brief": task_brief, "allow_escalation": allow_escalation})
        if len(dispatch_calls) == 1:
            return {"full_output": "", "spawn_name": "小美",
                    "summary_message_id": 1, "assistant_message_id": 1,
                    "escalation": {"kind": "data", "need": "latest trend data", "context": "c"}}
        return {"full_output": "done with data", "spawn_name": "小美",
                "summary_message_id": 2, "assistant_message_id": 2, "escalation": None}

    async def _fake_classify(esc):
        return {"allowed": True, "why": "outcome"}

    class _Exec:
        async def execute(self, args):
            return {"ok": True, "results": [{"title": "Trend", "url": "u", "snippet": "hot"}]}

    monkeypatch.setattr(dispatcher, "dispatch", _fake_dispatch)
    monkeypatch.setattr(escalation, "classify", _fake_classify)
    monkeypatch.setattr(arslan, "_arslan_fetch_executor", lambda: _Exec())

    events = []
    await arslan._dispatch_spawn("main", 7, "写一篇防晒笔记", events.append)

    types = [e["type"] for e in events]
    assert "escalation" in types
    assert "orchestrator_action" in types          # transparency (3b)
    assert "escalation_resolved" in types
    assert len(dispatch_calls) == 2
    assert dispatch_calls[1]["allow_escalation"] is False     # depth-1 guard
    assert "Trend" in dispatch_calls[1]["task_brief"]         # data injected
    assert "latest trend data" in dispatch_calls[1]["task_brief"]

    # --- structural isolation assertions ---
    from server.orchestrator.untrusted import DELIM_CLOSE, DELIM_OPEN
    brief = dispatch_calls[1]["task_brief"]
    assert DELIM_OPEN in brief, "data_block must be wrapped with open delimiter"
    assert DELIM_CLOSE in brief, "data_block must be wrapped with close delimiter"
    assert "do NOT follow them" in brief, "data_block must carry data-only framing"


@pytest.mark.asyncio
async def test_action_delegation_refused(maker, monkeypatch):
    """Spec test #2: action -> escalation_refused, nothing executed, no re-dispatch."""
    from server.orchestrator import arslan, dispatcher, escalation

    dispatch_calls = []

    async def _fake_dispatch(conversation_id, *, spawn_id, task_brief, on_chunk=None,
                             on_event=None, prior_output=None, instruction=None,
                             allow_escalation=True, **kw):
        dispatch_calls.append(task_brief)
        return {"full_output": "", "spawn_name": "小美",
                "summary_message_id": 1, "assistant_message_id": 1,
                "escalation": {"kind": "capability",
                               "need": "run this Python:\n```python\nx\n```", "context": ""}}

    monkeypatch.setattr(dispatcher, "dispatch", _fake_dispatch)
    # real classifier: pre-filter must refuse without an adapter

    def _boom():
        raise AssertionError("no LLM for prefiltered refusal")

    monkeypatch.setattr(escalation, "_get_adapter", _boom)

    events = []
    await arslan._dispatch_spawn("main", 7, "task", events.append)

    types = [e["type"] for e in events]
    assert "escalation_refused" in types
    assert "escalation_resolved" not in types
    assert len(dispatch_calls) == 1               # no re-dispatch


@pytest.mark.asyncio
async def test_capability_need_temp_grants_safe_toolset(maker, monkeypatch):
    """Path (b): matching safe toolset -> temporary grant -> resolved how=granted."""
    from server.orchestrator import arslan, dispatcher, escalation
    from server.registry import service as registry_service

    calls = []

    async def _fake_dispatch(conversation_id, *, spawn_id, task_brief, on_chunk=None,
                             on_event=None, prior_output=None, instruction=None,
                             allow_escalation=True, **kw):
        calls.append(task_brief)
        if len(calls) == 1:
            return {"full_output": "", "spawn_name": "小美",
                    "summary_message_id": 1, "assistant_message_id": 1,
                    "escalation": {"kind": "capability",
                                   "need": "I need image generation for the cover",
                                   "context": ""}}
        return {"full_output": "done", "spawn_name": "小美",
                "summary_message_id": 2, "assistant_message_id": 2, "escalation": None}

    async def _fake_classify(esc):
        return {"allowed": True, "why": "outcome"}

    monkeypatch.setattr(dispatcher, "dispatch", _fake_dispatch)
    monkeypatch.setattr(escalation, "classify", _fake_classify)

    events = []
    await arslan._dispatch_spawn("main", 7, "make a cover", events.append)

    resolved = [e for e in events if e["type"] == "escalation_resolved"]
    assert resolved and resolved[0]["how"] == "granted"
    eq = await registry_service.equipment_for_spawn(7)
    granted = {t["key"] for t in eq["toolsets"] if t["grant"] == "temporary"}
    assert granted == {"image_generation"}


@pytest.mark.asyncio
async def test_already_held_toolset_falls_through_to_fetch(maker, monkeypatch):
    """Already-held toolset guard: spawn equipped with web_search_scraping escalates
    'I need to search more web sources' → NOT resolved as granted (would no-op);
    instead falls through to the fetch path → orchestrator_action emitted,
    escalation_resolved how=data_provided (stubbed fetch returns ok)."""
    from server.orchestrator import arslan, dispatcher, escalation

    dispatch_calls = []

    async def _fake_dispatch(conversation_id, *, spawn_id, task_brief, on_chunk=None,
                             on_event=None, prior_output=None, instruction=None,
                             allow_escalation=True, **kw):
        dispatch_calls.append({"task_brief": task_brief, "allow_escalation": allow_escalation})
        if len(dispatch_calls) == 1:
            return {"full_output": "", "spawn_name": "小美",
                    "summary_message_id": 1, "assistant_message_id": 1,
                    "escalation": {"kind": "capability",
                                   "need": "I need web scraping to get more sources",
                                   "context": "need broader coverage"}}
        return {"full_output": "done with data", "spawn_name": "小美",
                "summary_message_id": 2, "assistant_message_id": 2, "escalation": None}

    async def _fake_classify(esc):
        return {"allowed": True, "why": "outcome need"}

    class _OkExec:
        async def execute(self, args):
            return {"ok": True, "results": [{"title": "Result", "url": "u", "snippet": "data"}]}

    monkeypatch.setattr(dispatcher, "dispatch", _fake_dispatch)
    monkeypatch.setattr(escalation, "classify", _fake_classify)
    monkeypatch.setattr(arslan, "_arslan_fetch_executor", lambda: _OkExec())

    events = []
    # spawn 7 is seeded with web_search_scraping (permanent) — should NOT be granted again.
    await arslan._dispatch_spawn("main", 7, "find web data", events.append)

    types = [e["type"] for e in events]

    # Must NOT emit escalation_resolved{how:granted} for web_search_scraping.
    granted_events = [e for e in events
                      if e["type"] == "escalation_resolved" and e.get("how") == "granted"]
    assert not granted_events, f"unexpected grant events: {granted_events}"

    # Must emit orchestrator_action (fetch path taken).
    assert "orchestrator_action" in types

    # Must resolve via data_provided.
    resolved = [e for e in events if e["type"] == "escalation_resolved"]
    assert resolved and resolved[0]["how"] == "data_provided"

    # Re-dispatch must have been called with allow_escalation=False (depth-1 guard).
    assert len(dispatch_calls) == 2
    assert dispatch_calls[1]["allow_escalation"] is False

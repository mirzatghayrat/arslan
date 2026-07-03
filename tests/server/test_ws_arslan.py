"""/ws/arslan endpoint: answer streaming, routing, suggest+confirm create."""
import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
import server.orchestrator.arslan as arslan_mod
import server.orchestrator.dispatcher as dispatcher_mod
from server.db.models import Base, Spawn


class _FakeAdapter:
    """Deterministic streaming adapter so spawn dispatch runs against the test DB."""

    def __init__(self, text: str = "OK"):
        self._text = text
        self.captured_user: str | None = None

    async def chat_stream(self, system, user, history=None):  # noqa: ANN001
        self.captured_user = user
        yield self._text


def _stub_spawn_adapter(monkeypatch, text: str = "OK") -> _FakeAdapter:
    adapter = _FakeAdapter(text)
    monkeypatch.setattr(dispatcher_mod, "_get_adapter", lambda: adapter)
    return adapter


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))
    import importlib

    import server.config as config

    importlib.reload(config)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'wsar.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with maker() as s:
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
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.main import create_app

    return TestClient(create_app())


def test_answer_turn_streams(app_client, monkeypatch):
    # Stub the orchestration loop to a deterministic answer.
    async def _fake_handle(conv, msg, emit, *, attached_context=None, confirm_command=None):
        emit({"type": "stream_start", "source": "arslan"})
        emit({"type": "stream_chunk", "content": "Hello"})
        emit({"type": "stream_end", "message_id": 1})

    monkeypatch.setattr(arslan_mod, "handle_user_message", _fake_handle)

    with app_client.websocket_connect("/ws/arslan/main") as ws:
        hist = ws.receive_json()
        assert hist["type"] == "history"
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "user_message", "content": "hi"})
        assert ws.receive_json()["type"] == "stream_start"
        assert ws.receive_json() == {"type": "stream_chunk", "content": "Hello"}
        assert ws.receive_json()["type"] == "stream_end"


def test_confirm_create_makes_spawn(app_client):
    draft = {
        "name": "translator",
        "domain": "personal-assistant.translator",
        "capabilities": ["qa-interaction"],
        "persona_role": "translator",
        "persona_tone": "precise",
    }
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "confirm_create", "draft": draft})
        created = ws.receive_json()
        assert created["type"] == "spawn_created"
        assert created["spawn_name"] == "translator"
        _drain_roster_after_created(ws)  # drain roster_event + roster_update

    async def _check():
        async with db_session.AsyncSessionLocal() as s:
            rows = (await s.execute(select(Spawn).where(Spawn.name == "translator"))).scalars().all()
            return rows

    assert len(anyio.run(_check)) == 1


def test_confirm_create_dedups_duplicate_name(app_client):
    # "beauty-guru" already exists (seeded).
    # OLD behavior (plan Task 6): silently auto-suffixed to beauty-guru-2.
    # NEW behavior (plan Task 6, pairwise dedup rule): collision detected at create time;
    # server re-emits suggest_create with overlaps so the user sees the overlap card.
    # With differentiation the user can override and get beauty-guru-2.
    draft = {
        "name": "beauty-guru",
        "domain": "content-creator.xiaohongshu",
        "capabilities": [],
        "persona_role": "blogger",
    }
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "confirm_create", "draft": draft})
        frame = ws.receive_json()
        # No differentiation → overlap card re-emitted, NOT created.
        assert frame["type"] == "suggest_create"
        assert frame["overlaps"] is not None and frame["overlaps"]["spawn_id"] == 7

    # With differentiation → auto-suffix still applies (create_spawn_unique).
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({
            "type": "confirm_create",
            "draft": draft,
            "differentiation": "regional market focus",
        })
        created = ws.receive_json()
        assert created["type"] == "spawn_created"
        assert created["spawn_name"] == "beauty-guru-2"
        _drain_roster_after_created(ws)  # drain roster_event + roster_update


def _drain(ws, max_frames: int = 30) -> list[dict]:
    """Collect frames until a stream_end is seen (or budget exhausted)."""
    frames: list[dict] = []
    for _ in range(max_frames):
        f = ws.receive_json()
        frames.append(f)
        if f.get("type") == "stream_end":
            break
    return frames


def _drain_roster_after_created(ws) -> None:
    """After receiving spawn_created, drain the roster frames the server now always emits:
    optionally roster_event("joined", ...) followed by roster_update(...).
    Call this any time a test receives spawn_created and doesn't need the roster frames."""
    f = ws.receive_json()
    if f.get("type") == "roster_event":
        # roster_event is only emitted when newly_joined; consume it then get roster_update
        roster = ws.receive_json()
        assert roster["type"] == "roster_update"
    else:
        # No roster_event, this frame should already be roster_update
        assert f["type"] == "roster_update"


def test_confirm_create_then_executes(app_client, monkeypatch):
    _stub_spawn_adapter(monkeypatch)
    draft = {"name": "eq", "domain": "finance.x", "capabilities": []}
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "confirm_create", "draft": draft, "task_brief": "analyze TSLA"})
        created = ws.receive_json()
        assert created["type"] == "spawn_created"
        frames = _drain(ws)
        types = [f["type"] for f in frames]
        # create THEN execute: a routed spawn turn follows.
        assert "routing" in types
        assert "spawn_meta" in types
        assert "stream_end" in types


def test_confirm_create_domain_collision_no_differentiation(app_client):
    """Unique name but identical full domain (category.subcategory) as an existing spawn
    → confirm_create without differentiation re-emits suggest_create with overlaps,
    creates nothing.

    The seeded spawn has domain_category='content-creator' and no subcategory, so a
    draft with domain='content-creator.xiaohongshu' does NOT trigger the domain check
    (subcategories differ). We seed a second spawn with a subcategory to exercise the
    exact-domain-equality branch in find_overlap.
    """
    # Seed a spawn with full domain content-creator.makeup.
    async def _seed_domain_spawn():
        async with db_session.AsyncSessionLocal() as s:
            s.add(
                Spawn(
                    id=99,
                    name="makeup-artist-pro",
                    domain_category="content-creator",
                    domain_subcategory="makeup",
                    capabilities=[],
                    system_prompt="You are a makeup specialist.",
                )
            )
            await s.commit()

    anyio.run(_seed_domain_spawn)

    # Draft with a unique name but identical full domain content-creator.makeup.
    draft = {
        "name": "totally-new-makeup-agent",
        "domain": "content-creator.makeup",
        "capabilities": ["tutorial-writing"],
        "persona_role": "makeup influencer",
    }

    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "confirm_create", "draft": draft})
        frame = ws.receive_json()
        # Domain collision without differentiation → overlap card re-emitted, NOT created.
        assert frame["type"] == "suggest_create"
        assert frame["overlaps"] is not None
        assert frame["overlaps"]["spawn_id"] == 99

    # Verify nothing was inserted with the new name.
    async def _check():
        async with db_session.AsyncSessionLocal() as s:
            rows = (
                await s.execute(select(Spawn).where(Spawn.name == "totally-new-makeup-agent"))
            ).scalars().all()
            return rows

    assert len(anyio.run(_check)) == 0


def test_confirm_create_without_task_brief_does_not_dispatch(app_client, monkeypatch):
    _stub_spawn_adapter(monkeypatch)
    draft = {"name": "eq", "domain": "finance.x", "capabilities": []}
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({"type": "confirm_create", "draft": draft, "task_brief": ""})
        created = ws.receive_json()
        assert created["type"] == "spawn_created"
        _drain_roster_after_created(ws)  # drain roster_event (newly_joined) + roster_update
        # No dispatch: send a follow-up and prove the very next frame is a routing frame from route_to.
        ws.send_json({"type": "route_to", "spawn_id": 7, "task_brief": "ping"})
        # dispatch_spawn emits roster_event (newly joined) then roster_update then routing
        frames = _drain(ws)
        types = [f["type"] for f in frames]
        assert "routing" in types, f"expected routing in {types}"
        routing_frame = next(f for f in frames if f["type"] == "routing")
        assert routing_frame["spawn_id"] == 7  # this routing is from route_to, not the no-op confirm_create


def test_route_to_existing_dispatches(app_client, monkeypatch):
    _stub_spawn_adapter(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.send_json({"type": "route_to", "spawn_id": 7, "task_brief": "analyze TSLA"})
        frames = _drain(ws)
        assert any(f["type"] == "routing" and f["spawn_id"] == 7 for f in frames)
        assert any(f["type"] == "spawn_meta" for f in frames)


def test_redo_redispatches(app_client, monkeypatch):
    _stub_spawn_adapter(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.send_json({"type": "redo", "spawn_id": 7, "message_id": 1, "task_brief": "do X"})
        frames = _drain(ws)
        assert any(f["type"] == "spawn_meta" for f in frames)


def test_refine_passes_instruction(app_client, monkeypatch):
    from server.db.models import ChatMessage

    adapter = _stub_spawn_adapter(monkeypatch)

    # Seed a prior assistant output so _last_spawn_output returns non-None.
    async def _seed_prior():
        async with db_session.AsyncSessionLocal() as s:
            s.add(ChatMessage(spawn_id=7, role="assistant", content="DULL PRIOR RESULT"))
            await s.commit()

    anyio.run(_seed_prior)

    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.send_json({
            "type": "refine",
            "spawn_id": 7,
            "message_id": 1,
            "task_brief": "do X",
            "instruction": "make it livelier",
        })
        frames = _drain(ws)
        assert any(f["type"] == "spawn_meta" for f in frames)

    # The adapter must have received both the instruction and the seeded prior output.
    assert adapter.captured_user is not None
    assert "make it livelier" in adapter.captured_user
    assert "DULL PRIOR RESULT" in adapter.captured_user


def test_redo_with_bad_spawn_id_is_recoverable(app_client, monkeypatch):
    _stub_spawn_adapter(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        # Malformed: spawn_id is None. Must NOT crash/close the socket.
        ws.send_json({"type": "redo", "spawn_id": None, "task_brief": "x"})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "INVALID_INPUT"
        # Socket still usable: a subsequent valid route_to to seeded spawn 7 routes.
        ws.send_json({"type": "route_to", "spawn_id": 7, "task_brief": "ping"})
        frames = _drain(ws)
        assert any(f["type"] == "routing" and f["spawn_id"] == 7 for f in frames)


def test_to_frame_carries_task_brief_and_overlaps():
    from server.ws.arslan import _to_frame

    frame = _to_frame({
        "type": "suggest_create",
        "draft": {"name": "x"},
        "task_brief": "do X",
        "overlaps": {"spawn_id": 3, "name": "y", "axes": ["a"]},
    })
    assert frame["task_brief"] == "do X"
    assert frame["overlaps"] == {"spawn_id": 3, "name": "y", "axes": ["a"]}


def test_confirm_create_dedups_at_create_time(app_client):
    """A draft whose name collides with an existing spawn (seeded: beauty-guru, id=7)
    must be re-emitted as suggest_create with overlaps rather than created.
    With differentiation= the explicit override, the spawn IS created.
    (plan: Task 6, step 6)
    """
    # 1) Collision draft: server re-emits suggest_create with overlaps, creates nothing.
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({
            "type": "confirm_create",
            "draft": {"name": "beauty-guru", "domain": "content-creator.xiaohongshu"},
            "task_brief": "",
        })
        frame = ws.receive_json()
        assert frame["type"] == "suggest_create"
        assert frame["overlaps"] is not None
        assert frame["overlaps"]["spawn_id"] == 7

    # 2) Explicit differentiation overrides the dedup: spawn is created.
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({
            "type": "confirm_create",
            "draft": {"name": "beauty-guru", "domain": "content-creator.xiaohongshu"},
            "task_brief": "",
            "differentiation": "focus on skincare for Gen Z",
        })
        frame = ws.receive_json()
        assert frame["type"] == "spawn_created"
        _drain_roster_after_created(ws)  # drain roster_event + roster_update


# ---------------------------------------------------------------------------
# _to_frame unit tests — verify protocol builders are the wire-shape authority
# ---------------------------------------------------------------------------

def test_to_frame_escalation_resolved():
    """_to_frame routes escalation_resolved through the protocol builder."""
    from server.ws.arslan import _to_frame
    from server.ws import protocol

    ev = {"type": "escalation_resolved", "spawn_id": 7, "how": "granted", "detail": "image_generation"}
    frame = _to_frame(ev)
    assert frame == protocol.escalation_resolved(7, "granted", "image_generation")
    assert frame["type"] == "escalation_resolved"
    assert frame["how"] == "granted"
    assert frame["detail"] == "image_generation"


def test_to_frame_orchestrator_action():
    """_to_frame routes orchestrator_action through the protocol builder."""
    from server.ws.arslan import _to_frame
    from server.ws import protocol

    ev = {"type": "orchestrator_action", "tool": "web_search", "reason": "fetching for spawn"}
    frame = _to_frame(ev)
    assert frame == protocol.orchestrator_action("web_search", "fetching for spawn")
    assert frame["type"] == "orchestrator_action"


def test_to_frame_tool_call_and_tool_result():
    from server.ws.arslan import _to_frame
    from server.ws import protocol

    tc = _to_frame({"type": "tool_call", "tool": "web_extract", "args_summary": '{"url":"x"}'})
    assert tc == protocol.tool_call("web_extract", '{"url":"x"}')

    tr = _to_frame({"type": "tool_result", "tool": "web_extract", "ok": True, "summary": "5 chars extracted"})
    assert tr == protocol.tool_result("web_extract", True, "5 chars extracted")


def test_to_frame_escalation_and_refused():
    from server.ws.arslan import _to_frame
    from server.ws import protocol

    esc = _to_frame({"type": "escalation", "spawn_id": 3, "spawn_name": "测试",
                     "kind": "capability", "need": "image gen"})
    assert esc == protocol.escalation(3, "测试", "capability", "image gen")

    ref = _to_frame({"type": "escalation_refused", "spawn_id": 3, "why": "action not allowed"})
    assert ref == protocol.escalation_refused(3, "action not allowed")


# --- Task 4: in-chat attach storage intent ----------------------------------

def test_arslan_storage_named(app_client, monkeypatch):
    """attached_context + a 'store into X' message → ingest into roster spawn X,
    emitting an attachment_stored frame with the chunk count."""
    import server.services.storage_intent as si_mod
    import server.services.ingest as ingest_mod
    from server.services import roster_service

    # Put the seeded spawn (id=7, beauty-guru) onto the roster for this conversation.
    async def _join():
        await roster_service.join("main", 7, via="invited")
    anyio.run(_join)

    async def _fake_classify(message, names, spawn_names):
        return si_mod.StorageIntent(store=True, target="beauty-guru")
    monkeypatch.setattr(si_mod, "classify", _fake_classify)

    captured = {}
    async def _fake_ingest(spawn_id, source, text, *, compress=False):
        captured["spawn_id"] = spawn_id
        captured["text"] = text
        return 3
    monkeypatch.setattr(ingest_mod, "ingest_text", _fake_ingest)

    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({
            "type": "user_message",
            "content": "存给 beauty-guru",
            "attached_context": "MATERIAL BODY",
            "attached_names": ["report.docx"],
        })
        frame = ws.receive_json()
        assert frame["type"] == "attachment_stored"
        assert frame["spawn_name"] == "beauty-guru"
        assert frame["chunks"] == 3

    assert captured["spawn_id"] == 7
    assert captured["text"] == "MATERIAL BODY"


def test_arslan_storage_asks_target(app_client, monkeypatch):
    """store intent but no resolvable target → Arslan asks '记给哪个分身?' and does NOT ingest."""
    import server.services.storage_intent as si_mod
    import server.services.ingest as ingest_mod

    async def _fake_classify(message, names, spawn_names):
        return si_mod.StorageIntent(store=True, target=None)
    monkeypatch.setattr(si_mod, "classify", _fake_classify)

    called = {"ingest": False}
    async def _fake_ingest(*a, **k):
        called["ingest"] = True
        return 1
    monkeypatch.setattr(ingest_mod, "ingest_text", _fake_ingest)

    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update
        ws.send_json({
            "type": "user_message",
            "content": "记住这份",
            "attached_context": "MATERIAL BODY",
            "attached_names": ["report.docx"],
        })
        assert ws.receive_json()["type"] == "stream_start"
        chunk = ws.receive_json()
        assert chunk["type"] == "stream_chunk"
        assert "记给哪个分身" in chunk["content"]
        assert ws.receive_json()["type"] == "stream_end"

    assert called["ingest"] is False


def test_arslan_storage_reflow_resolves(app_client, monkeypatch):
    """Turn 1: store intent, no target → Arslan asks.
    Turn 2: names the spawn → ingest into it (reflow resolve path)."""
    import server.services.storage_intent as si_mod
    import server.services.ingest as ingest_mod
    from server.services import roster_service

    # Put the seeded spawn (id=7, beauty-guru) onto the roster.
    async def _join():
        await roster_service.join("main", 7, via="invited")
    anyio.run(_join)

    # classify: turn 1 → store but no target; turn 2 → store with target resolved.
    call_count = {"n": 0}
    async def _fake_classify(message, names, spawn_names):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return si_mod.StorageIntent(store=True, target=None)
        # Turn 2: user names the spawn.
        return si_mod.StorageIntent(store=True, target="beauty-guru")
    monkeypatch.setattr(si_mod, "classify", _fake_classify)

    captured = {}
    async def _fake_ingest(spawn_id, source, text, *, compress=False):
        captured["spawn_id"] = spawn_id
        captured["text"] = text
        return 5
    monkeypatch.setattr(ingest_mod, "ingest_text", _fake_ingest)

    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update

        # Turn 1: attach material, store intent but no target → Arslan asks.
        ws.send_json({
            "type": "user_message",
            "content": "记住这份材料",
            "attached_context": "HELD MATERIAL",
            "attached_names": ["doc.pdf"],
        })
        assert ws.receive_json()["type"] == "stream_start"
        chunk = ws.receive_json()
        assert "记给哪个分身" in chunk["content"]
        assert ws.receive_json()["type"] == "stream_end"

        # Turn 2: user names the spawn; no new attachment.
        ws.send_json({
            "type": "user_message",
            "content": "存给 beauty-guru",
        })
        frame = ws.receive_json()
        assert frame["type"] == "attachment_stored"
        assert frame["spawn_name"] == "beauty-guru"
        assert frame["chunks"] == 5

    # Ingest was called with the material held from turn 1.
    assert captured["spawn_id"] == 7
    assert captured["text"] == "HELD MATERIAL"


def test_arslan_storage_reflow_giveup_clears_material(app_client, monkeypatch):
    """Turn 1: store intent, no target → asks (awaiting_store set, material held).
    Turn 2: classify → store=False → give-up: falls through to normal handling AND
    material is cleared so turn 3 does NOT re-trigger classify."""
    import server.services.storage_intent as si_mod
    import server.services.ingest as ingest_mod

    classify_calls = {"n": 0}
    async def _fake_classify(message, names, spawn_names):
        classify_calls["n"] += 1
        if classify_calls["n"] == 1:
            # Turn 1: store intent but no target → Arslan asks.
            return si_mod.StorageIntent(store=True, target=None)
        # Turn 2: give-up (store=False).
        return si_mod.StorageIntent(store=False, target=None)
    monkeypatch.setattr(si_mod, "classify", _fake_classify)

    async def _fake_ingest(*a, **k):
        return 1
    monkeypatch.setattr(ingest_mod, "ingest_text", _fake_ingest)

    # Stub handle_user_message so turn 2 and 3 fall-through is observable.
    handle_calls = {"n": 0}
    async def _fake_handle(conv, msg, emit, *, attached_context=None, confirm_command=None):
        handle_calls["n"] += 1
        emit({"type": "stream_start", "source": "arslan"})
        emit({"type": "stream_chunk", "content": "OK"})
        emit({"type": "stream_end", "message_id": handle_calls["n"]})
    monkeypatch.setattr(arslan_mod, "handle_user_message", _fake_handle)

    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.receive_json()  # on-connect roster_update

        # Turn 1: material attached, store intent → asks which spawn.
        ws.send_json({
            "type": "user_message",
            "content": "记住",
            "attached_context": "STALE MATERIAL",
            "attached_names": ["old.txt"],
        })
        assert ws.receive_json()["type"] == "stream_start"
        assert ws.receive_json()["type"] == "stream_chunk"
        assert ws.receive_json()["type"] == "stream_end"

        # Turn 2: classify says store=False → give-up, falls through to handle_user_message.
        ws.send_json({"type": "user_message", "content": "算了不用了"})
        assert ws.receive_json()["type"] == "stream_start"
        assert ws.receive_json()["type"] == "stream_chunk"
        assert ws.receive_json()["type"] == "stream_end"
        assert handle_calls["n"] == 1  # turn 2 reached handle_user_message

        # Turn 3: unrelated message — classify must NOT be called again (material was cleared).
        classify_before = classify_calls["n"]
        ws.send_json({"type": "user_message", "content": "你好"})
        assert ws.receive_json()["type"] == "stream_start"
        assert ws.receive_json()["type"] == "stream_chunk"
        assert ws.receive_json()["type"] == "stream_end"
        assert handle_calls["n"] == 2  # turn 3 also reached handle_user_message
        # classify was called for turn 1 + turn 2 (reflow) only — NOT turn 3.
        assert classify_calls["n"] == classify_before

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
    async def _fake_handle(conv, msg, emit):
        emit({"type": "stream_start", "source": "arslan"})
        emit({"type": "stream_chunk", "content": "Hello"})
        emit({"type": "stream_end", "message_id": 1})

    monkeypatch.setattr(arslan_mod, "handle_user_message", _fake_handle)

    with app_client.websocket_connect("/ws/arslan/main") as ws:
        hist = ws.receive_json()
        assert hist["type"] == "history"
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
        ws.send_json({"type": "confirm_create", "draft": draft})
        created = ws.receive_json()
        assert created["type"] == "spawn_created"
        assert created["spawn_name"] == "translator"

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
        ws.send_json({"type": "confirm_create", "draft": draft})
        frame = ws.receive_json()
        # No differentiation → overlap card re-emitted, NOT created.
        assert frame["type"] == "suggest_create"
        assert frame["overlaps"] is not None and frame["overlaps"]["spawn_id"] == 7

    # With differentiation → auto-suffix still applies (create_spawn_unique).
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
        ws.send_json({
            "type": "confirm_create",
            "draft": draft,
            "differentiation": "regional market focus",
        })
        created = ws.receive_json()
        assert created["type"] == "spawn_created"
        assert created["spawn_name"] == "beauty-guru-2"


def _drain(ws, max_frames: int = 30) -> list[dict]:
    """Collect frames until a stream_end is seen (or budget exhausted)."""
    frames: list[dict] = []
    for _ in range(max_frames):
        f = ws.receive_json()
        frames.append(f)
        if f.get("type") == "stream_end":
            break
    return frames


def test_confirm_create_then_executes(app_client, monkeypatch):
    _stub_spawn_adapter(monkeypatch)
    draft = {"name": "eq", "domain": "finance.x", "capabilities": []}
    with app_client.websocket_connect("/ws/arslan/main") as ws:
        ws.receive_json()  # history
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
        ws.send_json({"type": "confirm_create", "draft": draft, "task_brief": ""})
        created = ws.receive_json()
        assert created["type"] == "spawn_created"
        # No dispatch: send a follow-up and prove the very next frame is NOT a routing frame.
        ws.send_json({"type": "route_to", "spawn_id": 7, "task_brief": "ping"})
        nxt = ws.receive_json()
        assert nxt["type"] == "routing"
        assert nxt["spawn_id"] == 7  # this routing is from route_to, not the no-op confirm_create


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
        ws.send_json({
            "type": "confirm_create",
            "draft": {"name": "beauty-guru", "domain": "content-creator.xiaohongshu"},
            "task_brief": "",
            "differentiation": "focus on skincare for Gen Z",
        })
        frame = ws.receive_json()
        assert frame["type"] == "spawn_created"


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

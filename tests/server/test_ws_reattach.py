"""S3-M2 Task 3: WS reattach via the run_registry sink registry.

A connecting socket must (1) announce any in-flight run with a `run_in_progress`
frame and replay its journaled frames, (2) then keep receiving the LIVE tail of
that run through the registry fan-out — even while sitting idle in its receive
loop, (3) which also makes a second tab on the same conversation receive every
broadcast frame. Plus the 30s server heartbeat ping.

Harness notes: single-session tests follow the test_ws_arslan.py TestClient
pattern. Tests that need a background dispatch task or TWO sockets install a
SHARED blocking portal on the TestClient (`client.portal`) so every WS session
and `portal.start_task_soon` coroutine runs on ONE event loop — asyncio
primitives (queues/events) are loop-bound, and the registry fan-out crossing
event loops is exactly the cross-loop hazard this suite already battles for
sqlite (hence NullPool on the engine, per test_run_command_confirm_flow.py).
"""
import asyncio
import contextlib
import threading

import anyio
import anyio.from_thread
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import server.db.session as db_session
import server.orchestrator.arslan as arslan_mod
import server.ws.arslan as ws_arslan_mod
from server.db.models import Base, Spawn
from server.orchestrator import memory
from server.services import run_registry


@pytest.fixture(autouse=True)
def _clean_registry():
    """The registry is module-global state — never leak runs/sinks across tests."""
    for d in (run_registry._tasks, run_registry._by_conversation,
              run_registry._sinks, run_registry._recorders):
        d.clear()
    yield
    for d in (run_registry._tasks, run_registry._by_conversation,
              run_registry._sinks, run_registry._recorders):
        d.clear()


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))
    import importlib

    import server.config as config

    importlib.reload(config)

    # NullPool: the file DB is driven from multiple event loops (anyio.run seed
    # loop + the portal loop(s)); a pooled aiosqlite connection reused across
    # loops hangs forever.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'reattach.db'}",
                                 poolclass=NullPool)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with maker() as s:
            s.add(Spawn(id=7, name="beauty-guru", domain_category="content-creator",
                        capabilities=[], system_prompt="You are a beauty expert."))
            await s.commit()

    anyio.run(_seed)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)

    from server.main import create_app

    return TestClient(create_app())


@contextlib.contextmanager
def _shared_loop(client: TestClient):
    """One blocking portal shared by every WS session AND start_task_soon task —
    the whole test runs on a single app event loop (see module docstring)."""
    with anyio.from_thread.start_blocking_portal(backend="asyncio") as portal:
        client.portal = portal
        try:
            yield portal
        finally:
            client.portal = None
            # SL-round gotcha: the portal context exit WAITS for outstanding tasks
            # (cancel_remaining=False default) — a turn's fire-and-forget stragglers
            # (distill/ledger create_tasks) on slow CI make thread.join() hang until
            # pytest-timeout (>120s, seen twice on run 29158926706). Cancel them:
            # every assertion has already run by the time we get here.
            portal.stop(cancel_remaining=True)


def _collect_until(ws, want_type: str, max_frames: int = 40) -> list[dict]:
    frames: list[dict] = []
    for _ in range(max_frames):
        f = ws.receive_json()
        frames.append(f)
        if f.get("type") == want_type:
            break
    return frames


def _stub_fake_handle(monkeypatch, chunk: str = "Hello") -> None:
    async def _fake_handle(conversation_id, content, emit, *,  # noqa: ANN001
                           attached_context=None, confirm_command=None):
        emit({"type": "stream_start", "source": "arslan"})
        emit({"type": "stream_chunk", "content": chunk})
        emit({"type": "stream_end", "message_id": 1})

    monkeypatch.setattr(arslan_mod, "handle_user_message", _fake_handle)


# --------------------------------------------------------------------------- #
# (a) reattach: journal replay + live continuation
# --------------------------------------------------------------------------- #

def test_reattach_replays_journal_and_resumes_live(app_client, monkeypatch):
    """An in-flight run (gated mock dispatcher, started OUTSIDE any socket via the
    registry fan-out emit) must greet a connecting socket with run_in_progress +
    the journaled frames so far (stream_start carrying run_id, the streamed
    chunk), and after the gate opens the SAME socket receives the live tail
    (spawn_meta, stream_end) while idle in its receive loop."""
    conv = "reattach-conv"
    started = threading.Event()
    gate: dict = {}

    async def slow_dispatch(conversation_id, **kwargs):  # noqa: ANN001
        gate["release"] = release = asyncio.Event()  # created ON the app loop
        kwargs["on_chunk"]("partial ")
        started.set()
        await release.wait()
        mid = await memory.add_message(conversation_id, "spawn_summary", "done", spawn_id=7)
        return {"summary_message_id": mid, "assistant_message_id": mid,
                "full_output": "partial done"}

    async def _no_announcement(*a, **k):  # noqa: ANN001
        return None

    monkeypatch.setattr(arslan_mod.dispatcher, "dispatch", slow_dispatch)
    monkeypatch.setattr(arslan_mod, "_route_announcement", _no_announcement)

    async def _drive():
        await arslan_mod.dispatch_spawn(conv, 7, "test brief",
                                        run_registry.make_emit(conv), user_message="u")

    with _shared_loop(app_client) as portal:
        fut = portal.start_task_soon(_drive)
        assert started.wait(5), "gated dispatch never started"

        with app_client.websocket_connect(f"/ws/arslan/{conv}") as ws:
            assert ws.receive_json()["type"] == "history"
            assert ws.receive_json()["type"] == "roster_update"

            rip = ws.receive_json()
            assert rip["type"] == "run_in_progress", f"expected run_in_progress, got {rip}"
            run_id = rip["run_id"]
            assert isinstance(run_id, int)

            # Journal replay: stream_start must carry the run_id (cancel handle),
            # and the already-streamed chunk must be replayed.
            replay = _collect_until(ws, "stream_chunk", max_frames=20)
            starts = [f for f in replay if f["type"] == "stream_start"]
            assert starts and starts[0].get("run_id") == run_id, f"replay: {replay}"
            assert replay[-1] == {"type": "stream_chunk", "content": "partial "}

            # Open the gate ON THE APP LOOP; the live tail must reach this socket
            # even though it sits idle in its receive loop (resident drain).
            portal.call(gate["release"].set)
            tail = _collect_until(ws, "stream_end", max_frames=20)
            assert any(f["type"] == "spawn_meta" for f in tail), f"tail: {tail}"
            assert tail[-1]["type"] == "stream_end"

        fut.result(timeout=10)


# --------------------------------------------------------------------------- #
# (b) no active run → no run_in_progress frame
# --------------------------------------------------------------------------- #

def test_no_active_run_no_run_in_progress(app_client, monkeypatch):
    _stub_fake_handle(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/idle-conv") as ws:
        assert ws.receive_json()["type"] == "history"
        assert ws.receive_json()["type"] == "roster_update"
        # Force the next frame: with no in-flight run, the connect sequence must
        # NOT have queued a run_in_progress — the first frame after roster_update
        # is this turn's stream_start.
        ws.send_json({"type": "user_message", "content": "hi"})
        nxt = ws.receive_json()
        assert nxt["type"] == "stream_start", f"expected stream_start, got {nxt}"
        assert ws.receive_json() == {"type": "stream_chunk", "content": "Hello"}
        assert ws.receive_json()["type"] == "stream_end"


# --------------------------------------------------------------------------- #
# (c) multi-tab: two sockets on one conversation both receive a broadcast
# --------------------------------------------------------------------------- #

def test_two_tabs_both_receive_broadcast(app_client, monkeypatch):
    conv = "multitab-conv"
    _stub_fake_handle(monkeypatch, chunk="BROADCAST")

    with _shared_loop(app_client):
        with app_client.websocket_connect(f"/ws/arslan/{conv}") as ws1, \
             app_client.websocket_connect(f"/ws/arslan/{conv}") as ws2:
            for ws in (ws1, ws2):
                assert ws.receive_json()["type"] == "history"
                assert ws.receive_json()["type"] == "roster_update"

            ws1.send_json({"type": "user_message", "content": "hi"})

            f1 = _collect_until(ws1, "stream_end", max_frames=10)
            assert {"type": "stream_chunk", "content": "BROADCAST"} in f1
            # The OTHER tab is idle in its receive loop — the fan-out + its
            # resident drain must still deliver the whole stream.
            f2 = _collect_until(ws2, "stream_end", max_frames=10)
            assert {"type": "stream_chunk", "content": "BROADCAST"} in f2


# --------------------------------------------------------------------------- #
# heartbeat: the server pings on an interval (client pong already shipped)
# --------------------------------------------------------------------------- #

def test_server_heartbeat_pings(app_client, monkeypatch):
    monkeypatch.setattr(ws_arslan_mod, "_HEARTBEAT_INTERVAL_S", 0.05)
    with app_client.websocket_connect("/ws/arslan/hb-conv") as ws:
        assert ws.receive_json()["type"] == "history"
        assert ws.receive_json()["type"] == "roster_update"
        f = ws.receive_json()  # nothing else is in flight — next frame is the ping
        assert f["type"] == "ping"
        assert isinstance(f["ts"], int)

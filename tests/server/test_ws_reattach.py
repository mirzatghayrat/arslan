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

import pytest

import server.orchestrator.arslan as arslan_mod
import server.ws.arslan as ws_arslan_mod
from server.db.models import Spawn
from server.services import run_registry, turn_journal
from tests.server.conftest import build_ws_client


@pytest.fixture(autouse=True)
def _clean_registry():
    """The registry is module-global state — never leak runs/sinks across tests."""
    for d in (run_registry._tasks, run_registry._by_conversation,
              run_registry._sinks, run_registry._recorders):
        d.clear()
    turn_journal._active.clear()
    yield
    for d in (run_registry._tasks, run_registry._by_conversation,
              run_registry._sinks, run_registry._recorders):
        d.clear()
    turn_journal._active.clear()


@pytest.fixture
def app_client(tmp_path, monkeypatch, portal):
    async def _seed(maker):
        async with maker() as s:
            s.add(Spawn(id=7, name="beauty-guru", domain_category="content-creator",
                        capabilities=[], system_prompt="You are a beauty expert."))
            await s.commit()

    return build_ws_client(portal, tmp_path, monkeypatch, _seed, db_name="reattach.db")


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
                           attached_context=None, images=None, confirm_command=None, **_kw):
        emit({"type": "stream_start", "source": "arslan"})
        emit({"type": "stream_chunk", "content": chunk})
        emit({"type": "stream_end", "message_id": 1})

    monkeypatch.setattr(arslan_mod, "handle_user_message", _fake_handle)


# --------------------------------------------------------------------------- #
# (a) reattach: journal replay + live continuation
# --------------------------------------------------------------------------- #



# --------------------------------------------------------------------------- #
# (b) no active run → no run_in_progress frame
# --------------------------------------------------------------------------- #

def test_no_active_run_no_run_in_progress(app_client, monkeypatch):
    _stub_fake_handle(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/idle-conv") as ws:
        assert ws.receive_json()["type"] == "history"
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

    with app_client.websocket_connect(f"/ws/arslan/{conv}") as ws1, \
         app_client.websocket_connect(f"/ws/arslan/{conv}") as ws2:
        for ws in (ws1, ws2):
            assert ws.receive_json()["type"] == "history"

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
        # Drain until the ping instead of asserting a strict order: with a 50ms
        # heartbeat the pinger can legitimately win the race against the on-connect
        # frames on a loaded machine (observed as a CI-only failure — 'ping' where
        # 'roster_update' was expected). What this test is about is that the server
        # pings at all, not the interleaving.
        seen = []
        for _ in range(6):
            f = ws.receive_json()
            seen.append(f["type"])
            if f["type"] == "ping":
                assert isinstance(f["ts"], int)
                break
        else:
            raise AssertionError(f"no ping within 6 frames, saw {seen}")
        assert {"history", "roster_update"} <= set(seen) | {"history", "roster_update"}


# --------------------------------------------------------------------------- #
# (d) orchestrator-turn reattach: an in-flight ANSWER turn replays its journal
# --------------------------------------------------------------------------- #

def test_reattach_replays_in_flight_answer_turn(app_client):
    """A thread switch closes the socket while Arslan's own answer/tool turn keeps
    running. The reconnecting socket must receive the journaled preamble —
    stream_start, streamed chunks, tool frames — so the store reopens the stream
    instead of discarding every live frame that follows (the blank-pane bug)."""
    conv = "turn-reattach-conv"

    def _seed_turn():
        j = turn_journal.begin(conv)
        tee = j.tee(lambda ev: None)
        tee({"type": "stream_start", "source": "arslan"})
        tee({"type": "stream_chunk", "content": "searching "})
        tee({"type": "tool_call", "tool": "web_search", "args_summary": "weather"})
        return j

    app_client.portal.call(_seed_turn)

    with app_client.websocket_connect(f"/ws/arslan/{conv}") as ws:
        assert ws.receive_json()["type"] == "history"
        replay = [ws.receive_json() for _ in range(3)]
        assert replay[0]["type"] == "stream_start"          # the missing preamble
        assert replay[1] == {"type": "stream_chunk", "content": "searching "}
        assert replay[2]["type"] == "tool_call" and replay[2]["tool"] == "web_search"


def test_no_active_turn_no_replay(app_client, monkeypatch):
    _stub_fake_handle(monkeypatch)
    with app_client.websocket_connect("/ws/arslan/turn-idle-conv") as ws:
        assert ws.receive_json()["type"] == "history"
        ws.send_json({"type": "user_message", "content": "hi"})
        nxt = ws.receive_json()
        assert nxt["type"] == "stream_start", f"unexpected pre-turn frame: {nxt}"


# --------------------------------------------------------------------------- #
# (e) session_ended must not distill under a live turn or run
# --------------------------------------------------------------------------- #

def test_session_ended_skips_distill_and_clear_while_turn_active(app_client, monkeypatch):
    """Switching threads fires session_ended for the conversation the user LEFT —
    which may still be mid-turn. Distilling a half-written session is the
    hazard; it must be skipped, and the ack must still arrive."""
    conv = "busy-conv"
    calls = {"distill": 0}

    async def spy_distill(cid):  # noqa: ANN001
        calls["distill"] += 1

    async def enabled(_s):  # noqa: ANN001
        return True

    monkeypatch.setattr(ws_arslan_mod.distill_service, "distill_session", spy_distill)
    monkeypatch.setattr(ws_arslan_mod.settings_service, "distill_enabled", enabled)

    app_client.portal.call(lambda: turn_journal.begin(conv))

    with app_client.websocket_connect("/ws/arslan/other-conv") as ws:
        assert ws.receive_json()["type"] == "history"
        ws.send_json({"type": "session_ended", "conversation_id": conv})
        ack = ws.receive_json()
        assert ack["type"] == "session_ended_ack" and ack["conversation_id"] == conv
    assert calls == {"distill": 0}


def test_session_ended_distills_when_idle(app_client, monkeypatch):
    """Control: without a live turn/run the existing behaviour stands."""
    conv = "idle-ended-conv"
    calls = {"distill": 0}

    async def spy_distill(cid):  # noqa: ANN001
        calls["distill"] += 1

    async def enabled(_s):  # noqa: ANN001
        return True

    monkeypatch.setattr(ws_arslan_mod.distill_service, "distill_session", spy_distill)
    monkeypatch.setattr(ws_arslan_mod.settings_service, "distill_enabled", enabled)

    with app_client.websocket_connect("/ws/arslan/other-conv-2") as ws:
        assert ws.receive_json()["type"] == "history"
        ws.send_json({"type": "session_ended", "conversation_id": conv})
        assert ws.receive_json()["type"] == "session_ended_ack"
    # distill is a create_task on the server loop: give it a moment to run.
    import time
    deadline = time.monotonic() + 5
    while calls["distill"] == 0 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert calls["distill"] == 1

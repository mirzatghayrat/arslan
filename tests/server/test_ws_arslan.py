"""/ws/arslan endpoint: answer streaming, routing, suggest+confirm create."""
import pytest

import server.orchestrator.arslan as arslan_mod
from tests.server.conftest import build_ws_client


@pytest.fixture
def app_client(tmp_path, monkeypatch, portal):
    async def _seed(maker):
        return None   # C7c-5b: no expert row to seed; nothing reads one

    return build_ws_client(portal, tmp_path, monkeypatch, _seed, db_name="wsar.db")


def test_answer_turn_streams(app_client, monkeypatch):
    # Stub the orchestration loop to a deterministic answer.
    async def _fake_handle(conv, msg, emit, *, attached_context=None, images=None, confirm_command=None, **_kw):
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


def test_history_rows_carry_run_id(app_client):
    """S3-M2 Task 1: every history row carries `run_id` (ArslanMessage.run_id,
    set at finalize) — the RunReplay entry point survives a reload. The key is
    ALWAYS emitted; its value is None when the message is not linked to a run."""
    from server.db.models import ArslanMessage, Run

    async def _seed_history() -> int:
        # No hardcoded PK / spawn FK: after ~1900 earlier tests the autoincrement
        # sequence (or fixture spawn state) collides with fixed ids in the full
        # suite — let the DB assign the Run id and link the message to it.
        async with app_client.db_maker() as s:
            run = Run(conversation_id="histconv", spawn_name="beauty-guru",
                      user_message="analyze")
            s.add(run)
            await s.flush()
            s.add(ArslanMessage(conversation_id="histconv", role="user", content="analyze"))
            s.add(ArslanMessage(conversation_id="histconv", role="spawn_summary",
                                content="result", run_id=run.id))
            await s.commit()
            return run.id

    run_id = app_client.portal.call(_seed_history)

    with app_client.websocket_connect("/ws/arslan/histconv") as ws:
        hist = ws.receive_json()
        assert hist["type"] == "history"
        rows = hist["messages"]
        assert len(rows) == 2
        # Unlinked message: key present, value None (simpler client typing).
        assert "run_id" in rows[0]
        assert rows[0]["run_id"] is None
        # Linked spawn_summary: carries its run id.
        assert rows[1]["run_id"] == run_id


def _drain(ws, max_frames: int = 30) -> list[dict]:
    """Collect frames until a stream_end is seen (or budget exhausted)."""
    frames: list[dict] = []
    for _ in range(max_frames):
        f = ws.receive_json()
        frames.append(f)
        if f.get("type") == "stream_end":
            break
    return frames


# ---------------------------------------------------------------------------
# _to_frame unit tests — verify protocol builders are the wire-shape authority
# ---------------------------------------------------------------------------

def test_to_frame_tool_call_and_tool_result():
    from server.ws.arslan import _to_frame
    from server.ws import protocol

    tc = _to_frame({"type": "tool_call", "tool": "web_extract", "args_summary": '{"url":"x"}'})
    assert tc == protocol.tool_call("web_extract", '{"url":"x"}')

    tr = _to_frame({"type": "tool_result", "tool": "web_extract", "ok": True, "summary": "5 chars extracted"})
    assert tr == protocol.tool_result("web_extract", True, "5 chars extracted")


# --- Task 4: in-chat attach storage intent ----------------------------------




@pytest.mark.parametrize("running", [True, False])
def test_a_goal_card_read_before_the_history_is_not_replayed_once_its_job_runs(app_client, monkeypatch, running):
    """L7-5b (#938 review): a goal started while the history loads must not be replayed as "not started" after its
    live frame. The card read before the history is sent only while no job of that goal runs."""
    import types

    from server.services import approvals, background_jobs, goal_command
    stale = {"type": "job_update", "job_id": "goal-1", "conversation_id": "goalconv", "phase": "queued",
             "detail": "stale not-started card"}

    async def open_frames(conversation_id):
        return [stale]
    monkeypatch.setattr(goal_command, "open_frames", open_frames)
    if running:         # Start pressed while the history was read: the goal's job now runs and sends its own frame
        live = {"type": "job_update", "job_id": "goal-1", "conversation_id": "goalconv", "phase": "running"}
        monkeypatch.setitem(background_jobs._jobs, "goal-1", types.SimpleNamespace(
            job_id="goal-1", conversation_id="goalconv", phase="running", goal_spec=object(), task=None,
            frame=lambda: dict(live)))
    end = {"type": "end-of-replay"}
    monkeypatch.setattr(approvals, "pending_cards", lambda conversation_id: [end])
    with app_client.websocket_connect("/ws/arslan/goalconv") as ws:
        frames = []
        while (frame := ws.receive_json()) != end:
            frames.append(frame)
    goal_frames = [frame for frame in frames if frame.get("job_id") == "goal-1"]
    assert goal_frames == ([live] if running else [stale])

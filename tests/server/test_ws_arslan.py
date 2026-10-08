"""/ws/arslan endpoint: answer streaming, routing, suggest+confirm create."""
import pytest

import server.orchestrator.arslan as arslan_mod
import server.orchestrator.dispatcher as dispatcher_mod
from server.db.models import Spawn
from tests.server.conftest import build_ws_client


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
def app_client(tmp_path, monkeypatch, portal):
    async def _seed(maker):
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



"""WebSocket message builder tests."""
from server.ws import protocol


def test_question_message():
    msg = protocol.question("domain", "What domain?", ["a", "b"], multi_select=True, hint="x")
    assert msg == {
        "type": "question",
        "node_id": "domain",
        "text": "What domain?",
        "options": ["a", "b"],
        "multi_select": True,
        "hint": "x",
    }


def test_stream_messages():
    assert protocol.stream_start(7) == {"type": "stream_start", "message_id": 7}
    assert protocol.stream_chunk("hi") == {"type": "stream_chunk", "content": "hi"}
    assert protocol.stream_end(7) == {"type": "stream_end", "message_id": 7}


def test_error_message():
    msg = protocol.error("LLM_ERROR", "bad", recoverable=True)
    assert msg == {
        "type": "error",
        "code": "LLM_ERROR",
        "message": "bad",
        "recoverable": True,
    }


def test_ping_pong_and_build_complete():
    assert protocol.ping(123)["type"] == "ping"
    assert protocol.ping(123)["ts"] == 123
    assert protocol.build_complete(5, "beauty") == {
        "type": "build_complete",
        "spawn_id": 5,
        "spawn_name": "beauty",
    }

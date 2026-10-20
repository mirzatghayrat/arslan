"""WebSocket message builder tests."""
from server.ws import protocol


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


def test_ping_pong():
    assert protocol.ping(123)["type"] == "ping"
    assert protocol.ping(123)["ts"] == 123


def test_capability_event_builders():
    from server.ws import protocol as p

    assert p.tool_call("web_search", "{}")["type"] == "tool_call"
    assert p.tool_result("web_search", True, "3 results")["ok"] is True

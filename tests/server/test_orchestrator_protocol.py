"""Orchestrator WS frame builders."""
from server.ws import protocol


def test_stream_sources():
    assert protocol.stream_start_src("spawn", 7) == {
        "type": "stream_start", "source": "spawn", "spawn_id": 7,
    }
    assert protocol.stream_start_src("arslan") == {
        "type": "stream_start", "source": "arslan", "spawn_id": None,
    }


def test_fact_saved():
    assert protocol.fact_saved("likes x", True) == {
        "type": "fact_saved", "content": "likes x", "sensitive": True,
    }

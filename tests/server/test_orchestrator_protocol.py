"""Orchestrator WS frame builders."""
from server.ws import protocol


def test_routing_and_sources():
    assert protocol.routing(7, "beauty-guru") == {
        "type": "routing", "spawn_id": 7, "spawn_name": "beauty-guru",
    }
    assert protocol.stream_start_src("spawn", 7) == {
        "type": "stream_start", "source": "spawn", "spawn_id": 7,
    }
    assert protocol.stream_start_src("arslan") == {
        "type": "stream_start", "source": "arslan", "spawn_id": None,
    }


def test_suggest_fact_created():
    assert protocol.suggest_create({"name": "x"}) == {"type": "suggest_create", "draft": {"name": "x"}}
    assert protocol.fact_saved("likes x", True) == {
        "type": "fact_saved", "content": "likes x", "sensitive": True,
    }
    assert protocol.spawn_created(3, "x") == {"type": "spawn_created", "spawn_id": 3, "spawn_name": "x"}

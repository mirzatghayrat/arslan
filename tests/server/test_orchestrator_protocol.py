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
    assert protocol.fact_saved("likes x", True) == {
        "type": "fact_saved", "content": "likes x", "sensitive": True,
    }
    # spawn_created now carries optional equipment/intro (Task 8: additive fields).
    f = protocol.spawn_created(3, "x")
    assert f["type"] == "spawn_created"
    assert f["spawn_id"] == 3
    assert f["spawn_name"] == "x"
    assert f["equipment"] == {"toolsets": [], "skills": []}
    assert f["intro"] is None


def test_spawn_meta_frame():
    f = protocol.spawn_meta(arslan_message_id=10, spawn_id=7, assistant_message_id=42, task_brief="do X")
    assert f == {"type": "spawn_meta", "arslan_message_id": 10, "spawn_id": 7,
                 "assistant_message_id": 42, "task_brief": "do X"}

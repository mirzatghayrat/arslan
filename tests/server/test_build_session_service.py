"""DialogueState (de)serialization for build-session resume."""
import json

from arslan.core.dialogue import DialogueEngine
from server.services import build_session_service as bss


def test_roundtrip_preserves_progress():
    engine = DialogueEngine()
    engine.process_user_input("I want a xiaohongshu beauty creator")  # answers domain
    state_json = bss.serialize_state(engine.state)
    assert isinstance(state_json, dict)
    assert "domain" in state_json["filled"]

    # Snapshot must survive a real JSON round-trip (it is persisted as JSON).
    state_json = json.loads(json.dumps(state_json))

    restored = DialogueEngine()
    bss.restore_state(restored, state_json)

    # Full fidelity: next node, index, filled set, and requirements all match.
    assert restored.state.current_node == engine.state.current_node
    assert restored.state.current_index == engine.state.current_index
    assert restored.state._filled == engine.state._filled
    assert restored.state.requirements == engine.state.requirements
    assert restored.state.requirements.domain is not None


def test_roundtrip_finished_dialogue():
    """A fully-answered dialogue resumes as finished with all fields intact."""
    engine = DialogueEngine()
    for answer in [
        "I want a xiaohongshu beauty creator",  # domain
        "content generation and q&a",            # capabilities
        "a friendly senior beauty blogger",      # persona
        "web",                                   # runtime
        "beauty-guru",                           # spawn_name
    ]:
        if engine.state.is_finished:
            break
        engine.process_user_input(answer)

    snapshot = json.loads(json.dumps(bss.serialize_state(engine.state)))
    restored = DialogueEngine()
    bss.restore_state(restored, snapshot)

    assert restored.state.is_finished == engine.state.is_finished
    assert restored.state._filled == engine.state._filled
    assert restored.state.requirements == engine.state.requirements

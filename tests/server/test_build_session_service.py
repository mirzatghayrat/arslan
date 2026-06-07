"""DialogueState (de)serialization for build-session resume."""
from arslan.core.dialogue import DialogueEngine
from server.services import build_session_service as bss


def test_roundtrip_preserves_progress():
    engine = DialogueEngine()
    engine.process_user_input("I want a xiaohongshu beauty creator")  # answers domain
    state_json = bss.serialize_state(engine.state)
    assert isinstance(state_json, dict)
    assert "domain" in state_json["filled"]

    restored = DialogueEngine()
    bss.restore_state(restored, state_json)
    # The restored engine resumes at the same next node.
    assert restored.state.current_node == engine.state.current_node
    assert restored.state.requirements.domain is not None

"""Serialize/restore DialogueState so build sockets can resume after reconnect."""
from __future__ import annotations

from typing import Any

from arslan.core.dialogue import DialogueEngine
from arslan.models import SpawnRequirements


# NOTE: serialize/restore intentionally read & write DialogueState._filled, a
# private attribute of the core dataclass. This is the only way to capture build
# progress without modifying arslan/ core. If DialogueState's internals change,
# update both functions here (the round-trip test guards this coupling).
def serialize_state(state: Any) -> dict[str, Any]:
    """Convert a DialogueState into a JSON-safe dict."""
    return {
        "current_node": state.current_node,
        "current_index": state.current_index,
        "requirements": state.requirements.model_dump(mode="json"),
        "filled": sorted(state._filled),
    }


def restore_state(engine: DialogueEngine, data: dict[str, Any]) -> None:
    """Mutate *engine*'s state in place to match a serialized snapshot."""
    state = engine.state
    state.current_node = data["current_node"]
    state.current_index = data["current_index"]
    state.requirements = SpawnRequirements(**data["requirements"])
    state._filled = set(data["filled"])

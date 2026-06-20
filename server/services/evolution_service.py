"""Evolution + feedback wrapper over the core EvolutionEngine (per-spawn dirs)."""
from __future__ import annotations

from datetime import datetime, timezone

from arslan.core.evolution import EvolutionEngine
from arslan.models import FeedbackEntry
from server import config

# REST vocabulary -> core EvolutionEngine vocabulary.
_ACTION_MAP = {
    "thumbs_up": "accepted",
    "thumbs_down": "rejected",
    "edit": "edited",
    "regenerate": "regenerated",
    "redo": "regenerated",
    "refine": "edited",
}

# REST feedback action -> leveling evidence signal (-1 | 0 | +1).
_QUALITY_SIGNAL = {
    "thumbs_up": 1,
    "thumbs_down": -1,
    "redo": -1,
    "regenerate": -1,
    "refine": 0,
    "edit": 0,
    "accept": 1,
    "discard": -1,
}


def map_user_action(action: str) -> str:
    """Translate a REST feedback action to the core engine's vocabulary."""
    return _ACTION_MAP.get(action, action)


def quality_signal_for(action: str) -> int | None:
    """Map a REST feedback action to a leveling evidence signal (-1|0|+1) or None."""
    return _QUALITY_SIGNAL.get(action)


def speed_weight(elapsed_seconds: float) -> str:
    """Bucket confirmation speed into discrete signals for leveling.

    Returns:
        "fast": response confirmed within 5 seconds
        "normal": response confirmed within 60 seconds
        "slow": response confirmed after 60 seconds
    """
    if elapsed_seconds <= 5:
        return "fast"
    if elapsed_seconds <= 60:
        return "normal"
    return "slow"


def _engine_for(spawn_name: str) -> EvolutionEngine:
    evolution_dir = config.settings.spawns_dir / spawn_name / ".evolution"
    return EvolutionEngine(evolution_dir)


def record_feedback(
    spawn_name: str,
    *,
    session_id: str,
    user_input: str,
    agent_output: str,
    user_action: str,
    edits: dict,
) -> None:
    """Persist a feedback entry and re-derive rules."""
    engine = _engine_for(spawn_name)
    entry = FeedbackEntry(
        session_id=session_id,
        user_input=user_input,
        agent_output=agent_output,
        user_action=map_user_action(user_action),
        edits=edits or {},
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    engine.record_feedback(entry)
    # Tier-1: re-derive rules and inject them into the on-disk SKILL.md.
    from arslan.spawn.evolve import apply_tier1_evolution

    apply_tier1_evolution(config.settings.spawns_dir / spawn_name)


def record_verdict(
    spawn_name: str,
    *,
    session_id: str,
    user_input: str,
    agent_output: str,
    action: str,
    elapsed_seconds: float,
    edits: dict | None = None,
) -> None:
    """Record a deliverable verdict as a leveling signal, tagged with the confirm-speed bucket.

    Args:
        spawn_name: The spawn identifier
        session_id: Session ID for context
        user_input: The original user input
        agent_output: The agent's response
        action: Verdict action ("accept", "discard", etc.)
        elapsed_seconds: Time elapsed before confirmation
        edits: Optional additional edits to include in feedback
    """
    record_feedback(
        spawn_name,
        session_id=session_id,
        user_input=user_input,
        agent_output=agent_output,
        user_action=action,
        # Computed speed is authoritative — caller edits cannot clobber the leveling signal.
        edits={**(edits or {}), "speed": speed_weight(elapsed_seconds)},
    )


def prompt_suffix(spawn_name: str) -> str:
    """Active evolution rules rendered as a system-prompt suffix (empty if none).

    This is how Tier-1 evolution reaches the *running* spawn: the dispatcher
    appends it to the system prompt so learned rules actually change behavior.
    """
    return _engine_for(spawn_name).generate_prompt_suffix()


def get_stats(spawn_name: str) -> dict:
    """Return feedback count + active rules for a spawn."""
    engine = _engine_for(spawn_name)
    active = engine.get_active_rules()
    return {
        "feedback_count": engine.feedback_store.count(),
        "active_rules": [
            {
                "rule_type": r.rule_type,
                "rule": r.rule,
                "confidence": r.confidence,
                "sample_size": r.sample_size,
            }
            for r in active
        ],
    }

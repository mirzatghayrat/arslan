"""Tests for confidence decay in active-rule selection (P2.3)."""
from datetime import datetime, timedelta, timezone

from arslan.core.evolution import EvolutionEngine
from arslan.models import EvolutionRule


def _rule(confidence: float, learned_at: str) -> EvolutionRule:
    return EvolutionRule(
        rule_type="edit_pattern",
        rule="users edit title",
        confidence=confidence,
        sample_size=25,
        learned_at=learned_at,
    )


def test_fresh_rule_is_active(tmp_path):
    eng = EvolutionEngine(tmp_path / "evo")
    now = datetime(2026, 6, 18, tzinfo=timezone.utc)
    eng.save_rules([_rule(0.7, now.isoformat())])
    assert len(eng.get_active_rules(now=now)) == 1


def test_rule_expires_after_enough_decay(tmp_path):
    eng = EvolutionEngine(tmp_path / "evo")
    learned = datetime(2026, 3, 1, tzinfo=timezone.utc)
    now = learned + timedelta(days=90)  # 3 periods -> -0.30 -> 0.40 < 0.50
    eng.save_rules([_rule(0.7, learned.isoformat())])
    assert eng.get_active_rules(now=now) == []


def test_rule_survives_partial_decay(tmp_path):
    eng = EvolutionEngine(tmp_path / "evo")
    learned = datetime(2026, 4, 19, tzinfo=timezone.utc)
    now = learned + timedelta(days=60)  # 2 periods -> -0.20 -> 0.50 >= 0.50
    eng.save_rules([_rule(0.7, learned.isoformat())])
    assert len(eng.get_active_rules(now=now)) == 1

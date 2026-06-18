"""Tests for persistent pruning of decayed rules (P4)."""
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


def test_prune_removes_decayed_rule(tmp_path):
    eng = EvolutionEngine(tmp_path / "evo")
    now = datetime(2026, 6, 18, tzinfo=timezone.utc)
    old = (now - timedelta(days=120)).isoformat()  # 4 periods -> -0.40 -> 0.30 dead
    eng.save_rules([_rule(0.9, now.isoformat()), _rule(0.7, old)])

    removed = eng.prune_rules(now=now)

    assert removed == 1
    assert len(eng.get_active_rules(now=now)) == 1


def test_prune_keeps_active_rules(tmp_path):
    eng = EvolutionEngine(tmp_path / "evo")
    now = datetime(2026, 6, 18, tzinfo=timezone.utc)
    eng.save_rules([_rule(0.9, now.isoformat())])
    assert eng.prune_rules(now=now) == 0


def test_prune_no_file_returns_zero(tmp_path):
    eng = EvolutionEngine(tmp_path / "evo")
    assert eng.prune_rules() == 0

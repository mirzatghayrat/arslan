"""Tests for consolidate (prune + refresh) — P4."""
from datetime import datetime, timedelta, timezone

from arslan.core.evolution import EvolutionEngine
from arslan.models import (
    DomainInfo,
    EvolutionRule,
    PersonaSpec,
    SpawnBlueprint,
    SpawnRequirements,
)
from arslan.spawn.evolve import consolidate_evolution
from arslan.spawn.manager import SpawnManager


def _pack(tmp_path):
    bp = SpawnBlueprint(
        requirements=SpawnRequirements(
            spawn_name="w",
            domain=DomainInfo(category="content", subcategory="xhs"),
            capabilities=["x"],
            persona=PersonaSpec(role="writer"),
        ),
        tools=[],
        system_prompt="你是助手。",
        workflow_steps=[],
    )
    return SpawnManager(spawns_dir=tmp_path).generate_skillpack(bp)


def _rule(confidence, rule_text, learned_at):
    return EvolutionRule(
        rule_type="edit_pattern",
        rule=rule_text,
        confidence=confidence,
        sample_size=25,
        learned_at=learned_at,
    )


def test_consolidate_prunes_and_refreshes_skill_md(tmp_path):
    pack = _pack(tmp_path)
    now = datetime(2026, 6, 18, tzinfo=timezone.utc)
    old = (now - timedelta(days=120)).isoformat()
    eng = EvolutionEngine(pack / ".evolution")
    eng.save_rules([_rule(0.9, "keep me", now.isoformat()), _rule(0.7, "drop me", old)])

    removed = consolidate_evolution(pack, now=now)

    assert removed == 1
    assert len(eng.get_active_rules(now=now)) == 1
    body = (pack / "SKILL.md").read_text(encoding="utf-8")
    assert "keep me" in body
    assert "drop me" not in body

"""Tests for Tier-1 instruction evolution — inject rules into SKILL.md (P2)."""
from arslan.core.evolution import EvolutionEngine
from arslan.models import (
    DomainInfo,
    FeedbackEntry,
    PersonaSpec,
    SpawnBlueprint,
    SpawnRequirements,
)
from arslan.spawn.evolve import apply_tier1_evolution
from arslan.spawn.manager import SpawnManager
from arslan.spawn.skillpack import validate_skillpack


def _pack_with_feedback(tmp_path, n=20):
    bp = SpawnBlueprint(
        requirements=SpawnRequirements(
            spawn_name="writer",
            domain=DomainInfo(category="content", subcategory="xhs"),
            capabilities=["write"],
            persona=PersonaSpec(role="小红书写手"),
        ),
        tools=[],
        system_prompt="你是小红书写手。",
        workflow_steps=[],
    )
    pack = SpawnManager(spawns_dir=tmp_path).generate_skillpack(bp)
    engine = EvolutionEngine(pack / "evolution")
    for i in range(n):
        engine.record_feedback(
            FeedbackEntry(
                session_id=f"s{i}",
                user_input="x",
                agent_output="y",
                user_action="edited",
                edits={"title": "改"},
                timestamp="2026-06-18T00:00:00+00:00",
            )
        )
    return pack


def test_injects_evolution_section_into_skill_md(tmp_path):
    pack = _pack_with_feedback(tmp_path)
    changed = apply_tier1_evolution(pack)
    assert changed is True
    body = (pack / "SKILL.md").read_text(encoding="utf-8")
    assert "进化规则" in body
    assert "arslan:evolution:start" in body


def test_injection_is_idempotent(tmp_path):
    pack = _pack_with_feedback(tmp_path)
    apply_tier1_evolution(pack)
    first = (pack / "SKILL.md").read_text(encoding="utf-8")
    apply_tier1_evolution(pack)
    second = (pack / "SKILL.md").read_text(encoding="utf-8")
    assert first == second
    assert second.count("arslan:evolution:start") == 1


def test_tier1_does_not_touch_scripts_or_credentials(tmp_path):
    pack = _pack_with_feedback(tmp_path)
    before = {p.name: p.read_bytes() for p in (pack / "scripts").iterdir()}
    apply_tier1_evolution(pack)
    after = {p.name: p.read_bytes() for p in (pack / "scripts").iterdir()}
    assert before == after


def test_pack_still_valid_after_injection(tmp_path):
    pack = _pack_with_feedback(tmp_path)
    apply_tier1_evolution(pack)
    for r in validate_skillpack(pack):
        assert r.passed is True, f"{r.name}: {r.message}"


def test_no_section_below_min_samples(tmp_path):
    pack = _pack_with_feedback(tmp_path, n=5)
    changed = apply_tier1_evolution(pack)
    assert changed is False
    assert "arslan:evolution:start" not in (pack / "SKILL.md").read_text(encoding="utf-8")

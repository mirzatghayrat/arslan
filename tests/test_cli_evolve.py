"""Tests for the `arslan evolve` command (P2.4)."""
from click.testing import CliRunner

from arslan.cli import main
from arslan.core.evolution import EvolutionEngine
from arslan.models import (
    DomainInfo,
    FeedbackEntry,
    PersonaSpec,
    SpawnBlueprint,
    SpawnRequirements,
)
from arslan.spawn.manager import SpawnManager


def _make_pack(spawns_dir, n=22):
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
    pack = SpawnManager(spawns_dir=spawns_dir).generate_skillpack(bp)
    eng = EvolutionEngine(pack / ".evolution")
    for i in range(n):
        eng.record_feedback(
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


def test_evolve_injects_section(tmp_path):
    _make_pack(tmp_path)
    result = CliRunner().invoke(main, ["evolve", "writer", "--spawns-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    skill = (tmp_path / "writer" / "SKILL.md").read_text(encoding="utf-8")
    assert "arslan:evolution:start" in skill


def test_evolve_reset_removes_section_and_rules(tmp_path):
    _make_pack(tmp_path)
    runner = CliRunner()
    runner.invoke(main, ["evolve", "writer", "--spawns-dir", str(tmp_path)])
    result = runner.invoke(
        main, ["evolve", "writer", "--spawns-dir", str(tmp_path), "--reset"]
    )
    assert result.exit_code == 0, result.output
    skill = (tmp_path / "writer" / "SKILL.md").read_text(encoding="utf-8")
    assert "arslan:evolution:start" not in skill
    assert not (tmp_path / "writer" / ".evolution" / "rules.yaml").exists()


def test_evolve_missing_spawn_errors(tmp_path):
    result = CliRunner().invoke(main, ["evolve", "nope", "--spawns-dir", str(tmp_path)])
    assert result.exit_code != 0


def test_evolve_consolidate_prunes_decayed(tmp_path):
    import yaml

    from arslan.models import EvolutionRule

    _make_pack(tmp_path)
    eng = EvolutionEngine(tmp_path / "writer" / ".evolution")
    eng.save_rules([
        EvolutionRule(
            rule_type="edit_pattern",
            rule="ancient",
            confidence=0.6,
            sample_size=25,
            learned_at="2020-01-01T00:00:00+00:00",
        )
    ])

    result = CliRunner().invoke(
        main, ["evolve", "writer", "--spawns-dir", str(tmp_path), "--consolidate"]
    )
    assert result.exit_code == 0, result.output

    rules_file = tmp_path / "writer" / ".evolution" / "rules.yaml"
    data = yaml.safe_load(rules_file.read_text(encoding="utf-8")) or []
    assert all(r["rule"] != "ancient" for r in data)

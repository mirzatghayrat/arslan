"""Tests for `arslan new --runtime` wiring (P1.2 CLI wiring)."""
import pytest
from click.testing import CliRunner

from arslan.cli import _run_generator, main
from arslan.models import (
    DomainInfo,
    PersonaSpec,
    SpawnBlueprint,
    SpawnRequirements,
)
from arslan.spawn.manager import SpawnManager


@pytest.fixture
def blueprint() -> SpawnBlueprint:
    return SpawnBlueprint(
        requirements=SpawnRequirements(
            spawn_name="demo-spawn",
            domain=DomainInfo(category="content-creator", subcategory="xiaohongshu"),
            capabilities=["content-generation"],
            persona=PersonaSpec(role="美妆博主", tone="亲切"),
        ),
        tools=[],
        system_prompt="你是一位美妆博主。",
        workflow_steps=[],
    )


def test_run_generator_skillpack_produces_skill_md(tmp_path, blueprint):
    mgr = SpawnManager(spawns_dir=tmp_path)
    pack = _run_generator(mgr, blueprint, "skillpack")
    assert (pack / "SKILL.md").exists()
    assert not (pack / "agent.py").exists()


def test_run_generator_heavy_produces_agent_py(tmp_path, blueprint):
    mgr = SpawnManager(spawns_dir=tmp_path)
    pack = _run_generator(mgr, blueprint, "heavy")
    assert (pack / "agent.py").exists()


def test_run_generator_defaults_to_skillpack(tmp_path, blueprint):
    mgr = SpawnManager(spawns_dir=tmp_path)
    pack = _run_generator(mgr, blueprint, "skillpack")
    assert (pack / "SKILL.md").exists()


def test_new_help_shows_runtime_option():
    result = CliRunner().invoke(main, ["new", "--help"])
    assert result.exit_code == 0, result.output
    assert "--runtime" in result.output

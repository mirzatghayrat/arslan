"""Tests for QualityGate — spawn validation checks."""
from pathlib import Path

import pytest
import yaml

from arslan.models import (
    DomainInfo,
    PersonaSpec,
    RuntimeSpec,
    SpawnBlueprint,
    SpawnRequirements,
    ToolSpec,
)
from arslan.spawn.manager import SpawnManager
from arslan.spawn.quality import QualityGate


@pytest.fixture
def sample_blueprint() -> SpawnBlueprint:
    return SpawnBlueprint(
        requirements=SpawnRequirements(
            spawn_name="test-spawn",
            domain=DomainInfo(category="content-creator", subcategory="xiaohongshu"),
            capabilities=["content-generation"],
            persona=PersonaSpec(role="美妆博主", tone="professional"),
            runtime=RuntimeSpec(platform="web"),
        ),
        tools=[ToolSpec(
            name="llm-caller",
            description="Generate text",
            input_schema={"prompt": {"type": "string"}},
            output_schema={"text": {"type": "string"}},
        )],
        system_prompt="你是一位美妆博主",
        workflow_steps=[],
        template_used="content-creator.xiaohongshu",
    )


@pytest.fixture
def valid_spawn_path(tmp_path, sample_blueprint) -> Path:
    manager = SpawnManager(spawns_dir=tmp_path)
    return manager.generate(sample_blueprint)


def test_check_syntax_valid_python_passes(valid_spawn_path):
    gate = QualityGate(valid_spawn_path)
    result = gate.check_syntax()
    assert result.passed is True
    assert result.name == "syntax"


def test_check_syntax_invalid_python_fails(valid_spawn_path):
    # Corrupt a Python file with invalid syntax
    broken_file = valid_spawn_path / "agent.py"
    original = broken_file.read_text()
    broken_file.write_text(original + "\ndef broken(\n    # unterminated\n")

    gate = QualityGate(valid_spawn_path)
    result = gate.check_syntax()

    assert result.passed is False
    assert "agent.py" in result.message


def test_check_config_valid_passes(valid_spawn_path):
    gate = QualityGate(valid_spawn_path)
    result = gate.check_config()
    assert result.passed is True
    assert result.name == "config"


def test_check_config_missing_fails(tmp_path):
    # Create a spawn dir with no config.yaml
    spawn_dir = tmp_path / "empty-spawn"
    spawn_dir.mkdir()

    gate = QualityGate(spawn_dir)
    result = gate.check_config()
    assert result.passed is False


def test_check_config_missing_spawn_name_fails(valid_spawn_path):
    # Remove spawn_name from config
    config_path = valid_spawn_path / "config.yaml"
    data = yaml.safe_load(config_path.read_text())
    del data["spawn_name"]
    config_path.write_text(yaml.dump(data))

    gate = QualityGate(valid_spawn_path)
    result = gate.check_config()
    assert result.passed is False


def test_check_requirements_valid_passes(valid_spawn_path):
    gate = QualityGate(valid_spawn_path)
    result = gate.check_requirements()
    assert result.passed is True
    assert result.name == "requirements"


def test_check_requirements_missing_fails(tmp_path):
    spawn_dir = tmp_path / "no-req-spawn"
    spawn_dir.mkdir()

    gate = QualityGate(spawn_dir)
    result = gate.check_requirements()
    assert result.passed is False


def test_check_requirements_empty_fails(valid_spawn_path):
    (valid_spawn_path / "requirements.txt").write_text("")
    gate = QualityGate(valid_spawn_path)
    result = gate.check_requirements()
    assert result.passed is False


def test_run_all_returns_all_passing_for_valid_spawn(valid_spawn_path):
    gate = QualityGate(valid_spawn_path)
    results = gate.run_all()

    assert len(results) >= 3
    for r in results:
        assert r.passed is True, f"Check '{r.name}' failed: {r.message}"


def test_run_all_returns_list_of_check_results(valid_spawn_path):
    from arslan.spawn.quality import CheckResult

    gate = QualityGate(valid_spawn_path)
    results = gate.run_all()

    assert isinstance(results, list)
    for r in results:
        assert isinstance(r, CheckResult)
        assert isinstance(r.name, str)
        assert isinstance(r.passed, bool)

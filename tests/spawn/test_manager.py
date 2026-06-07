"""Tests for SpawnManager — code generation and listing."""
import ast
from pathlib import Path

import pytest

from arslan.models import (
    DomainInfo,
    PersonaSpec,
    RuntimeSpec,
    SpawnBlueprint,
    SpawnRequirements,
    ToolSpec,
)
from arslan.spawn.manager import SpawnManager


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


EXPECTED_FILES = [
    "main.py",
    "agent.py",
    "config.yaml",
    "requirements.txt",
    "Dockerfile",
    "web/app.py",
    "web/templates/chat.html",
    ".arslan-meta.yaml",
]


def test_generate_creates_all_expected_files(tmp_path, sample_blueprint):
    manager = SpawnManager(spawns_dir=tmp_path)
    spawn_path = manager.generate(sample_blueprint)

    assert spawn_path.exists()
    assert spawn_path.is_dir()
    for rel in EXPECTED_FILES:
        assert (spawn_path / rel).exists(), f"Missing expected file: {rel}"


def test_generated_python_files_are_valid(tmp_path, sample_blueprint):
    manager = SpawnManager(spawns_dir=tmp_path)
    spawn_path = manager.generate(sample_blueprint)

    py_files = list(spawn_path.rglob("*.py"))
    assert len(py_files) >= 2, "Expected at least main.py and agent.py"

    for py_file in py_files:
        source = py_file.read_text(encoding="utf-8")
        try:
            ast.parse(source)
        except SyntaxError as e:
            pytest.fail(f"Syntax error in {py_file.name}: {e}")


def test_list_spawns_returns_correct_info_after_generate(tmp_path, sample_blueprint):
    manager = SpawnManager(spawns_dir=tmp_path)
    manager.generate(sample_blueprint)

    spawns = manager.list_spawns()
    assert len(spawns) == 1

    entry = spawns[0]
    assert entry["name"] == "test-spawn"
    assert "path" in entry
    assert Path(entry["path"]).exists()


def test_list_spawns_returns_empty_when_no_spawns(tmp_path):
    manager = SpawnManager(spawns_dir=tmp_path)
    assert manager.list_spawns() == []


def test_get_spawn_path_returns_path_when_exists(tmp_path, sample_blueprint):
    manager = SpawnManager(spawns_dir=tmp_path)
    manager.generate(sample_blueprint)

    result = manager.get_spawn_path("test-spawn")
    assert result is not None
    assert result.exists()
    assert result.name == "test-spawn"


def test_get_spawn_path_returns_none_when_missing(tmp_path):
    manager = SpawnManager(spawns_dir=tmp_path)
    assert manager.get_spawn_path("nonexistent") is None


def test_generate_creates_meta_with_correct_fields(tmp_path, sample_blueprint):
    import yaml

    manager = SpawnManager(spawns_dir=tmp_path)
    spawn_path = manager.generate(sample_blueprint)

    meta_path = spawn_path / ".arslan-meta.yaml"
    meta = yaml.safe_load(meta_path.read_text())

    assert meta["name"] == "test-spawn"
    assert meta["domain"] == "content-creator.xiaohongshu"
    assert meta["template_used"] == "content-creator.xiaohongshu"
    assert "generation_level" in meta


def test_generate_creates_spawns_dir_if_missing(tmp_path, sample_blueprint):
    new_dir = tmp_path / "deep" / "nested" / "spawns"
    manager = SpawnManager(spawns_dir=new_dir)
    spawn_path = manager.generate(sample_blueprint)
    assert spawn_path.exists()

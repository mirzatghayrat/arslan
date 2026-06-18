"""Tests for SpawnManager.generate_skillpack — P1 skill-pack generation."""
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
from arslan.spawn.skillpack import SkillPack, validate_skillpack


@pytest.fixture
def blueprint() -> SpawnBlueprint:
    return SpawnBlueprint(
        requirements=SpawnRequirements(
            spawn_name="github-eval",
            domain=DomainInfo(category="developer-tools", subcategory="github"),
            capabilities=["repo-evaluation", "need-matching"],
            persona=PersonaSpec(
                role="GitHub 仓库评估助手",
                tone="客观严谨",
                constraints=[
                    "先看 stars / 活跃度 / license",
                    "碰钱的工具必须用户批准",
                ],
            ),
            runtime=RuntimeSpec(platform="cli"),
            research_results={"summary": "agent skill 生态正在标准化（agentskills.io）"},
        ),
        tools=[
            ToolSpec(
                name="gh-api",
                description="GitHub API 只读查询",
                input_schema={"repo": {"type": "string"}},
                output_schema={"stars": {"type": "integer"}},
            )
        ],
        system_prompt="你是一个只做 GitHub 仓库评估和匹配的助手。",
        workflow_steps=[],
        template_used="developer-tools.github",
    )


def test_generate_skillpack_creates_pack_files(tmp_path, blueprint):
    mgr = SpawnManager(spawns_dir=tmp_path)
    pack = mgr.generate_skillpack(blueprint)
    assert (pack / "SKILL.md").exists()
    clis = list((pack / "scripts").glob("*_cli.py"))
    assert len(clis) == 1


def test_generated_skillpack_passes_validation(tmp_path, blueprint):
    mgr = SpawnManager(spawns_dir=tmp_path)
    pack = mgr.generate_skillpack(blueprint)
    results = validate_skillpack(pack)
    for r in results:
        assert r.passed is True, f"{r.name}: {r.message}"


def test_generated_skill_md_frontmatter_and_sections(tmp_path, blueprint):
    mgr = SpawnManager(spawns_dir=tmp_path)
    pack = mgr.generate_skillpack(blueprint)
    sp = SkillPack.from_skill_md((pack / "SKILL.md").read_text(encoding="utf-8"))
    assert sp.name == "github-eval"
    assert sp.version
    assert sp.has_section("Trigger")
    assert sp.has_section("决策规则")


def test_research_summary_injected_into_body(tmp_path, blueprint):
    mgr = SpawnManager(spawns_dir=tmp_path)
    pack = mgr.generate_skillpack(blueprint)
    body = (pack / "SKILL.md").read_text(encoding="utf-8")
    assert "agentskills.io" in body


def test_persona_constraints_become_decision_rules(tmp_path, blueprint):
    mgr = SpawnManager(spawns_dir=tmp_path)
    pack = mgr.generate_skillpack(blueprint)
    body = (pack / "SKILL.md").read_text(encoding="utf-8")
    assert "stars" in body


def test_heavy_runtime_path_still_available(tmp_path, blueprint):
    # P1.4: the old heavy-spawn path is preserved as an explicit option.
    mgr = SpawnManager(spawns_dir=tmp_path)
    pack = mgr.generate(blueprint)
    assert (pack / "agent.py").exists()

"""Tests for Tier-2 capability reflection into SKILL.md (P3)."""
from arslan.models import (
    DomainInfo,
    PersonaSpec,
    SpawnBlueprint,
    SpawnRequirements,
)
from arslan.spawn.evolve import apply_tier2_capabilities
from arslan.spawn.manager import SpawnManager
from arslan.spawn.skillpack import validate_skillpack


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


def test_reflects_equipment_section(tmp_path):
    pack = _pack(tmp_path)
    changed = apply_tier2_capabilities(pack, [{"key": "web-search", "description": "搜索"}])
    assert changed is True
    body = (pack / "SKILL.md").read_text(encoding="utf-8")
    assert "已装备能力" in body
    assert "web-search" in body
    assert "arslan:equipment:start" in body


def test_tier2_idempotent(tmp_path):
    pack = _pack(tmp_path)
    apply_tier2_capabilities(pack, [{"key": "web-search"}])
    first = (pack / "SKILL.md").read_text(encoding="utf-8")
    apply_tier2_capabilities(pack, [{"key": "web-search"}])
    second = (pack / "SKILL.md").read_text(encoding="utf-8")
    assert first == second
    assert second.count("arslan:equipment:start") == 1


def test_tier2_updates_on_change(tmp_path):
    pack = _pack(tmp_path)
    apply_tier2_capabilities(pack, [{"key": "web-search"}])
    apply_tier2_capabilities(pack, [{"key": "web-search"}, {"key": "image-gen"}])
    body = (pack / "SKILL.md").read_text(encoding="utf-8")
    assert "image-gen" in body
    assert body.count("arslan:equipment:start") == 1


def test_tier2_does_not_touch_scripts(tmp_path):
    pack = _pack(tmp_path)
    before = {p.name: p.read_bytes() for p in (pack / "scripts").iterdir()}
    apply_tier2_capabilities(pack, [{"key": "web-search"}])
    after = {p.name: p.read_bytes() for p in (pack / "scripts").iterdir()}
    assert before == after


def test_tier2_pack_still_valid(tmp_path):
    pack = _pack(tmp_path)
    apply_tier2_capabilities(pack, [{"key": "web-search", "description": "搜索"}])
    for r in validate_skillpack(pack):
        assert r.passed is True, f"{r.name}: {r.message}"

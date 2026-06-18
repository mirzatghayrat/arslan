"""The bundled seed spawns must be valid skill-packs (P6)."""
from pathlib import Path

import pytest

import arslan.spawn
from arslan.spawn.skillpack import SkillPack, validate_skillpack

SEEDS = Path(arslan.spawn.__file__).parent / "seeds"


@pytest.mark.parametrize("name", ["research", "github-eval"])
def test_seed_spawn_is_valid(name):
    pack = SEEDS / name
    assert pack.is_dir(), f"seed pack missing: {pack}"
    for r in validate_skillpack(pack):
        assert r.passed is True, f"{name}/{r.name}: {r.message}"


@pytest.mark.parametrize("name", ["research", "github-eval"])
def test_seed_spawn_frontmatter_parses(name):
    pack = SEEDS / name
    sp = SkillPack.from_skill_md((pack / "SKILL.md").read_text(encoding="utf-8"))
    assert sp.name
    assert sp.has_section("Trigger")
    assert sp.has_section("决策规则")

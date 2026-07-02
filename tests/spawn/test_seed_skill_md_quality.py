from pathlib import Path

import pytest

import arslan.spawn
from arslan.spawn.skillpack import SkillPack

_SEEDS = Path(arslan.spawn.__file__).parent / "seeds"

# The curated pure-LLM-technique skills that must carry a real SKILL.md body.
AUTHORED = [
    "systematic-debugging", "plan", "codebase-audit", "github-code-review", "design-md",
    "architecture-diagram", "humanizer", "ascii-art", "baoyu-infographic", "sketch", "claude-design",
    "designed-html-report",
]


@pytest.mark.parametrize("key", AUTHORED)
def test_authored_skill_md_is_valid(key):
    md = _SEEDS / key / "SKILL.md"
    assert md.exists(), f"missing seeds/{key}/SKILL.md"
    pack = SkillPack.from_skill_md(md.read_text(encoding="utf-8"))
    assert pack.name and pack.description and pack.version
    assert pack.has_section("Trigger"), f"{key} body missing ## Trigger"
    assert pack.has_section("决策规则"), f"{key} body missing ## 决策规则"
    assert len(pack.body.strip()) >= 200, f"{key} body too thin to be useful"

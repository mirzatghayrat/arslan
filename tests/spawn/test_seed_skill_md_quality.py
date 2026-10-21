from pathlib import Path

import pytest

import arslan.skills
from arslan.skills.skillpack import SkillPack

_SEEDS = Path(arslan.skills.__file__).parent / "bundled"

# The skills Arslan ships with (C9, v0.1.63): each must carry a real SKILL.md body.
AUTHORED = ["designed-html-report", "skill-creator"]


@pytest.mark.parametrize("key", AUTHORED)
def test_authored_skill_md_is_valid(key):
    md = _SEEDS / key / "SKILL.md"
    assert md.exists(), f"missing bundled/{key}/SKILL.md"
    pack = SkillPack.from_skill_md(md.read_text(encoding="utf-8"))
    assert pack.name and pack.description and pack.version
    assert pack.has_section("Trigger"), f"{key} body missing ## Trigger"
    assert pack.has_section("决策规则"), f"{key} body missing ## 决策规则"
    assert len(pack.body.strip()) >= 200, f"{key} body too thin to be useful"

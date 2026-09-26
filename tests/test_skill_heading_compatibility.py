"""The English UI must not require Chinese syntax; old packs stay readable."""
import pytest

from arslan.spawn.skillpack import REQUIRED_SECTIONS, SkillPack, has_body_section
from server.services.skill_suggest import has_required_sections


@pytest.mark.parametrize("heading", ["Decision Rules", "决策规则"])
def test_both_skill_formats_remain_valid(heading):
    body = f"## Trigger\nWhen needed\n## {heading}\n- Check evidence"
    pack = SkillPack(name="test", description="test", version="1", body=body)
    assert all(pack.has_section(title) for title in REQUIRED_SECTIONS)
    assert has_required_sections(body)


@pytest.mark.parametrize("body", [
    "Mention ## Trigger and ## Decision Rules in a sentence.",
    "## Trigger\n## Decision Rules Extra",
    "## Decision Rules\nNo trigger heading.",
])
def test_prose_and_partial_headings_do_not_satisfy_contract(body):
    assert not has_required_sections(body)


def test_unrelated_headings_are_not_aliased():
    assert not has_body_section("## 决策规则", "Trigger")

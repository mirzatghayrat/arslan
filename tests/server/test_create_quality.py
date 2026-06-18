"""Create-time quality guards: capability normalization + decision-rule fallback."""
from arslan.models import (
    DomainInfo,
    PersonaSpec,
    SpawnBlueprint,
    SpawnRequirements,
)
from arslan.spawn.manager import SpawnManager
from server.services.spawn_service import normalize_capabilities


def test_normalize_capabilities_caps_count():
    many = "a,b,c,d,e,f,g,h,i,j"
    out = normalize_capabilities(many)
    assert len(out) <= 6


def test_normalize_capabilities_drops_sentence_like_entries():
    val = [
        "内容生成",
        "这是一段非常长的描述性句子用来塞满能力字段它完全不像一个简洁的能力短语理应被丢弃掉以免污染触发行",
    ]
    out = normalize_capabilities(val)
    assert "内容生成" in out
    assert all(len(c) <= 40 for c in out)


def test_normalize_capabilities_preserves_normal_list():
    assert normalize_capabilities(["内容生成", "热点调研"]) == ["内容生成", "热点调研"]


def test_decision_rules_fall_back_to_capabilities_when_no_constraints(tmp_path):
    bp = SpawnBlueprint(
        requirements=SpawnRequirements(
            spawn_name="x",
            domain=DomainInfo(category="content", subcategory="beauty"),
            capabilities=["内容生成", "热点调研"],
            persona=PersonaSpec(role="助手"),  # no constraints
        ),
        tools=[],
        system_prompt="你是助手。",
        workflow_steps=[],
    )
    pack = SpawnManager(spawns_dir=tmp_path).generate_skillpack(bp)
    body = (pack / "SKILL.md").read_text(encoding="utf-8")
    # The 决策规则 section is no longer empty: capabilities surface as bullet rules.
    assert "- 内容生成" in body
    assert "- 热点调研" in body


def test_decision_rules_prefer_explicit_constraints(tmp_path):
    bp = SpawnBlueprint(
        requirements=SpawnRequirements(
            spawn_name="x",
            domain=DomainInfo(category="content"),
            capabilities=["内容生成"],
            persona=PersonaSpec(role="助手", constraints=["标题用悬念型"]),
        ),
        tools=[],
        system_prompt="你是助手。",
        workflow_steps=[],
    )
    pack = SpawnManager(spawns_dir=tmp_path).generate_skillpack(bp)
    body = (pack / "SKILL.md").read_text(encoding="utf-8")
    assert "- 标题用悬念型" in body  # explicit constraints win

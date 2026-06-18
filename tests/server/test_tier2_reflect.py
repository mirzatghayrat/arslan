"""Server reflects a spawn's equipment into SKILL.md (P3 Tier-2 wiring)."""
from arslan.spawn.skillpack import validate_skillpack
from server.services.spawn_service import emit_skillpack, reflect_equipment


def test_reflect_equipment_writes_section(tmp_path):
    draft = {"name": "w", "domain": "content.xhs", "capabilities": ["x"], "persona_role": "写手"}
    emit_skillpack(tmp_path, "w", draft, "你是写手。")
    eq = {
        "toolsets": [{"key": "web_search", "description": "网页搜索"}],
        "skills": [{"key": "infographic", "description": "图文"}],
    }
    changed = reflect_equipment(tmp_path, "w", eq)
    assert changed is True
    body = (tmp_path / "w" / "SKILL.md").read_text(encoding="utf-8")
    assert "已装备能力" in body
    assert "web_search" in body
    assert "infographic" in body
    for r in validate_skillpack(tmp_path / "w"):
        assert r.passed is True, f"{r.name}: {r.message}"


def test_reflect_empty_equipment(tmp_path):
    draft = {"name": "w", "domain": "other", "capabilities": []}
    emit_skillpack(tmp_path, "w", draft, "你是助手。")
    changed = reflect_equipment(tmp_path, "w", {"toolsets": [], "skills": []})
    assert changed is True
    body = (tmp_path / "w" / "SKILL.md").read_text(encoding="utf-8")
    assert "暂无装备能力" in body

"""Server evolution path injects rules into the on-disk SKILL.md (P2)."""
import dataclasses

from server import config
from server.services import evolution_service, spawn_service


def test_record_feedback_injects_into_skill_md(tmp_path, monkeypatch):
    monkeypatch.setattr(
        config, "settings", dataclasses.replace(config.settings, spawns_dir=tmp_path)
    )
    draft = {
        "name": "writer",
        "domain": "content.xhs",
        "capabilities": ["write"],
        "persona_role": "小红书写手",
    }
    spawn_service.emit_skillpack(tmp_path, "writer", draft, "你是小红书写手。")

    for i in range(22):
        evolution_service.record_feedback(
            "writer",
            session_id=f"s{i}",
            user_input="x",
            agent_output="y",
            user_action="edit",
            edits={"title": "改"},
        )

    skill = (tmp_path / "writer" / "SKILL.md").read_text(encoding="utf-8")
    assert "arslan:evolution:start" in skill

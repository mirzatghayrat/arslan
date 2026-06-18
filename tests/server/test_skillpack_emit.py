"""Tests for server-side skill-pack file emission on create (P2, storage model A)."""
from arslan.spawn.skillpack import validate_skillpack
from server.services.spawn_service import emit_skillpack


def test_emit_skillpack_writes_valid_pack(tmp_path):
    draft = {
        "name": "writer",
        "domain": "content.xhs",
        "capabilities": ["write"],
        "persona_role": "小红书写手",
        "persona_tone": "亲切",
    }
    pack = emit_skillpack(tmp_path, "writer", draft, "你是小红书写手。")
    assert (pack / "SKILL.md").exists()
    assert list((pack / "scripts").glob("*_cli.py"))
    for r in validate_skillpack(pack):
        assert r.passed is True, f"{r.name}: {r.message}"


def test_emit_skillpack_handles_missing_persona(tmp_path):
    draft = {"name": "bot", "domain": "other", "capabilities": []}
    pack = emit_skillpack(tmp_path, "bot", draft, "你是一个助手。")
    for r in validate_skillpack(pack):
        assert r.passed is True, f"{r.name}: {r.message}"

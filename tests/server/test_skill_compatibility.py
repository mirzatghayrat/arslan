"""PC-4: per-skill sandbox-compatibility classification + the one-time anti-fabrication
preamble at the top of the injected techniques section.

skill_compatibility(key, body) is deterministic and HONEST — "full" only when every
bundled script is runnable in the sandbox exactly as shipped."""
from server.db.models import SkillPack
from server.orchestrator.dispatcher import (
    _TECHNIQUE_HONESTY_PREAMBLE,
    _equipment_block_from,
)
from server.registry import service


def _pack(key: str, body: str = "## X\nuse it") -> SkillPack:
    return SkillPack(key=key, name=key.title(), category="x", description="d",
                     tier="safe", status="registered", body=body)


# ── Part A: compatibility classification ─────────────────────────────────────────────

def test_text_only_skill_is_text(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    # no skill_scripts dir at all
    assert service.skill_compatibility("plain", "## Method\njust prose") == "text"
    # empty scripts dir is also text
    (tmp_path / "skill_scripts" / "emptydir").mkdir(parents=True)
    assert service.skill_compatibility("emptydir", "body") == "text"


def test_references_only_is_partial(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    refs = tmp_path / "skill_scripts" / "docskill" / "references"
    refs.mkdir(parents=True)
    (refs / "guide.md").write_text("# guide", encoding="utf-8")
    assert service.skill_has_references("docskill") is True
    assert service.skill_has_scripts("docskill") is False   # references/ ≠ scripts
    assert service.skill_compatibility("docskill", "body") == "partial"


def test_clean_py_scripts_are_full(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    d = tmp_path / "skill_scripts" / "runner"
    d.mkdir(parents=True)
    (d / "entry.py").write_text("print('hi')", encoding="utf-8")
    (d / "helper.py").write_text("X = 1", encoding="utf-8")
    assert service.skill_compatibility("runner", "body") == "full"


def test_clean_py_scripts_with_references_still_full(tmp_path, monkeypatch):
    """Bundled references are mounted read-only by the sandbox (PC-3 ②), so runnable
    scripts + refs = everything works = full."""
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    d = tmp_path / "skill_scripts" / "both"
    d.mkdir(parents=True)
    (d / "entry.py").write_text("print('ok')", encoding="utf-8")
    refs = d / "references"
    refs.mkdir()
    (refs / "notes.md").write_text("# notes", encoding="utf-8")
    assert service.skill_compatibility("both", "body") == "full"


def test_non_py_script_is_partial(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    d = tmp_path / "skill_scripts" / "mixed"
    d.mkdir(parents=True)
    (d / "entry.py").write_text("print('hi')", encoding="utf-8")
    (d / "run.sh").write_text("echo hi", encoding="utf-8")   # non-.py → constrained
    assert service.skill_compatibility("mixed", "body") == "partial"


def test_requires_marker_is_partial(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    for marker in ("# requires: network", "# requires: cli"):
        key = "needs" + marker.split()[-1]
        d = tmp_path / "skill_scripts" / key
        d.mkdir(parents=True)
        (d / "entry.py").write_text(marker + "\nprint('x')", encoding="utf-8")
        assert service.skill_compatibility(key, "body") == "partial", marker


def test_unreadable_script_downgrades_to_partial(tmp_path, monkeypatch):
    """A non-UTF-8 .py entry can't be verified → we refuse to promise full."""
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    d = tmp_path / "skill_scripts" / "binary"
    d.mkdir(parents=True)
    (d / "entry.py").write_bytes(b"\xff\xfe\x00bad")
    assert service.skill_compatibility("binary", "body") == "partial"


def test_skill_dict_carries_compatibility(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    d = tmp_path / "skill_scripts" / "runner"
    d.mkdir(parents=True)
    (d / "entry.py").write_text("print('hi')", encoding="utf-8")
    assert service._skill_dict(_pack("runner"))["compatibility"] == "full"
    assert service._skill_dict(_pack("plain"))["compatibility"] == "text"


# ── Part B: one-time anti-fabrication preamble ───────────────────────────────────────

def test_preamble_present_exactly_once_when_skills_equipped(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    equipment = {"toolsets": [], "skills": [
        service._skill_dict(_pack("a")),
        service._skill_dict(_pack("b")),
    ]}
    bodies = {"a": "## X\nalpha technique", "b": "## Y\nbeta technique"}
    block = _equipment_block_from(equipment, [], bodies)
    assert block.count(_TECHNIQUE_HONESTY_PREAMBLE) == 1
    # preamble sits above the per-skill blocks
    assert block.index(_TECHNIQUE_HONESTY_PREAMBLE) < block.index("alpha technique")


def test_preamble_absent_when_no_skills_equipped(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    equipment = {"toolsets": [], "skills": []}
    block = _equipment_block_from(equipment, [], {})
    assert _TECHNIQUE_HONESTY_PREAMBLE not in block
    assert "Your techniques:" not in block

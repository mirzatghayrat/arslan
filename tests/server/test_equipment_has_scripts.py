"""PC1-c Part B: the equipment skill dict carries has_scripts, computed from the
data_dir/skill_scripts/<key>/ dir that RunPythonExecutor._load_skill_script resolves
against. So _equipment_block_from emits the run-hint line for script-bearing skills
and omits it for scriptless ones."""
from server.db.models import SkillPack
from server.orchestrator.dispatcher import _equipment_block_from
from server.registry import service


def _pack(key: str) -> SkillPack:
    return SkillPack(key=key, name=key.title(), category="x", description="d",
                     tier="safe", status="registered", body="## X\nuse it")


def test_skill_has_scripts_detects_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    d = tmp_path / "skill_scripts" / "withscripts"
    d.mkdir(parents=True)
    (d / "entry.py").write_text("x = 1", encoding="utf-8")
    assert service.skill_has_scripts("withscripts") is True
    assert service.skill_has_scripts("noscripts") is False


def test_skill_has_scripts_empty_dir_is_false(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    (tmp_path / "skill_scripts" / "emptydir").mkdir(parents=True)
    assert service.skill_has_scripts("emptydir") is False
    assert service.skill_has_scripts("") is False


def test_equipment_block_run_hint_fires_for_script_bearing_skill(tmp_path, monkeypatch):
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    d = tmp_path / "skill_scripts" / "handoff"
    d.mkdir(parents=True)
    (d / "run.py").write_text("print('hi')", encoding="utf-8")

    equipment = {"toolsets": [], "skills": [
        service._skill_dict(_pack("handoff")),   # has_scripts True
        service._skill_dict(_pack("plain")),     # no dir → False
    ]}
    bodies = {"handoff": "## X\nrun it", "plain": "## X\njust prose"}
    # run_python wired → the run hint fires for the script skill.
    wired = [{"key": "run_python", "description": "run python"}]
    block = _equipment_block_from(equipment, wired, bodies)
    assert "skill_script" in block and "handoff/" in block   # run hint for the script skill
    assert "plain/`" not in block                            # no run-hint path for the scriptless one


def test_equipment_block_run_hint_gated_off_when_run_python_unwired(tmp_path, monkeypatch):
    """PC compat fix: without run_python wired, the script skill gets an honest 'needs Code
    Sandbox' note instead of a dead-end run_python pointer."""
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    d = tmp_path / "skill_scripts" / "handoff"
    d.mkdir(parents=True)
    (d / "run.py").write_text("print('hi')", encoding="utf-8")

    equipment = {"toolsets": [], "skills": [service._skill_dict(_pack("handoff"))]}
    bodies = {"handoff": "## X\nrun it"}
    block = _equipment_block_from(equipment, [], bodies)   # nothing wired
    # the actionable run pointer is gone (the preamble may still name the tool generically)
    assert "skill_script" not in block
    assert "handoff/" not in block
    assert "跑脚本需装备 Code Sandbox 工具集" in block

"""PC1-c Part B: the equipment skill dict carries has_scripts, computed from the
data_dir/skill_scripts/<key>/ dir that RunPythonExecutor._load_skill_script resolves
against. So _equipment_block_from emits the run-hint line for script-bearing skills
and omits it for scriptless ones."""
from server.registry import service


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

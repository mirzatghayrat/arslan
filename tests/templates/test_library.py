"""Tests for TemplateConfig and TemplateLibrary."""
from pathlib import Path

import yaml

from arslan.templates.library import TemplateConfig, TemplateLibrary


# ---------------------------------------------------------------------------
# TemplateConfig tests
# ---------------------------------------------------------------------------


def test_from_yaml_loads_correctly(tmp_path: Path) -> None:
    """TemplateConfig.from_yaml loads all fields and sets path to parent dir."""
    yaml_data = {
        "name": "Test Template",
        "domain": "test.category",
        "description": "A test template",
        "keywords": ["test", "demo"],
        "variables": {"foo": {"ask": "What?", "type": "text"}},
        "tools": [{"name": "llm-caller", "source": "builtin://llm-caller"}],
        "workflow": [{"step": 1, "action": "generate"}],
        "platforms": ["web", "mobile"],
    }
    yaml_file = tmp_path / "template.yaml"
    yaml_file.write_text(yaml.dump(yaml_data, allow_unicode=True), encoding="utf-8")

    config = TemplateConfig.from_yaml(yaml_file)

    assert config.name == "Test Template"
    assert config.domain == "test.category"
    assert config.description == "A test template"
    assert config.keywords == ["test", "demo"]
    assert "foo" in config.variables
    assert len(config.tools) == 1
    assert len(config.workflow) == 1
    assert config.platforms == ["web", "mobile"]
    assert config.path == str(tmp_path)


def test_from_yaml_sets_path_to_parent(tmp_path: Path) -> None:
    """path is set to the directory containing the YAML file."""
    subdir = tmp_path / "mytemplate"
    subdir.mkdir()
    yaml_file = subdir / "template.yaml"
    yaml_file.write_text(
        yaml.dump({"name": "X", "domain": "a.b"}, allow_unicode=True),
        encoding="utf-8",
    )
    config = TemplateConfig.from_yaml(yaml_file)
    assert config.path == str(subdir)


def test_domain_tags_splits_on_dot() -> None:
    """domain_tags splits the domain string by '.'."""
    config = TemplateConfig(name="T", domain="content-creator.xiaohongshu")
    assert config.domain_tags == ["content-creator", "xiaohongshu"]


def test_domain_tags_single_segment() -> None:
    """domain_tags with a single-segment domain returns a single-element list."""
    config = TemplateConfig(name="T", domain="personal-assistant")
    assert config.domain_tags == ["personal-assistant"]


def test_template_config_defaults() -> None:
    """TemplateConfig defaults apply when optional fields are absent."""
    config = TemplateConfig(name="Minimal", domain="test")
    assert config.description == ""
    assert config.keywords == []
    assert config.variables == {}
    assert config.tools == []
    assert config.workflow == []
    assert config.platforms == ["web"]
    assert config.path == ""


# ---------------------------------------------------------------------------
# TemplateLibrary tests
# ---------------------------------------------------------------------------


def test_load_official_finds_at_least_one_template() -> None:
    """load_official loads at least the bundled official templates."""
    lib = TemplateLibrary()
    lib.load_official()
    assert len(lib.list_all()) >= 1


def test_load_official_loads_xiaohongshu() -> None:
    """The xiaohongshu template is present after load_official."""
    lib = TemplateLibrary()
    lib.load_official()
    names = [t.name for t in lib.list_all()]
    assert "小红书内容创作" in names


def test_load_official_loads_translator() -> None:
    """The translator template is present after load_official."""
    lib = TemplateLibrary()
    lib.load_official()
    names = [t.name for t in lib.list_all()]
    assert "翻译助手" in names


def test_search_by_domain_exact_match() -> None:
    """search_by_domain returns templates with an exact domain match."""
    lib = TemplateLibrary()
    lib.load_official()
    results = lib.search_by_domain("content-creator.xiaohongshu")
    assert any(t.domain == "content-creator.xiaohongshu" for t in results)


def test_search_by_domain_partial_match() -> None:
    """search_by_domain with parent prefix matches child domains."""
    lib = TemplateLibrary()
    lib.load_official()
    results = lib.search_by_domain("content-creator")
    # Should include xiaohongshu which starts with 'content-creator'
    assert len(results) >= 1
    assert all(t.domain.startswith("content-creator") for t in results)


def test_search_by_query_keyword() -> None:
    """search() finds templates whose keywords contain the query string."""
    lib = TemplateLibrary()
    lib.load_official()
    results = lib.search("小红书")
    assert len(results) >= 1
    assert any(t.name == "小红书内容创作" for t in results)


def test_search_is_case_insensitive() -> None:
    """search() is case-insensitive for ASCII queries."""
    lib = TemplateLibrary()
    lib.add(TemplateConfig(name="My Agent", domain="test", description="HELLO WORLD"))
    results = lib.search("hello")
    assert len(results) == 1
    assert results[0].name == "My Agent"


def test_search_by_name_substring() -> None:
    """search() matches on name substring."""
    lib = TemplateLibrary()
    lib.add(TemplateConfig(name="翻译助手", domain="personal-assistant.translator"))
    results = lib.search("翻译")
    assert len(results) == 1


def test_add_and_list_all() -> None:
    """add() appends a template; list_all() returns all templates."""
    lib = TemplateLibrary()
    t1 = TemplateConfig(name="A", domain="x")
    t2 = TemplateConfig(name="B", domain="y")
    lib.add(t1)
    lib.add(t2)
    all_templates = lib.list_all()
    assert len(all_templates) == 2
    assert t1 in all_templates
    assert t2 in all_templates


def test_load_official_skips_malformed(tmp_path: Path, monkeypatch) -> None:
    """load_official skips template.yaml files that fail to parse."""
    import arslan.templates.library as lib_module

    # Point OFFICIAL_DIR to a temp dir with one broken template
    bad_dir = tmp_path / "bad-template"
    bad_dir.mkdir(parents=True)
    (bad_dir / "template.yaml").write_text(
        "name: [invalid yaml: :", encoding="utf-8"
    )

    monkeypatch.setattr(lib_module, "OFFICIAL_DIR", tmp_path)
    lib = TemplateLibrary()
    lib.load_official()  # Should not raise
    assert lib.list_all() == []

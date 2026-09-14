import json
from pathlib import Path

from server.registry.display import skill_display_keys, toolset_display_keys
from server.registry.seed_catalog import SKILLS, TOOLSETS


def test_builtin_display_keys_leave_custom_text_untouched():
    for row in TOOLSETS:
        keys = toolset_display_keys(row["key"], row["name"], row["description"])
        assert keys == {
            "name_key": f"catalogUI.{row['key']}.name",
            "description_key": f"catalogUI.{row['key']}.description",
        }
        assert toolset_display_keys(row["key"], "My name", "My description") == {
            "name_key": None, "description_key": None,
        }
        assert toolset_display_keys(row["key"], "My name", row["description"])["description_key"]
    assert toolset_display_keys("custom", "File Operations", "custom") == {
        "name_key": None, "description_key": None,
    }


def test_skill_display_hints_do_not_relabel_user_edits():
    for key, name, _, description, *_ in SKILLS:
        assert skill_display_keys(key, name, description) == {
            "name_key": f"catalogUI.skills.{key}.name", "description_key": f"catalogUI.skills.{key}.description",
        }
        assert skill_display_keys(key, "My label", description)["name_key"] is None
        assert skill_display_keys(key, name, "My explanation")["description_key"] is None
    assert skill_display_keys("custom", "skill-creator", "My method") == {"name_key": None, "description_key": None}


def test_every_seed_skill_has_six_complete_display_records():
    locales = Path(__file__).resolve().parents[2] / "web" / "src" / "locales"
    expected = {row[0] for row in SKILLS}
    for language in ("en", "zh", "ja", "es", "de", "fr"):
        data = json.loads((locales / f"skills-{language}.json").read_text())
        assert set(data) == expected
        for value in data.values():
            assert set(value) == {"name", "description"}
            assert all(isinstance(text, str) and text.strip() for text in value.values())

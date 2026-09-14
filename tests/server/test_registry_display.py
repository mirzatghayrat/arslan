from server.registry.display import toolset_display_keys
from server.registry.seed_catalog import TOOLSETS


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

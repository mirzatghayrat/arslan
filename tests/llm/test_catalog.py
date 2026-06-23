from arslan.llm import catalog
from arslan.llm.presets import PRESETS, NATIVE


def test_catalog_covers_every_provider():
    expected = set(PRESETS) | set(NATIVE)
    assert set(catalog.CATALOG) == expected


def test_every_entry_has_models_capabilities_languages():
    for key, entry in catalog.CATALOG.items():
        assert entry["models"], f"{key} has no models"
        for dim in catalog.CAPABILITY_DIMENSIONS:
            assert 0 <= entry["capabilities"][dim] <= 10, f"{key}.{dim} out of range"
        assert entry["languages"], f"{key} has no languages map"


def test_models_for_and_capabilities_for():
    assert "qwen-max" in catalog.models_for("qwen")
    assert catalog.models_for("nope") == []
    caps = catalog.capabilities_for("anthropic")
    assert caps["reasoning"] == 10


def test_language_fit_resolves_and_defaults():
    assert catalog.language_fit("qwen", "zh") == 9
    assert catalog.language_fit("qwen", None) == catalog.DEFAULT_LANGUAGE_FIT
    assert catalog.language_fit("qwen", "xx") == catalog.DEFAULT_LANGUAGE_FIT
    assert catalog.language_fit("unknown-provider", "en") == catalog.DEFAULT_LANGUAGE_FIT

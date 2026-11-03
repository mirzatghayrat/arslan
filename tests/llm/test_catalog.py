from arslan.llm import catalog
from arslan.llm.presets import PRESETS, NATIVE


def test_catalog_covers_every_provider():
    expected = set(PRESETS) | set(NATIVE)
    assert set(catalog.CATALOG) == expected


def test_every_cloud_provider_has_seed_models():
    for key, entry in catalog.CATALOG.items():
        # B5: ollama ships NO seed models — the dynamic list (/api/tags) is the
        # only honest source; every cloud provider still needs a static fallback.
        if key != "ollama":
            assert entry["models"], f"{key} has no models"


def test_models_for():
    assert "qwen3.7-max" in catalog.models_for("qwen")
    assert catalog.models_for("nope") == []


def test_the_catalog_carries_models_only():
    """ROUTE1 (v0.1.64): no capability scores or language map are left for a routing engine to read."""
    assert all(set(entry) == {"models"} for entry in catalog.CATALOG.values())
    assert not hasattr(catalog, "capabilities_for") and not hasattr(catalog, "language_fit")

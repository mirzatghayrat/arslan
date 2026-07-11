"""Seed-catalog freshness guards (Provider spec D2, 2026-07-11).

The seed catalog ships in releases and is NOT fetched remotely, so a model id
with a known shutdown date (or an already-retired generation) must never be in
it. The deny list below was verified against official deprecation pages on
2026-07-11 (see docs/superpowers/specs/2026-07-11-provider-catalog-local-models-design.md
Part A2). Growing this list is fine; shrinking it needs a source.
"""
from arslan.llm.catalog import CATALOG, models_for
from arslan.llm.presets import NATIVE, PRESETS

# Retired today — these ids hard-fail at the API.
DEAD = {
    "claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307",
    "claude-3-5-sonnet-20240620", "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022",
    "claude-3-7-sonnet-20250219", "claude-opus-4-20250514", "claude-sonnet-4-20250514",
    "gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-pro", "gemini-1.5-flash",
    "gpt-4.5-preview",
}

# Announced shutdown dates or deprecated aliases — must not ship in a fresh seed.
DYING = {
    "deepseek-chat", "deepseek-reasoner",            # re-pointed/deprecated 2026-07-24
    "gpt-4o", "gpt-4o-mini", "gpt-4", "gpt-4-turbo", # shutdown 2026-10-23
    "gpt-3.5-turbo", "o1", "o4-mini", "gpt-4.1-mini", "gpt-4.1-nano",
    "o3",                                            # shutdown 2026-12-11
    "claude-opus-4-1-20250805",                      # shutdown 2026-08-05
    "openai/gpt-4o",                                 # openrouter slug of the above
}

# Retired generations (successor lines shipped 2025-2026) — stale in a fresh seed.
STALE_GEN = {
    "llama3",                                        # 2024 llama-3 8B ollama tag
    "glm-4", "glm-4-air", "glm-4-flash",
    "abab6.5s-chat", "abab6.5-chat",
    "moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k",
}

DENY = DEAD | DYING | STALE_GEN


def _all_seed_ids() -> set[str]:
    ids: set[str] = set()
    for provider in CATALOG:
        ids.update(models_for(provider))
    for p in PRESETS.values():
        ids.add(p["default_model"])
    for p in NATIVE.values():
        ids.add(p["default_model"])
    return ids


def test_seed_contains_no_dead_or_dying_model_ids():
    shipped = _all_seed_ids()
    offenders = sorted(shipped & DENY)
    assert not offenders, f"seed catalog ships dead/dying/stale model ids: {offenders}"


def test_every_preset_default_model_is_in_its_catalog_list():
    # catalog<->presets alignment was previously enforced only by comment convention
    # (catalog.py:47); make the default-model half of it executable.
    for key, p in {**PRESETS, **NATIVE}.items():
        assert p["default_model"] in models_for(key), (
            f"{key}: default_model {p['default_model']!r} not in catalog models {models_for(key)}"
        )

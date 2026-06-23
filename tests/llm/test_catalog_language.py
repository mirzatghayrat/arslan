"""TDD tests for Bug 1: language_fit must handle display strings + 6 UI locales."""
from arslan.llm.catalog import (
    CATALOG,
    DEFAULT_LANGUAGE_FIT,
    language_fit,
    normalize_language,
)

# The exact <option value="..."> strings from web/src/components/SettingsScreen.tsx
DISPLAY_STRINGS = {
    "English (US)": "en",
    "Chinese (Simplified)": "zh",
    "Japanese": "ja",
    "German": "de",
}

# All 6 UI locale ISO codes (en, zh, de, es, fr, ja)
UI_LOCALES = {"en", "zh", "de", "es", "fr", "ja"}


class TestNormalizeLanguage:
    """normalize_language must map display strings and ISO codes to ISO codes."""

    def test_iso_codes_pass_through(self):
        assert normalize_language("en") == "en"
        assert normalize_language("zh") == "zh"
        assert normalize_language("de") == "de"
        assert normalize_language("es") == "es"
        assert normalize_language("fr") == "fr"
        assert normalize_language("ja") == "ja"

    def test_display_strings_resolve_to_iso(self):
        for display, iso in DISPLAY_STRINGS.items():
            assert normalize_language(display) == iso, (
                f"Expected normalize_language({display!r}) == {iso!r}"
            )

    def test_none_returns_none(self):
        assert normalize_language(None) is None

    def test_unknown_string_returns_none(self):
        assert normalize_language("Klingon") is None
        assert normalize_language("xx") is None
        assert normalize_language("") is None


class TestLanguageFitWithDisplayStrings:
    """language_fit must work with both display strings AND ISO codes."""

    def test_qwen_zh_iso_code(self):
        assert language_fit("qwen", "zh") == 9

    def test_qwen_chinese_simplified_display_string(self):
        # The real value the settings dropdown stores
        assert language_fit("qwen", "Chinese (Simplified)") == 9

    def test_openai_english_us_display_string(self):
        assert language_fit("openai", "English (US)") == 10

    def test_groq_japanese_display_string(self):
        # groq has lower zh/ja scores — we just need it NOT to return DEFAULT
        score = language_fit("groq", "Japanese")
        assert score != DEFAULT_LANGUAGE_FIT or "ja" not in CATALOG["groq"]["languages"]

    def test_unknown_language_returns_default(self):
        assert language_fit("qwen", "Klingon") == DEFAULT_LANGUAGE_FIT
        assert language_fit("qwen", "xx") == DEFAULT_LANGUAGE_FIT
        assert language_fit("qwen", "") == DEFAULT_LANGUAGE_FIT

    def test_none_language_returns_default(self):
        assert language_fit("qwen", None) == DEFAULT_LANGUAGE_FIT

    def test_unknown_provider_returns_default(self):
        assert language_fit("nonexistent", "en") == DEFAULT_LANGUAGE_FIT


class TestCatalogCoversAllUILocales:
    """Every provider must have scores for all 6 UI locale ISO codes."""

    def test_all_providers_have_six_ui_locales(self):
        for provider, entry in CATALOG.items():
            lang_map = entry["languages"]
            missing = UI_LOCALES - set(lang_map.keys())
            assert not missing, (
                f"Provider {provider!r} is missing UI locale keys: {missing}"
            )

    def test_all_scores_in_range(self):
        for provider, entry in CATALOG.items():
            for code, score in entry["languages"].items():
                assert 0 <= score <= 10, (
                    f"Provider {provider!r} language {code!r} score {score} out of range"
                )

"""OS permission copy must ship as native bundle localizations, not SPA strings."""
from __future__ import annotations

import json
import pathlib
import plistlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2] / "desktop" / "src-tauri"
LOCALES = ("en", "zh-Hans", "ja", "es", "de", "fr")
KEYS = {"NSMicrophoneUsageDescription", "NSSpeechRecognitionUsageDescription"}


@pytest.mark.parametrize("locale", LOCALES)
def test_native_permission_locale_is_complete_and_bundled(locale):
    source = f"locales/{locale}.lproj"
    config = json.loads((ROOT / "tauri.conf.json").read_text())
    assert config["bundle"]["resources"][source] == f"{locale}.lproj"
    copy = plistlib.loads((ROOT / source / "InfoPlist.strings").read_bytes())
    assert set(copy) == KEYS
    assert all(isinstance(value, str) and value.strip() for value in copy.values())
    assert "Apple" in copy["NSSpeechRecognitionUsageDescription"]


def test_native_permission_english_fallback_matches_localized_copy():
    fallback = plistlib.loads((ROOT / "Info.plist").read_bytes())
    english = plistlib.loads((ROOT / "locales/en.lproj/InfoPlist.strings").read_bytes())
    assert {key: fallback[key] for key in KEYS} == english
    speech = english["NSSpeechRecognitionUsageDescription"]
    assert "when on-device recognition is available" in speech
    assert "may be sent to Apple" in speech
    assert "not sent anywhere" not in speech


def test_native_permission_translations_are_not_english_placeholders():
    copies = [plistlib.loads((ROOT / f"locales/{locale}.lproj/InfoPlist.strings")
                            .read_bytes()) for locale in LOCALES]
    for key in KEYS:
        assert len({copy[key] for copy in copies}) == len(LOCALES)

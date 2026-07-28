"""The OCR language choice: a BOUNDED picker over what the host can do.

Two measured facts drive every assertion here, and both run against intuition,
so they are pinned rather than trusted to survive a future "simplification":

  1. Asking for MORE languages makes recognition WORSE. A mixed Chinese/English
     image returns both lines for ("zh-Hans", "en-US"), and only the English one
     when all thirty supported languages are requested. Japanese disappears
     entirely. So the picker has a ceiling.

  2. Automatic detection has the best recall and is unusable: it fabricates a
     plausible Uyghur-looking string for a script it cannot read. That is why
     the options come from the host's own list and nothing else.
"""
from __future__ import annotations

import pytest

from server.services import ocr_fallback, ocr_vision


@pytest.fixture
def host_languages(monkeypatch):
    """A host that recognises a known set — substituted so the assertions do
    not depend on which macOS this runs on."""
    monkeypatch.setattr(ocr_vision, "_vision", lambda: object())
    monkeypatch.setattr(ocr_vision, "supported_languages",
                        lambda: ("en-US", "zh-Hans", "ja-JP", "de-DE"))


def test_no_choice_falls_back_to_the_interface_language(host_languages):
    assert ocr_vision.resolve_requested_tags(None, "zh") == ("zh-Hans", "en-US")
    assert ocr_vision.resolve_requested_tags("", "ja") == ("ja-JP", "en-US")
    assert ocr_vision.resolve_requested_tags("   ", None) == ("en-US",)


def test_an_explicit_choice_wins_over_the_interface_language(host_languages):
    assert ocr_vision.resolve_requested_tags("ja-JP,en-US", "zh") == ("ja-JP", "en-US")


def test_the_selection_is_capped(host_languages):
    """The ceiling is the whole point of a bounded picker.

    Without it the setting becomes the foot-gun the measurement found: more
    languages, worse recognition, and the user reasonably believing otherwise."""
    tags = ocr_vision.resolve_requested_tags(
        "en-US,zh-Hans,ja-JP,de-DE", "en")
    assert len(tags) == ocr_vision.MAX_REQUESTED_LANGUAGES
    assert tags == ("en-US", "zh-Hans", "ja-JP")


def test_languages_the_host_cannot_read_are_dropped_before_vision(host_languages):
    """Uyghur is the case this exists for: it is not in any macOS list, and
    handing it over anyway is how the scrambled result was produced."""
    assert ocr_vision.resolve_requested_tags("ug,zh-Hans", "en") == ("zh-Hans",)


def test_a_choice_of_only_unavailable_languages_yields_nothing(host_languages):
    """NOT a silent fallback to the interface language.

    Substituting a different question for the one the user asked would read as
    "we tried what you chose" while trying something else. Empty here becomes
    unsupported_language in recognize(), which the UI explains."""
    assert ocr_vision.resolve_requested_tags("ug,xx-XX", "zh") == ()


def test_duplicates_do_not_consume_the_budget(host_languages):
    assert ocr_vision.resolve_requested_tags(
        "en-US,en-US,zh-Hans", "en") == ("en-US", "zh-Hans")


def test_the_read_path_uses_the_chosen_languages(monkeypatch, host_languages):
    """The integration half: a setting nothing reads is not a setting.

    Asserts the tags that reach recognize(), because the pure resolver passing
    its own unit tests says nothing about whether anyone calls it."""
    seen = {}

    def fake_recognize(data, *, languages):
        seen["languages"] = languages
        return "text", ocr_vision.OK

    monkeypatch.setattr(ocr_vision, "recognize", fake_recognize)
    ocr_fallback.read_locally(b"x", ui_language="zh", chosen_languages="ja-JP")
    assert seen["languages"] == ("ja-JP",)


@pytest.mark.asyncio
async def test_the_endpoint_reports_the_host_rather_than_a_constant(monkeypatch):
    from server.api.settings import ocr_languages

    monkeypatch.setattr(ocr_vision, "supported_languages",
                        lambda: ("xx-XX", "yy-YY"))
    monkeypatch.setattr(ocr_vision, "is_available", lambda: True)
    body = await ocr_languages()
    # Discriminating: a hardcoded list would ignore the substitution entirely.
    assert body["available"] == ["xx-XX", "yy-YY"]
    assert body["max_selectable"] == ocr_vision.MAX_REQUESTED_LANGUAGES
    assert body["platform_supported"] is True


@pytest.mark.asyncio
async def test_the_endpoint_is_honest_on_a_host_without_recognition(monkeypatch):
    from server.api.settings import ocr_languages

    monkeypatch.setattr(ocr_vision, "_vision", lambda: None)
    monkeypatch.setattr(ocr_vision, "supported_languages", lambda: ())
    body = await ocr_languages()
    assert body["available"] == []
    assert body["platform_supported"] is False

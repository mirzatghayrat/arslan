from unittest.mock import AsyncMock

import pytest

from server.orchestrator import llm_errors
from server.services import provider_error_messages as provider, runtime_messages
from server.ws.arslan import _to_frame


@pytest.mark.parametrize("locale", ["en", "zh", "ja", "es", "de", "fr"])
async def test_owned_errors_carry_complete_catalog_and_legacy_message(monkeypatch, locale):
    monkeypatch.setattr(runtime_messages, "selected_locale", AsyncMock(return_value=locale))
    cases = [(provider.ModelNotConfiguredError("old localized body"), "not_configured"),
             (ValueError("maximum context length exceeded"), "context"),
             (ValueError("ReadTimeout"), "transport"),
             (ValueError("key limit exceeded"), "key_limit"),
             (ValueError("not available in your region"), "region"),
             (ValueError("402 insufficient credits"), "payment"),
             (ValueError("401 unauthorized"), "auth"),
             (ValueError("429 rate limit"), "rate")]
    for exc, key in cases:
        frame = await llm_errors.error_frame(exc)
        assert frame["message"] == provider.render(key, locale)
        assert frame["message_i18n"] == {lang: provider.render(key, lang) for lang in provider.MESSAGES}
        assert frame["code"] == "LLM_ERROR" and frame["recoverable"]
        assert _to_frame(frame) == frame


async def test_vision_catalog_requires_actual_image_input(monkeypatch):
    monkeypatch.setattr(runtime_messages, "selected_locale", AsyncMock(return_value="ja"))
    exc = ValueError("unknown variant `image_url`, expected `text`")
    plain = await llm_errors.error_frame(exc)
    assert plain["message"] == str(exc) and "message_i18n" not in plain
    visual = await llm_errors.error_frame(exc, code="SPAWN_ERROR", had_images=True)
    assert visual["code"] == "SPAWN_ERROR"
    assert visual["message_i18n"] == {lang: runtime_messages.render("image_refused", lang) for lang in provider.MESSAGES}


@pytest.mark.parametrize("raw", ["Novel provider diagnostic", provider.render("not_configured", "zh"), ""])
async def test_unknown_prose_is_not_reinterpreted_or_translated(monkeypatch, raw):
    lookup = AsyncMock(side_effect=AssertionError("Unknown text needs no locale lookup"))
    monkeypatch.setattr(runtime_messages, "selected_locale", lookup)
    assert await llm_errors.error_frame(ValueError(raw)) == {
        "type": "error", "code": "LLM_ERROR", "message": raw, "recoverable": True,
    }
    lookup.assert_not_called()

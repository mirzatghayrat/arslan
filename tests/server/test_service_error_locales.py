from string import Formatter
import httpx
import pytest

from server.db.models import Setting
from server.orchestrator import arslan, dispatcher, llm_errors, vision_errors
from server.services import llm_test, provider_error_messages as errors, runtime_messages as copy


CASES = {
    "context": "maximum context length exceeded 402",
    "transport": "ReadTimeout while reading provider response",
    "key_limit": "403 Key limit exceeded",
    "region": "403 model not available in your region",
    "payment": "402 Insufficient credits",
    "auth": "401 invalid_api_key",
    "rate": "429 Too Many Requests",
}


def test_service_error_catalog_parity_and_placeholder_contract():
    assert set(errors.MESSAGES) == set(copy.MESSAGES)
    for locale, messages in errors.MESSAGES.items():
        assert set(messages) == set(errors.MESSAGES["en"])
        for key, text in messages.items():
            assert text.strip()
            assert {field for _, field, _, _ in Formatter().parse(text) if field} == (
                {"status"} if key == "key_required" else set())
            if locale != "en":
                assert text != errors.MESSAGES["en"][key]


@pytest.mark.parametrize("locale", list(copy.MESSAGES))
async def test_saved_language_preserves_error_categories_and_unknowns(execution_db, locale):
    async with execution_db() as db:
        db.add(Setting(key="language", value=locale))
        await db.commit()
    for category, raw in CASES.items():
        assert llm_errors.classify(raw) == category
        assert await llm_errors.explain_current(raw, had_images=True) == errors.render(category, locale)
    assert await llm_errors.explain_current("Novel provider diagnostic") is None
    image_error = "unknown variant `image_url`, expected `text`"
    assert await llm_errors.explain_current(image_error, had_images=True) == copy.render("image_refused", locale)
    assert await llm_errors.explain_current(image_error, had_images=False) is None
    assert vision_errors.explain("429 rate limit", had_images=True, locale=locale) is None


@pytest.mark.parametrize("locale", list(copy.MESSAGES))
async def test_missing_expert_errors_keep_action_boundaries(execution_db, monkeypatch, locale):
    async with execution_db() as db:
        db.add(Setting(key="language", value=locale))
        await db.commit()
    async def missing(*args): return None
    async def forbidden(*args, **kwargs): raise AssertionError("Unavailable expert must not write or execute")
    monkeypatch.setattr(dispatcher, "get_spawn_name", missing)
    monkeypatch.setattr(arslan.memory, "add_message", forbidden)
    monkeypatch.setattr(arslan.run_recorder.RunRecorder, "start", forbidden)
    calls = [
        lambda emit: arslan._dispatch_spawn("fixture", 99, "Task", emit),
        lambda emit: arslan.record_deliverable_verdict("fixture", 99, "accept", None, emit),
        lambda emit: arslan.finalize_refinement("fixture", 99, None, "User text", emit),
        lambda emit: arslan.confirm_sandbox_merge("fixture", 99, "User text", "Summary", 0, emit),
    ]
    for index, call in enumerate(calls):
        frames = []
        await call(frames.append)
        assert frames == [{"type": "error", "code": "SPAWN_NOT_FOUND" if index == 0 else "INVALID_INPUT",
            "message": copy.render("expert_unavailable", locale), "recoverable": True}]


@pytest.mark.parametrize("locale", list(copy.MESSAGES))
@pytest.mark.parametrize("key", ["", "synthetic-key"])
async def test_model_connection_test_matches_saved_language(execution_db, monkeypatch, locale, key):
    async with execution_db() as db:
        db.add(Setting(key="language", value=locale))
        await db.commit()
    async def fail(*args, **kwargs):
        response = httpx.Response(401, request=httpx.Request("POST", "https://fixture.invalid"))
        raise httpx.HTTPStatusError("401 Unauthorized", request=response.request, response=response)
    monkeypatch.setattr(llm_test.LLMAdapter, "chat", fail)
    result = await llm_test.test_connection("openai", "fixture", "https://fixture.invalid", key)
    assert result == {"ok": False, "latency_ms": None, "error": errors.render(
        "auth" if key else "key_required", locale, status=401)}


def test_transport_explanation_does_not_claim_non_delivery_or_key_certainty():
    text = llm_errors.explain("ReadTimeout", locale="en")
    assert "does not establish" in text and "whether the provider processed" in text
    assert llm_errors.classify("ConnectError: proxy returned 401") == "transport"
    assert llm_errors.classify("401 Unauthorized") == "auth"


@pytest.mark.parametrize("locale", list(copy.MESSAGES))
async def test_unknown_connection_diagnostic_is_not_translated_or_reclassified(execution_db, monkeypatch, locale):
    async with execution_db() as db:
        db.add(Setting(key="language", value=locale))
        await db.commit()
    diagnostic = "Novel provider diagnostic: fixture-code-xyz"
    async def fail(*args, **kwargs):
        raise RuntimeError(diagnostic)
    monkeypatch.setattr(llm_test.LLMAdapter, "chat", fail)
    assert await llm_test.test_connection("openai", "fixture", "https://fixture.invalid", "synthetic-key") == {
        "ok": False, "latency_ms": None, "error": diagnostic}


def test_generic_key_limit_does_not_invent_a_provider_or_require_spending():
    text = llm_errors.explain("Key limit exceeded", locale="en")
    assert "provider's dashboard" in text
    assert "openrouter" not in text.lower()
    assert "Raise or remove" not in text

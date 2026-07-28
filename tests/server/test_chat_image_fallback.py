"""The chat turn, when the configured model will not look at the picture.

WHY THIS FILE EXISTS: v0.1.11 shipped a two-tier OCR fallback that could not
fire on the one path the user actually uses. Three separate defects lined up:

  1. the refusal matcher was built from phrasings I imagined rather than ones a
     provider emits — DeepSeek says the JSON failed to deserialise, and not one
     of the patterns went near that;
  2. _handle_answer's except never called vision_errors.explain at all, so the
     actionable copy existed only on the spawn-dispatch path;
  3. nothing in server/orchestrator/ referenced the OCR fallback, so a chat
     image had no tier 2 whatsoever.

Every provider string below is VERBATIM from a real failure, not composed for
the test. That distinction is the whole point: the previous suite passed
against invented text while the product was broken.
"""
from __future__ import annotations

import base64
import io

import pytest
import pytest_asyncio
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.db.session as db_session
from server.db.models import Base
from server.orchestrator import vision_errors
from server.services import ocr_fallback, ocr_vision

# Captured from the user's machine, 2026-07-28, DeepSeek via the OpenAI-compatible
# endpoint. Kept whole — trimming it to the "interesting" part is how a fixture
# stops resembling the thing it stands for.
DEEPSEEK_REFUSAL = (
    "Client error '400 Bad Request' for url 'https://api.deepseek.com/chat/completions'\n"
    '{"error":{"message":"Failed to deserialize the JSON body into the target type: '
    "messages[3]: unknown variant `image_url`, expected `text` at line 1 column 1111131\","
    '"type":"invalid_request_error","param":null,"code":"invalid_request_error"}}'
)

# A refusal that DOES use the wording the original matcher expected. Keeping it
# proves the broadening did not replace one narrow rule with another.
OPENAI_STYLE_REFUSAL = (
    "Error code: 400 - {'error': {'message': \"Invalid content type. image_url is only "
    "supported by certain models.\", 'type': 'invalid_request_error'}}"
)

RATE_LIMIT = (
    "Client error '429 Too Many Requests' for url 'https://api.deepseek.com/chat/completions'\n"
    '{"error":{"message":"Rate limit reached for requests","type":"rate_limit_error"}}'
)

# The two single-half cases. Mutation showed the suite could not tell the AND
# from an OR without them: neither the rate limit nor the dead key contains
# either half, so loosening the rule to "any one half" stayed green while
# quietly relabelling every malformed request as a vision problem.
SCHEMA_ERROR_NOT_ABOUT_IMAGES = (
    "Client error '400 Bad Request' for url 'https://api.deepseek.com/chat/completions'\n"
    '{"error":{"message":"Failed to deserialize the JSON body into the target type: '
    "messages[1]: unknown variant `assistant_prefix`, expected one of `system`, `user`, "
    "`assistant` at line 1 column 92\",\"type\":\"invalid_request_error\"}}"
)
IMAGE_MENTIONED_BUT_NOT_REFUSED = (
    "Client error '413 Payload Too Large' for url 'https://api.openai.com/v1/chat/completions'\n"
    '{"error":{"message":"Uploaded image/png exceeds the 20 MB limit",'
    '"type":"invalid_request_error"}}'
)

BAD_KEY = (
    "Client error '401 Unauthorized' for url 'https://api.deepseek.com/chat/completions'\n"
    '{"error":{"message":"Authentication Fails, Your api key is invalid",'
    '"type":"authentication_error"}}'
)


# ---------------------------------------------------------------------------
# 1. The matcher, against strings providers actually produce
# ---------------------------------------------------------------------------

def test_the_old_patterns_could_not_have_matched_deepseek():
    """(0) pre-assertion: without this the test below proves nothing.

    If the real string happened to contain "does not support image", the fix
    would be untested and the suite would still look green."""
    lowered = DEEPSEEK_REFUSAL.lower()
    for phrase in ("does not support image", "images are not supported",
                   "no support for image", "vision is not",
                   "unsupported content block type: image"):
        assert phrase not in lowered, (
            f"the fixture contains {phrase!r}, so it cannot demonstrate the gap")


def test_the_real_deepseek_refusal_is_recognised():
    assert vision_errors.explain(DEEPSEEK_REFUSAL, had_images=True) is not None
    assert ocr_fallback.model_refused_the_image(DEEPSEEK_REFUSAL) is True


def test_the_wording_the_matcher_already_knew_still_works():
    assert vision_errors.explain(OPENAI_STYLE_REFUSAL, had_images=True) is not None


@pytest.mark.parametrize("raw", [
    SCHEMA_ERROR_NOT_ABOUT_IMAGES,
    IMAGE_MENTIONED_BUT_NOT_REFUSED,
])
def test_one_half_alone_is_never_enough(raw):
    """The AND, pinned. Each of these satisfies exactly one of the two patterns.

    A schema complaint about a role name is not a vision problem, and an image
    that was too large was not refused for being an image — recovering by OCR
    would fail again in both cases, and the advice ("switch to a model that can
    see") would be flatly wrong."""
    assert vision_errors.explain(raw, had_images=True) is None
    assert ocr_fallback.model_refused_the_image(raw) is False


@pytest.mark.parametrize("raw", [RATE_LIMIT, BAD_KEY])
def test_unrelated_failures_are_still_left_alone(raw):
    """The narrowness this file must not destroy.

    Relabelling a rate limit or a dead key as "your model cannot see" sends
    someone off changing models over an unrelated fault, and — worse now —
    starts an OCR pass that cannot help."""
    assert vision_errors.explain(raw, had_images=True) is None
    assert ocr_fallback.model_refused_the_image(raw) is False


def test_a_turn_without_images_is_never_a_vision_problem():
    assert vision_errors.explain(DEEPSEEK_REFUSAL, had_images=False) is None


# ---------------------------------------------------------------------------
# 2. The chat path itself
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'chat.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    return maker


def _image_block(text: str) -> dict:
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 44)
    except OSError:  # pragma: no cover - host font layout
        font = ImageFont.load_default()
    img = Image.new("RGB", (760, 120), "white")
    ImageDraw.Draw(img).text((20, 30), text, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return {"name": "shot.png", "mime_type": "image/png",
            "data": base64.b64encode(buf.getvalue()).decode()}


def _collect():
    events: list[dict] = []
    return events, lambda ev: events.append(ev)


needs_vision = pytest.mark.skipif(
    not ocr_vision.is_available(), reason="no system recogniser on this host")


@needs_vision
@pytest.mark.asyncio
async def test_a_refused_image_is_read_locally_and_the_turn_continues(db, monkeypatch):
    """The user's own acceptance criterion, driven end to end.

    Not "the helper returns text" — the turn must RECOVER: a second dispatch
    happens, it carries the recognised words, and it carries no image (sending
    the picture again to a model that just refused it would fail identically)."""
    from server.orchestrator import arslan

    calls: list[object] = []

    async def fake_run_native(**kw):
        calls.append(kw["user_content"])
        if len(calls) == 1:
            raise RuntimeError(DEEPSEEK_REFUSAL)
        return {"answer": "I read it."}

    monkeypatch.setattr(arslan.tool_loop, "run_native", fake_run_native)
    monkeypatch.setattr(ocr_fallback, "current_ui_language", _en)

    events, emit = _collect()
    await arslan._handle_answer_body(
        "conv-ocr", "what does this say?", emit,
        images=[_image_block("invoice total 42")])

    assert len(calls) == 2, f"the turn did not retry after the refusal: {calls}"
    second = calls[1]
    flat = second if isinstance(second, str) else " ".join(
        b.get("text", "") for b in second if isinstance(b, dict))
    assert "invoice total 42" in flat, f"the recognised text never reached the model: {flat!r}"
    assert not any(isinstance(b, dict) and b.get("type") == "image"
                   for b in (second if isinstance(second, list) else [])), \
        "the image was sent again to a model that had just refused it"
    assert not [e for e in events if e.get("type") == "error"], events


@pytest.mark.asyncio
async def test_an_unrelated_failure_neither_recovers_nor_relabels(db, monkeypatch):
    """Discriminating twin. A fallback wired to `except Exception` would pass
    the test above and silently turn every outage into an OCR pass."""
    from server.orchestrator import arslan

    calls = []
    ocr_ran = []

    async def fake_run_native(**kw):
        calls.append(kw["user_content"])
        raise RuntimeError(RATE_LIMIT)

    monkeypatch.setattr(arslan.tool_loop, "run_native", fake_run_native)
    monkeypatch.setattr(ocr_fallback, "read_locally",
                        lambda *a, **k: ocr_ran.append(1) or ("x", ocr_vision.OK))

    events, emit = _collect()
    await arslan._handle_answer_body(
        "conv-rate", "what does this say?", emit, images=[_image_block("hi")])

    assert len(calls) == 1, "an unrelated failure triggered a retry"
    assert ocr_ran == [], "a rate limit started an OCR pass"
    errors = [e for e in events if e.get("type") == "error"]
    assert errors, events
    assert "Rate limit" in errors[0]["message"], errors[0]["message"]


@pytest.mark.asyncio
async def test_when_local_reading_finds_nothing_the_user_gets_the_advice(db, monkeypatch):
    """Recovery is not always possible; what must never happen is the raw
    provider JSON the user was shown in v0.1.11."""
    from server.orchestrator import arslan

    async def fake_run_native(**kw):
        raise RuntimeError(DEEPSEEK_REFUSAL)

    monkeypatch.setattr(arslan.tool_loop, "run_native", fake_run_native)
    monkeypatch.setattr(ocr_fallback, "read_locally",
                        lambda *a, **k: ("", ocr_vision.NO_TEXT))
    monkeypatch.setattr(ocr_fallback, "current_ui_language", _en)

    events, emit = _collect()
    await arslan._handle_answer_body(
        "conv-none", "what does this say?", emit, images=[_image_block("hi")])

    errors = [e for e in events if e.get("type") == "error"]
    assert errors, events
    msg = errors[0]["message"]
    assert "deserialize" not in msg, f"raw provider JSON reached the user: {msg!r}"
    assert "vision" in msg.lower() or "images" in msg.lower(), msg


async def _en():
    return "en"

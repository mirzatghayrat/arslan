"""Vision transport: a neutral image block must reach each provider's NATIVE
image shape — and must never be stringified into text.

Why payload assertions and not "it didn't crash": Gemini's builder did
`str(m["content"])`, which turns a block list into a Python repr and sends it
as TEXT. Nothing raises, the API answers, and the answer looks plausible — it
is simply computed from the literal characters of a base64 blob. Only asserting
the emitted payload can tell that apart from a working vision call.
"""
from __future__ import annotations

import base64

import pytest

from arslan.llm.providers.anthropic_provider import AnthropicProvider
from arslan.llm.providers.gemini_provider import GeminiProvider
from arslan.llm.providers.openai_provider import OpenAIProvider

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nFAKEBYTES").decode()

# The neutral shape the rest of the app speaks; each provider translates it.
IMAGE_BLOCK = {"type": "image", "mime_type": "image/png", "data": PNG}
TEXT_BLOCK = {"type": "text", "text": "what is in this picture?"}
USER_BLOCKS = [TEXT_BLOCK, IMAGE_BLOCK]


def _messages(provider):
    return provider.build_messages("SYS", USER_BLOCKS, None)


def _body(provider, messages):
    """Each provider's real payload signature — openai takes tools, the other
    two do not. Asserting the emitted body is the whole point, so the test
    adapts to the code rather than the code being bent for the test."""
    if isinstance(provider, OpenAIProvider):
        return provider._payload(messages, None, 0.7)
    return provider._payload(messages, 0.7)


def _walk(obj):
    """Every string anywhere in the payload."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _assert_not_stringified(payload):
    """⓪ The failure mode this whole file exists for: a dict rendered as its
    Python repr and shipped as text."""
    for s in _walk(payload):
        assert "'type':" not in s and '{"type":' not in s.replace(" ", ""), (
            f"a block was stringified into text: {s[:120]!r}"
        )


@pytest.fixture
def openai():
    return OpenAIProvider(model="gpt-x", api_key="k")


@pytest.fixture
def anthropic():
    return AnthropicProvider(model="claude-x", api_key="k")


@pytest.fixture
def gemini():
    return GeminiProvider(model="gemini-x", api_key="k")


def test_openai_emits_image_url_data_uri(openai):
    payload = _body(openai, _messages(openai))
    user = [m for m in payload["messages"] if m["role"] == "user"][-1]
    parts = user["content"]
    assert isinstance(parts, list), "content must stay a list of parts"
    img = [p for p in parts if p.get("type") == "image_url"]
    assert len(img) == 1, f"expected exactly one image part, got {parts}"
    assert img[0]["image_url"]["url"] == f"data:image/png;base64,{PNG}"
    assert any(p.get("type") == "text" for p in parts), "the question must survive"
    _assert_not_stringified(payload)


def test_anthropic_emits_base64_source(anthropic):
    payload = _body(anthropic, _messages(anthropic))
    user = [m for m in payload["messages"] if m["role"] == "user"][-1]
    parts = user["content"]
    img = [p for p in parts if p.get("type") == "image"]
    assert len(img) == 1, f"expected exactly one image part, got {parts}"
    assert img[0]["source"] == {"type": "base64", "media_type": "image/png", "data": PNG}
    _assert_not_stringified(payload)


def test_gemini_emits_inline_data_not_a_repr(gemini):
    """🔴 T5: the historic silent-corruption path."""
    payload = _body(gemini, _messages(gemini))
    parts = payload["contents"][-1]["parts"]
    inline = [p for p in parts if "inline_data" in p]
    assert len(inline) == 1, f"expected one inline_data part, got {parts}"
    assert inline[0]["inline_data"] == {"mime_type": "image/png", "data": PNG}
    assert any("text" in p for p in parts), "the question must survive"
    _assert_not_stringified(payload)


@pytest.mark.parametrize("name", ["openai", "anthropic", "gemini"])
def test_plain_string_user_is_untouched(name, request):
    """Discrimination: 34 of the 36 call sites pass plain strings. Widening the
    type must not reshape their payloads at all."""
    provider = request.getfixturevalue(name)
    payload = _body(provider, provider.build_messages("SYS", "hello", None))
    flat = "".join(_walk(payload))
    assert "hello" in flat
    assert "inline_data" not in str(payload) and "image_url" not in str(payload)

"""A provider's 4xx must carry ITS OWN explanation, not just the status line.

WHY (found on the user's machine, v0.1.9): httpx's raise_for_status() puts
nothing from the response body into the exception message. So a DeepSeek
refusal of image input reached the user as

    Client error '400 Bad Request' for url 'https://api.deepseek.com/…'

— useless to them and, worse, unmatchable by vision_errors.explain(), which
looks for the provider's actual wording. The vision error copy therefore never
fired in real life while its unit tests passed, because those tests used
error strings I had INVENTED rather than any the code produces.

These tests build the error through the REAL httpx path for that reason.
"""
from __future__ import annotations

import httpx
import pytest

from arslan.llm.providers import errors as provider_errors


def _real_httpx_error(body: dict | str, status: int = 400) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    kw = {"json": body} if isinstance(body, dict) else {"text": body}
    resp = httpx.Response(status, request=req, **kw)
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return exc
    raise AssertionError("expected raise_for_status to raise")


def test_the_status_line_alone_is_what_httpx_gives_us():
    """⓪ pre-assertion: if httpx ever starts including the body, the whole
    exercise below is unnecessary and this test says so loudly."""
    exc = _real_httpx_error({"error": {"message": "model does not support image input"}})
    assert "does not support image" not in str(exc)


def test_the_body_is_added_to_the_message():
    exc = _real_httpx_error({"error": {"message": "model does not support image input"}})
    msg = provider_errors.with_body(exc)
    assert "400" in msg
    assert "does not support image input" in msg


def test_a_plain_text_body_survives_too():
    exc = _real_httpx_error("upstream is out of capacity", status=503)
    assert "out of capacity" in provider_errors.with_body(exc)


def test_an_enormous_body_is_truncated():
    exc = _real_httpx_error("x" * 50_000)
    msg = provider_errors.with_body(exc)
    assert len(msg) < 2_000, "an error message must not become a wall of text"


def test_an_empty_body_degrades_to_the_status_line():
    exc = _real_httpx_error("")
    assert "400" in provider_errors.with_body(exc)


def test_vision_copy_now_fires_on_the_REAL_error_shape():
    """The end-to-end point: the conversion must trigger on what the code
    actually produces, not on a string I made up."""
    from server.orchestrator import vision_errors

    exc = _real_httpx_error({"error": {"message": "model does not support image input"}})
    enriched = provider_errors.with_body(exc)
    assert vision_errors.explain(enriched, had_images=True) is not None
    # …and the unenriched original still does not, which is exactly the bug.
    assert vision_errors.explain(str(exc), had_images=True) is None


@pytest.mark.asyncio
async def test_the_provider_itself_raises_with_the_body(monkeypatch):
    """Wiring, not just the helper. The last two rounds each shipped a correct
    pure function that nothing called; this drives the real provider."""
    from arslan.llm.providers.openai_provider import OpenAIProvider

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            req = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
            return httpx.Response(
                400, request=req,
                json={"error": {"message": "model does not support image input"}})

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: _Client())
    provider = OpenAIProvider(model="deepseek-chat", api_key="k",
                              base_url="https://api.deepseek.com")
    with pytest.raises(httpx.HTTPStatusError) as caught:
        await provider.chat([{"role": "user", "content": "hi"}])
    assert "does not support image input" in str(caught.value), (
        "the provider's explanation was dropped on the way out"
    )

"""web_extract must re-check the SSRF guard on every redirect hop (release-gate)."""
import httpx
import pytest

from server.registry import executors


def _client_with(handler):
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False
    )


async def test_fetch_text_blocks_redirect_to_private_host(monkeypatch):
    # public start host is fine; the redirect target (metadata IP) is private.
    monkeypatch.setattr(executors, "_is_private_host", lambda u: "169.254" in u)

    def handler(request):
        if "169.254" in str(request.url):
            return httpx.Response(200, text="SECRET CLOUD METADATA")
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})

    monkeypatch.setattr(executors, "_build_client", lambda: _client_with(handler))

    with pytest.raises(httpx.HTTPError):
        await executors._fetch_text("http://public.example/page")


async def test_fetch_text_follows_legit_public_redirect(monkeypatch):
    monkeypatch.setattr(executors, "_is_private_host", lambda u: False)
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.host == "a.example":
            return httpx.Response(302, headers={"location": "http://b.example/final"})
        return httpx.Response(
            200,
            text="<html><body><article>"
            "这是一段足够长的正文用于 trafilatura 正确抽取内容。"
            "</article></body></html>",
        )

    monkeypatch.setattr(executors, "_build_client", lambda: _client_with(handler))

    await executors._fetch_text("http://a.example/start")
    assert any("b.example" in u for u in seen), "legit public redirect must be followed"

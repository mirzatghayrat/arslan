"""0.1.49 search fix: the chat provider's own search first (DeepSeek native),
DuckDuckGo last, and a blocked provider is reported as blocked — never as
"0 results" (the bench found DuckDuckGo answering 202 with a challenge page)."""
import json

import httpx
import pytest

from arslan.execution_budget import Budget, Limits, scope
from server.registry import executors, net_pin, search_providers as sp

CHALLENGE = ("<html><body><div class='anomaly-modal'>Unfortunately, bots use DuckDuckGo too. Please complete "
             "the following challenge to confirm this search was made by a human.</div></body></html>")
RESULTS = ('<a class="result__a" href="https://example.test/a">Apple 10-K</a>'
           '<a class="result__snippet" href="#">Net sales were...</a>')


@pytest.mark.parametrize("status,body,blocked", [
    (202, CHALLENGE, True), (200, CHALLENGE, True), (202, "", True),
    (200, RESULTS, False), (200, "<html>no results here</html>", False),
])
def test_challenge_detection(status, body, blocked):
    assert sp.DuckDuckGoHtmlProvider.is_challenge(status, body) is blocked


async def test_ddg_challenge_raises_search_blocked(monkeypatch):
    async def fake(method, url, **kw):
        return httpx.Response(202, text=CHALLENGE, request=httpx.Request(method, url))
    monkeypatch.setattr(net_pin, "pinned_request", fake)
    with pytest.raises(sp.SearchBlocked):
        await sp.DuckDuckGoHtmlProvider().search("apple revenue")


NATIVE = {"content": [
    {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "apple revenue"}},
    {"type": "web_search_tool_result", "tool_use_id": "s1", "content": [
        {"type": "web_search_result", "url": "https://investor.apple.com/10k", "title": "Apple 10-K",
         "page_age": "2025-10-31"},
        {"type": "web_search_result", "url": "https://example.test/b", "title": "B"},
        {"type": "web_search_result", "url": "https://investor.apple.com/10k", "title": "dup"}]},
    {"type": "text", "text": "Apple reported...", "citations": [
        {"type": "web_search_result_location", "url": "https://investor.apple.com/10k",
         "cited_text": "Total net sales 416,161"}]}],
    "usage": {"input_tokens": 1200, "output_tokens": 80}}


def test_native_results_come_from_structured_blocks_only():
    rows = sp.DeepSeekNativeProvider.parse(NATIVE, 5)
    assert [r["url"] for r in rows] == ["https://investor.apple.com/10k", "https://example.test/b"]
    assert rows[0]["snippet"] == "Total net sales 416,161" and rows[0]["published"] == "2025-10-31"
    assert "Apple reported" not in json.dumps(rows)          # the model's prose is never a result


@pytest.mark.parametrize("payload", [
    {"content": [{"type": "text", "text": "I searched and found..."}]},
    {"content": [{"type": "web_search_tool_result", "content": {"type": "web_search_tool_result_error",
                                                                  "error_code": "unavailable"}}]},
])
def test_native_without_results_fails_loudly(payload):
    with pytest.raises(ValueError):
        sp.DeepSeekNativeProvider.parse(payload)


@pytest.mark.parametrize("base,model,expected", [
    ("https://api.deepseek.com", "deepseek-v4-flash", "https://api.deepseek.com/anthropic/v1"),
    ("https://api.deepseek.com/v1/", "deepseek-v4-pro", "https://api.deepseek.com/anthropic/v1"),
    ("http://127.0.0.1:8900/c/run", "deepseek-v4-pro", "http://127.0.0.1:8900/c/run/anthropic/v1"),
    ("https://api.openai.com/v1", "gpt-5", None),
    ("https://api.deepseek.com", "", None),
])
def test_native_base_only_for_deepseek_models(base, model, expected):
    assert sp.deepseek_native_base(base, model) == expected


async def test_native_request_shape_and_budget(monkeypatch):
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(200, json=NATIVE)
    real = httpx.AsyncClient
    monkeypatch.setattr("arslan.llm.deepseek_search.httpx.AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    with scope(Budget(Limits())) as budget:
        rows = await sp.DeepSeekNativeProvider(base_url="https://api.deepseek.com/anthropic/v1",
                                               api_key="sk-test").search("apple revenue")
    req = sent[0]
    body = json.loads(req.content)
    assert str(req.url) == "https://api.deepseek.com/anthropic/v1/messages"
    assert req.headers["x-api-key"] == "sk-test" and req.headers["anthropic-version"] == "2023-06-01"
    assert body["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}]
    assert body["model"] == "deepseek-v4-flash" and "apple revenue" in body["messages"][0]["content"][0]["text"]
    assert budget.model_requests == 1 and budget.tokens == 1280       # a search is a model call
    assert len(rows) == 2


def _auto(monkeypatch, endpoint=("https://api.deepseek.com", "deepseek-v4-flash", "sk-x"), name="duckduckgo"):
    async def cfg():
        return executors.SearchConfig(name=name, key="", key_state="unset")
    monkeypatch.setattr(executors, "_read_search_config", cfg)

    async def primary():
        return endpoint
    monkeypatch.setattr("server.services.llm_factory.primary_chat_endpoint", primary)


async def test_auto_prefers_the_chat_providers_own_search(monkeypatch):
    _auto(monkeypatch)

    async def native(self, query, num_results=5):
        return [{"title": "T", "url": "https://a.test", "snippet": ""}]

    async def ddg(self, query, num_results=5):
        raise AssertionError("the scrape is the last resort")
    monkeypatch.setattr(sp.DeepSeekNativeProvider, "search", native)
    monkeypatch.setattr(sp.DuckDuckGoHtmlProvider, "search", ddg)
    out = await executors.EXECUTORS["web_search"].execute({"query": "q"})
    assert out["ok"] and out["provider"] == "deepseek" and "fallback_from" not in out


async def test_auto_falls_back_and_says_why(monkeypatch):
    _auto(monkeypatch)

    async def native(self, query, num_results=5):
        raise ValueError("DeepSeek returned no web_search_tool_result block")

    async def ddg(self, query, num_results=5):
        return [{"title": "T", "url": "https://b.test", "snippet": ""}]
    monkeypatch.setattr(sp.DeepSeekNativeProvider, "search", native)
    monkeypatch.setattr(sp.DuckDuckGoHtmlProvider, "search", ddg)
    out = await executors.EXECUTORS["web_search"].execute({"query": "q"})
    assert out["ok"] and out["provider"] == "duckduckgo" and out["fallback_from"][0].startswith("deepseek:")


async def test_everything_blocked_is_an_explicit_error_not_zero_results(monkeypatch):
    _auto(monkeypatch, endpoint=None)          # not a DeepSeek chat model: only the scrape is left

    async def ddg(self, query, num_results=5):
        raise sp.SearchBlocked("DuckDuckGo answered with a human-verification challenge")
    monkeypatch.setattr(sp.DuckDuckGoHtmlProvider, "search", ddg)
    out = await executors.EXECUTORS["web_search"].execute({"query": "q"})
    assert out["ok"] is False and out["code"] == "search_blocked"
    assert "not 'no results'" in out["error"] and "Tavily" in out["error"]


async def test_a_deliberate_searxng_choice_never_falls_back(monkeypatch):
    async def cfg():
        return executors.SearchConfig(name="searxng", key="", key_state="unset", base_url="http://10.0.0.5:8080")
    monkeypatch.setattr(executors, "_read_search_config", cfg)
    resolved = await executors._search_provider()
    assert resolved.provider is not executors.AUTO_SEARCH
    assert type(resolved.provider).__name__ == "SearXNGProvider"

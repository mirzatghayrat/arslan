"""0.1.63 D5: web_search uses the search of the model THIS turn runs on (Anthropic's for Claude on its own host,
DeepSeek's for DeepSeek), a chosen Tavily / SearXNG is "only" or "backup" and never falls to DuckDuckGo, and a
provider that refuses (403, 429, an anti-bot page) is reported as blocked, while 401 is a rejected key."""
import json

import httpx
import pytest

from arslan.execution_budget import Budget, Limits, scope
from arslan.llm import prices
from arslan.llm.adapter import LLMAdapter
from arslan.llm.providers import anthropic_provider
from server import schemas
from server.orchestrator import tool_loop, turn_model
from server.registry import executors, net_pin, search_providers as sp
from server.services import settings_service

CLAUDE = dict(provider_name="anthropic", model="claude-sonnet-5", api_key="sk-ant-test")
DEEPSEEK = dict(provider_name="openai", model="deepseek-v4-flash", api_key="sk-ds-test",
                base_url="https://api.deepseek.com", report_provider="deepseek")
OLLAMA = dict(provider_name="openai", model="qwen3", base_url="http://127.0.0.1:11434/v1", report_provider="ollama")

ANSWER = {"content": [
    {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "apple revenue"}},
    {"type": "web_search_tool_result", "tool_use_id": "s1", "content": [
        {"type": "web_search_result", "url": "https://investor.apple.com/10k", "title": "Apple 10-K",
         "page_age": "2025-10-31", "encrypted_content": "e1"},
        {"type": "web_search_result", "url": "ftp://example.test/x", "title": "not http"},
        {"type": "web_search_result", "url": "https://example.test/b", "title": "B", "encrypted_content": "e2"},
        {"type": "web_search_result", "url": "https://investor.apple.com/10k", "title": "dup"}]},
    {"type": "text", "text": "Apple reported...", "citations": [
        {"type": "web_search_result_location", "url": "https://investor.apple.com/10k",
         "cited_text": "Total net sales 416,161"}]}],
    "usage": {"input_tokens": 1200, "output_tokens": 80, "server_tool_use": {"web_search_requests": 1}}}


def _turn(monkeypatch, adapter):
    monkeypatch.setattr(turn_model, "current", lambda: adapter)


def _primary(monkeypatch, endpoint):
    """The primary config. D5 must not read it; tests set it to the OTHER party so reading it would show."""
    async def primary():
        return endpoint
    monkeypatch.setattr("server.services.llm_factory.primary_chat_endpoint", primary)


def _settings(monkeypatch, name="", role="", key=""):
    async def cfg():
        return executors.SearchConfig(name=name, key=key, key_state="set" if key else "unset",
                                      base_url="http://10.0.0.5:8080" if name == "searxng" else "", role=role)
    monkeypatch.setattr(executors, "_read_search_config", cfg)

    async def no_wait(seconds):
        return None
    monkeypatch.setattr(executors, "_RETRY_SLEEP", no_wait)


def _names(providers):
    return [p.name for p in providers]


def _calls(monkeypatch, outcomes: dict):
    """Stub each provider's search; outcomes[name] is an exception to raise or rows to return. Returns the calls."""
    called = []

    def stub(name):
        async def search(self, query, num_results=5):
            called.append(name)
            outcome = outcomes[name]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return search
    for name, cls in (("anthropic", sp.AnthropicNativeProvider), ("deepseek", sp.DeepSeekNativeProvider),
                      ("duckduckgo", sp.DuckDuckGoHtmlProvider), ("tavily", sp.TavilyProvider),
                      ("searxng", sp.SearXNGProvider)):
        monkeypatch.setattr(cls, "search", stub(name))
    return called


ROWS = [{"title": "T", "url": "https://a.test", "snippet": ""}]


def _status(code, url="https://api.tavily.com/search"):
    request = httpx.Request("POST", url)
    return httpx.HTTPStatusError(f"http {code}", request=request, response=httpx.Response(code, request=request))


# --- Anthropic's result parsing -------------------------------------------------------------------------------


def test_anthropic_results_come_from_structured_blocks_only():
    rows = sp.AnthropicNativeProvider.parse(ANSWER, 5)
    assert [r["url"] for r in rows] == ["https://investor.apple.com/10k", "https://example.test/b"]  # no dup, no ftp
    assert rows[0]["snippet"] == "Total net sales 416,161" and rows[0]["published"] == "2025-10-31"
    assert "Apple reported" not in json.dumps(rows)          # the model's prose is never a result


@pytest.mark.parametrize("payload", [
    {"content": [{"type": "text", "text": "I searched and found..."}]},
    {"content": [{"type": "web_search_tool_result", "content": {"type": "web_search_tool_result_error",
                                                                  "error_code": "too_many_requests"}}]},
])
def test_anthropic_without_results_fails_loudly(payload):
    with pytest.raises(ValueError, match="Anthropic"):
        sp.AnthropicNativeProvider.parse(payload)


async def test_anthropic_request_shape_budget_and_price(monkeypatch):
    sent, details = [], []

    def handler(request):
        sent.append(request)
        return httpx.Response(200, json=ANSWER)
    real = httpx.AsyncClient
    monkeypatch.setattr("arslan.llm.anthropic_search.httpx.AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr("arslan.llm.usage_sink.report_detail", lambda **kw: details.append(kw))
    with scope(Budget(Limits())) as budget:
        rows = await sp.AnthropicNativeProvider(base_url="https://api.anthropic.com/v1",
                                                api_key="sk-ant-test").search("apple revenue")
    req = sent[0]
    body = json.loads(req.content)
    assert str(req.url) == "https://api.anthropic.com/v1/messages"
    assert req.headers["x-api-key"] == "sk-ant-test" and req.headers["anthropic-version"] == "2023-06-01"
    assert body["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}]
    assert body["model"] == "claude-haiku-5-5" and body["thinking"] == {"type": "disabled"}
    assert "apple revenue" in body["messages"][0]["content"][0]["text"]
    assert budget.model_requests == 1 and budget.tokens == 1280       # a search is a model call
    tokens_only = prices.usd_for_usage("claude-haiku-5-5", ANSWER["usage"], provider="anthropic")
    assert details[-1]["provider"] == "anthropic" and details[-1]["model"] == "claude-haiku-5-5"
    assert details[-1]["usd"] == pytest.approx(tokens_only + 0.01)   # $10 per 1,000 searches, one search
    assert len(rows) == 2


# --- The gate: K1b's first-party check, the same function -----------------------------------------------------


def test_claude_on_anthropics_host_uses_anthropics_search(monkeypatch):
    _turn(monkeypatch, LLMAdapter(**CLAUDE))
    providers = executors._native_providers()
    assert _names(providers) == ["anthropic"]
    assert providers[0].base_url == "https://api.anthropic.com/v1"


@pytest.mark.parametrize("adapter", [
    dict(CLAUDE, base_url="https://gateway.example.com/v1"),      # another Anthropic-protocol host
    dict(CLAUDE, model="mistral-large"),                           # official host, not Claude
    dict(CLAUDE, api_key=""),                                      # nothing to send it with
])
def test_no_anthropic_search_off_the_gate(monkeypatch, adapter):
    _turn(monkeypatch, LLMAdapter(**adapter))
    assert executors._native_providers() == []


def test_a_listed_verbatim_proxy_passes_the_gate(monkeypatch):
    adapter = dict(CLAUDE, base_url="http://127.0.0.1:8901/c/run/v1")
    _turn(monkeypatch, LLMAdapter(**adapter))
    assert executors._native_providers() == []                     # not listed: no
    monkeypatch.setattr(anthropic_provider, "_FIRST_PARTY_HOSTS", frozenset({"127.0.0.1:8901"}))
    providers = executors._native_providers()
    assert _names(providers) == ["anthropic"] and providers[0].base_url == "http://127.0.0.1:8901/c/run/v1"


# --- This turn's model, never the primary config --------------------------------------------------------------


async def test_ollama_turn_with_claude_primary_gets_no_anthropic(monkeypatch):
    _primary(monkeypatch, ("https://api.anthropic.com/v1", "claude-sonnet-5", "sk-ant-test"))
    _turn(monkeypatch, LLMAdapter(**OLLAMA))
    assert _names(await executors._auto_search_providers()) == ["duckduckgo"]


async def test_claude_turn_with_deepseek_primary_uses_anthropic(monkeypatch):
    _primary(monkeypatch, ("https://api.deepseek.com", "deepseek-v4-flash", "sk-ds-test"))
    _turn(monkeypatch, LLMAdapter(**CLAUDE))
    assert _names(await executors._auto_search_providers()) == ["anthropic", "duckduckgo"]


async def test_ollama_turn_with_deepseek_primary_gets_no_deepseek(monkeypatch):
    """The privacy bug ③Hands found on the D5 card: a local conversation's queries went to DeepSeek. The local
    model here is even NAMED like a DeepSeek one, so only the local check stops it."""
    _primary(monkeypatch, ("https://api.deepseek.com", "deepseek-v4-flash", "sk-ds-test"))
    _turn(monkeypatch, LLMAdapter(**dict(OLLAMA, model="deepseek-v4-flash", api_key="ollama")))
    assert _names(await executors._auto_search_providers()) == ["duckduckgo"]


async def test_no_turn_model_means_no_providers_own_search(monkeypatch):
    _primary(monkeypatch, ("https://api.deepseek.com", "deepseek-v4-flash", "sk-ds-test"))
    _turn(monkeypatch, None)
    assert _names(await executors._auto_search_providers()) == ["duckduckgo"]


async def test_deepseek_turn_uses_deepseek(monkeypatch):
    _primary(monkeypatch, ("https://api.anthropic.com/v1", "claude-sonnet-5", "sk-ant-test"))
    _turn(monkeypatch, LLMAdapter(**DEEPSEEK))
    assert _names(await executors._auto_search_providers()) == ["deepseek", "duckduckgo"]


async def test_the_tool_loop_hands_web_search_this_turns_adapter():
    seen = []

    class Adapter:
        calls = 0

        async def chat(self, system, user, history=None, **kwargs):
            from arslan.models import LLMResponse
            Adapter.calls += 1
            if Adapter.calls == 1:
                return LLMResponse(content="", usage={}, tool_calls=[{"id": "1", "type": "function", "function": {
                    "name": "web_search", "arguments": {"query": "q"}}}])
            return LLMResponse(content="Done.", usage={})

    class Executor:
        async def execute(self, args):
            seen.append(turn_model.current())
            return {"ok": True, "results": [], "provider": "fixture", "summary": "0 results · provider=fixture"}

    async def tools():
        return [{"key": "web_search", "description": "Search the web"}]

    adapter = Adapter()
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(tool_loop.EXECUTORS, "web_search", Executor())
        await tool_loop.run_native(system="Fixture", user_content="Search something", history=[],
                                   resolve_tools=tools, emit=lambda _: None, on_chunk=lambda _: None,
                                   adapter_override=adapter)
    assert seen == [adapter]
    assert turn_model.current() is None                            # reset after the call


# --- Order ------------------------------------------------------------------------------------------------------


async def test_no_service_chosen_claude_then_the_scrape(monkeypatch):
    _settings(monkeypatch, name="duckduckgo")
    _turn(monkeypatch, LLMAdapter(**CLAUDE))
    called = _calls(monkeypatch, {"anthropic": ValueError("no block"), "duckduckgo": ROWS})
    out = await executors.EXECUTORS["web_search"].execute({"query": "q"})
    assert called == ["anthropic", "duckduckgo"] and out["ok"] and out["provider"] == "duckduckgo"


@pytest.mark.parametrize("role", ["", "only"])
async def test_a_service_saved_before_d5_or_only_is_the_one_search(monkeypatch, role):
    """Every Tavily / SearXNG choice saved before D5 has role "": it behaves exactly as before."""
    _settings(monkeypatch, name="searxng", role=role)
    _turn(monkeypatch, LLMAdapter(**CLAUDE))
    called = _calls(monkeypatch, {"anthropic": ROWS, "searxng": ValueError("instance down"), "duckduckgo": ROWS})
    out = await executors.EXECUTORS["web_search"].execute({"query": "q"})
    assert called == ["searxng"]                                    # no model search, no scrape
    assert out["ok"] is False and out["code"] == "search_failed" and out["provider"] == "searxng"


async def test_backup_comes_after_the_models_own_search(monkeypatch):
    _settings(monkeypatch, name="searxng", role="backup")
    _turn(monkeypatch, LLMAdapter(**CLAUDE))
    called = _calls(monkeypatch, {"anthropic": ROWS, "searxng": ROWS, "duckduckgo": ROWS})
    out = await executors.EXECUTORS["web_search"].execute({"query": "q"})
    assert called == ["anthropic"] and out["provider"] == "anthropic"


async def test_backup_is_used_when_the_models_search_fails_and_never_the_scrape(monkeypatch):
    _settings(monkeypatch, name="searxng", role="backup")
    _turn(monkeypatch, LLMAdapter(**CLAUDE))
    called = _calls(monkeypatch, {"anthropic": ValueError("no block"), "searxng": ROWS, "duckduckgo": ROWS})
    out = await executors.EXECUTORS["web_search"].execute({"query": "q"})
    assert called == ["anthropic", "searxng"] and out["provider"] == "searxng"
    assert out["fallback_from"][0].startswith("anthropic:")
    called.clear()
    _calls(monkeypatch, {"anthropic": ValueError("no block"), "searxng": ValueError("down"), "duckduckgo": ROWS})
    out = await executors.EXECUTORS["web_search"].execute({"query": "q"})
    assert out["ok"] is False and "duckduckgo" not in out["error"]


async def test_backup_on_a_local_turn_is_just_the_chosen_service(monkeypatch):
    _settings(monkeypatch, name="searxng", role="backup")
    _turn(monkeypatch, LLMAdapter(**OLLAMA))
    called = _calls(monkeypatch, {"anthropic": ROWS, "deepseek": ROWS, "searxng": ROWS, "duckduckgo": ROWS})
    out = await executors.EXECUTORS["web_search"].execute({"query": "q"})
    assert called == ["searxng"] and out["provider"] == "searxng"


# --- Blocked is blocked, for every provider; a rejected key is not ------------------------------------------------


@pytest.mark.parametrize("code", [429, 403])
async def test_tavily_refusing_is_search_blocked_not_no_results(monkeypatch, code):
    _settings(monkeypatch, name="tavily", key="tvly-test")
    _turn(monkeypatch, LLMAdapter(**CLAUDE))
    _calls(monkeypatch, {"tavily": _status(code)})
    out = await executors.EXECUTORS["web_search"].execute({"query": "q"})
    assert out["ok"] is False and out["code"] == "search_blocked" and out["provider"] == "tavily"
    assert f"http {code}" in out["error"] and "not 'no results'" in out["error"]


async def test_searxng_rate_limit_through_the_real_request_is_search_blocked(monkeypatch):
    """Not a stubbed exception: the provider's own raise_for_status, and the one retry, on a real 429."""
    _settings(monkeypatch, name="searxng")
    _turn(monkeypatch, None)
    hits = []

    async def limited(method, url, **kw):
        hits.append(url)
        return httpx.Response(429, request=httpx.Request(method, url))
    monkeypatch.setattr(net_pin, "pinned_request", limited)
    out = await executors.EXECUTORS["web_search"].execute({"query": "q"})
    assert len(hits) == 2                                           # one retry for a rate limit, then stop
    assert out["code"] == "search_blocked" and out["provider"] == "searxng"


async def test_a_rejected_tavily_key_is_search_failed_with_re_enter_the_key(monkeypatch):
    _settings(monkeypatch, name="tavily", key="tvly-wrong")
    _turn(monkeypatch, None)
    _calls(monkeypatch, {"tavily": _status(401)})
    out = await executors.EXECUTORS["web_search"].execute({"query": "q"})
    assert out["ok"] is False and out["code"] == "search_failed"
    assert "re-enter it in Settings" in out["error"] and "blocked" not in out["error"]


async def test_backup_with_a_rejected_key_is_search_failed_with_re_enter_the_key(monkeypatch):
    _settings(monkeypatch, name="tavily", role="backup", key="tvly-wrong")
    _turn(monkeypatch, LLMAdapter(**CLAUDE))
    _calls(monkeypatch, {"anthropic": _status(429, "https://api.anthropic.com/v1/messages"),
                         "tavily": _status(401)})
    out = await executors.EXECUTORS["web_search"].execute({"query": "q"})
    assert out["code"] == "search_failed" and "anthropic: blocked (http 429)" in out["error"]
    assert "re-enter it in Settings" in out["error"]


async def test_backup_with_everything_refusing_is_search_blocked(monkeypatch):
    _settings(monkeypatch, name="tavily", role="backup", key="tvly-test")
    _turn(monkeypatch, LLMAdapter(**CLAUDE))
    _calls(monkeypatch, {"anthropic": _status(429, "https://api.anthropic.com/v1/messages"),
                         "tavily": _status(403)})
    out = await executors.EXECUTORS["web_search"].execute({"query": "q"})
    assert out["code"] == "search_blocked" and "re-enter" not in out["error"]


# --- The setting ------------------------------------------------------------------------------------------------


def test_search_provider_role_is_registered_in_all_three_places():
    assert "search_provider_role" in settings_service._PLAIN_KEYS
    assert "search_provider_role" in schemas.SettingsIn.model_fields
    assert schemas.SettingsOut.model_fields["search_provider_role"].default == ""   # saved before D5 = "only"


def test_search_provider_role_takes_only_its_three_values():
    assert schemas.SettingsIn(search_provider_role="backup").search_provider_role == "backup"
    with pytest.raises(ValueError):
        schemas.SettingsIn(search_provider_role="sometimes")


# --- What the activity line reads -------------------------------------------------------------------------------


async def test_every_blocked_error_leads_with_the_marker_and_a_mixed_failure_does_not(monkeypatch):
    """The error is the activity line's summary; "search blocked:" is how it says blocked (toolHumanize.ts)."""
    _settings(monkeypatch, name="duckduckgo")
    _turn(monkeypatch, LLMAdapter(**CLAUDE))
    _calls(monkeypatch, {"anthropic": _status(429, "https://api.anthropic.com/v1/messages"),
                         "duckduckgo": sp.SearchBlocked("challenge")})
    out = await executors.EXECUTORS["web_search"].execute({"query": "q"})
    assert out["code"] == "search_blocked" and out["error"].startswith("search blocked:")
    _calls(monkeypatch, {"anthropic": ValueError("no block"), "duckduckgo": sp.SearchBlocked("challenge")})
    out = await executors.EXECUTORS["web_search"].execute({"query": "q"})
    assert out["code"] == "search_failed" and not out["error"].startswith("search blocked:")
    _settings(monkeypatch, name="tavily", key="tvly-test")
    _calls(monkeypatch, {"tavily": _status(403)})
    out = await executors.EXECUTORS["web_search"].execute({"query": "q"})
    assert out["error"].startswith("search blocked:")

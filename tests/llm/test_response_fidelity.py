"""0.1.49 S1: parsers keep what the native protocol and truncation handling need.

- finish_reason, normalised: "length" is the only signal that a tool call's
  arguments may be cut off.
- reasoning_content (and its OpenRouter cousins), verbatim: DeepSeek rejects a
  tools request whose history drops it.
- the server's exact argument text, for verbatim echo and for evidence.
"""
from arslan.llm.providers.anthropic_provider import AnthropicProvider
from arslan.llm.providers.gemini_provider import GeminiProvider
from arslan.llm.providers.openai_provider import OpenAIProvider

DS = dict(model="deepseek-v4-flash", api_key="k", base_url="https://api.deepseek.com")


def _openai(message, finish="stop"):
    return {"choices": [{"message": {"role": "assistant", **message}, "finish_reason": finish}],
            "usage": {}}


def test_reasoning_content_is_kept_verbatim_with_endpoint_identity():
    p = OpenAIProvider(**DS)
    thought = "  Step 1: list files.\n\nStep 2: …  "
    r = p._parse_response(_openai({"content": "", "reasoning_content": thought,
                                   "tool_calls": [{"id": "c1", "type": "function", "function": {
                                       "name": "list_files", "arguments": "{}"}}]}, "tool_calls"))
    assert r.continuation == {"protocol": "openai", "endpoint": p.endpoint_fingerprint(),
                              "fields": {"reasoning_content": thought}}
    assert r.finish_reason == "tool_calls"


def test_absent_or_null_reasoning_yields_no_continuation():
    """Echo only what the endpoint sent: a strict endpoint must never receive
    a reasoning field it did not produce."""
    p = OpenAIProvider(**DS)
    assert p._parse_response(_openai({"content": "hi"})).continuation is None
    assert p._parse_response(_openai({"content": "hi", "reasoning_content": None})).continuation is None


def test_openrouter_reasoning_fields_are_captured_too():
    p = OpenAIProvider(model="x/y", api_key="k", base_url="https://openrouter.ai/api/v1")
    details = [{"type": "reasoning.encrypted", "data": "opaque"}]
    r = p._parse_response(_openai({"content": "a", "reasoning": "r", "reasoning_details": details,
                                   "unrelated": 1}))
    assert r.continuation["fields"] == {"reasoning": "r", "reasoning_details": details}


def test_endpoint_fingerprint_separates_models_and_endpoints():
    a = OpenAIProvider(**DS).endpoint_fingerprint()
    assert a == OpenAIProvider(**{**DS, "base_url": "https://api.deepseek.com/"}).endpoint_fingerprint()
    assert a != OpenAIProvider(**{**DS, "model": "deepseek-v4-pro"}).endpoint_fingerprint()
    assert a != OpenAIProvider(**{**DS, "base_url": "https://example.test/v1"}).endpoint_fingerprint()


def test_arguments_raw_is_the_servers_exact_text():
    raw = '{ "path" : "a.txt",\n "content": "x" }'
    r = OpenAIProvider(**DS)._parse_response(_openai({"tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "write_file", "arguments": raw}}]}))
    assert r.tool_calls[0]["arguments_raw"] == raw
    assert r.tool_calls[0]["function"]["arguments"] == {"path": "a.txt", "content": "x"}


def test_truncated_call_keeps_raw_text_and_length_finish():
    raw = '{"path": "report.md", "content": "Quarterly results were'
    r = OpenAIProvider(**DS)._parse_response(_openai({"tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "write_file", "arguments": raw}}]},
        "length"))
    assert r.finish_reason == "length"
    assert r.tool_calls[0]["arguments_raw"] == raw
    assert r.tool_calls[0]["function"]["arguments"] == raw  # unparsed; S8 decides what to do


def test_anthropic_max_tokens_is_length_and_tool_use_is_tool_calls():
    p = AnthropicProvider(model="claude-x", api_key="k")
    cut = p._parse_response({"content": [{"type": "text", "text": "partial"}],
                             "stop_reason": "max_tokens", "usage": {}})
    assert cut.finish_reason == "length"
    call = p._parse_response({"content": [{"type": "tool_use", "id": "t", "name": "n",
                                           "input": {"q": "é"}}], "stop_reason": "tool_use", "usage": {}})
    assert call.finish_reason == "tool_calls"
    assert call.tool_calls[0]["arguments_raw"] == '{"q": "é"}'
    assert p._parse_response({"content": [], "stop_reason": "end_turn", "usage": {}}).finish_reason == "stop"


def _gemini(parts, finish):
    return {"candidates": [{"content": {"parts": parts}, "finishReason": finish}]}


def test_gemini_finish_reasons_normalise():
    call = [{"functionCall": {"name": "web_search", "args": {"query": "q"}}}]
    assert GeminiProvider._parse_response(_gemini([{"text": "x"}], "MAX_TOKENS")).finish_reason == "length"
    assert GeminiProvider._parse_response(_gemini(call, "MAX_TOKENS")).finish_reason == "length"
    assert GeminiProvider._parse_response(_gemini(call, "STOP")).finish_reason == "tool_calls"
    assert GeminiProvider._parse_response(_gemini([{"text": "x"}], "STOP")).finish_reason == "stop"
    assert GeminiProvider._parse_response(_gemini([{"text": "x"}], "SAFETY")).finish_reason == "content_filter"

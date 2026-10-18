"""Native function request -> executor -> signed continuation -> final response."""
import json

import httpx

from arslan.llm.adapter import LLMAdapter
from arslan.llm.providers.gemini_provider import GeminiProvider
from server.orchestrator import tool_loop
from server.registry import executors


async def test_signed_parallel_function_responses_roundtrip(monkeypatch):
    requests = []
    executed = []
    parts = [
        {"functionCall": {"name": "web_search", "args": {"query": "one"}, "id": "fc1"},
         "thoughtSignature": "opaque-signed-parts"},
        {"functionCall": {"name": "web_search", "args": {"query": "two"}, "id": "fc2"}},
    ]

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            assert payload["tools"][0]["functionDeclarations"][0]["name"] == "web_search"
            return httpx.Response(200, json={"candidates": [{"content": {"parts": parts}}]})
        assert payload["contents"][-2] == {"role": "model", "parts": parts}
        turn = payload["contents"][-1]["parts"]
        results = [p for p in turn if "functionResponse" in p]
        # The step's status follows the function responses in the same user turn, as text.
        assert turn[:2] == results and all("text" in p for p in turn[2:])
        assert [r["functionResponse"]["id"] for r in results] == ["fc1", "fc2"]
        assert all(r["functionResponse"]["name"] == "web_search" for r in results)
        # 0.1.63 K1: the response is the result itself; this tool's output is untrusted, so it
        # arrives as {"output": <framed text>} rather than the old "TOOL RESULT for X" rendering.
        assert "result-one" in results[0]["functionResponse"]["response"]["output"]
        assert "result-two" in results[1]["functionResponse"]["response"]["output"]
        assert "TOOL RESULT for" not in json.dumps(results)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Both searches completed."}]}}]})

    adapter = LLMAdapter("gemini", "test-model")
    adapter._provider = GeminiProvider("test-model", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(tool_loop, "_get_adapter", lambda: adapter)

    class Search:
        async def execute(self, args):
            executed.append(args["query"])
            return {"ok": True, "external": True, "summary": f"result-{args['query']}"}

    monkeypatch.setitem(executors.EXECUTORS, "web_search", Search())

    async def resolve():
        return [{"key": "web_search", "description": "Search"}]

    result = await tool_loop.run_native(system="test", user_content="Find two sources", history=[],
                                        emit=lambda e: None, on_chunk=lambda c: None, resolve_tools=resolve)
    assert result["final"] == "Both searches completed."
    assert executed == ["one", "two"] and len(requests) == 2

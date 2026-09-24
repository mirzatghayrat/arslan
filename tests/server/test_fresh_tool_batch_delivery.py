"""Fresh parallel reads must reach a model before old-history eviction."""
import json

import pytest

from arslan.companion.research import receipt
from arslan.models import LLMResponse
from arslan.runtime_policy import bounded_history
from server.orchestrator import tool_loop


def test_tail_group_is_temporary_not_permanent_pinning():
    history = [{"role": "user", "content": "old" * 100},
               {"role": "user", "content": "A" * 80}, {"role": "user", "content": "B" * 80}]
    kept, cut = bounded_history(history, max_chars=100, preserve_tail=2)
    assert kept == history[-2:] and cut
    next_kept, next_cut = bounded_history(kept + [{"role": "user", "content": "new"}], max_chars=100)
    assert next_cut and next_kept == [{"role": "user", "content": "new"}]


@pytest.mark.parametrize("size,complete", [(23000, True), (39000, False)])
async def test_actual_loop_delivers_or_explicitly_discloses_large_fresh_batch(monkeypatch, size, complete):
    payloads = []
    texts = {f"https://example.com/{i}": f"SOURCE_{i}_START " + "x" * size + f" SOURCE_{i}_END" for i in range(3)}

    class Adapter:
        async def chat(self, system, user, history=None, **kwargs):
            payloads.append((system, json.dumps((history or []) + [{"role": "user", "content": user}], ensure_ascii=False)))
            if len(payloads) == 1:
                return LLMResponse(content="", usage={}, tool_calls=[{"id": str(i), "type": "function",
                    "function": {"name": "web_extract", "arguments": {"url": url, "max_chars": 40000}}}
                    for i, url in enumerate(texts)])
            return LLMResponse(content="Source-delivery fixture only.", usage={})

    class Executor:
        async def execute(self, args):
            text = texts[args["url"]]
            return {"ok": True, "url": args["url"], "text": text,
                    "source": receipt(args["url"], text, truncated=False).model_dump(mode="json")}

    async def tools():
        return [{"key": "web_extract", "description": "Read supplied source"}]

    monkeypatch.setitem(tool_loop.EXECUTORS, "web_extract", Executor())
    result = await tool_loop.run_native(system="Fixture", user_content="Read three sources", history=[],
        resolve_tools=tools, emit=lambda _: None, on_chunk=lambda _: None, adapter_override=Adapter())
    assert len(payloads) == 2 and len(result["tool_trace"]) == 3
    assert "Read three sources" in payloads[1][1]
    if complete:
        assert all(text in payloads[1][1] for text in texts.values())
        assert "omitted before you saw it" not in payloads[1][0]
    else:
        assert not all(text in payloads[1][1] for text in texts.values())
        assert "omitted before you saw it" in payloads[1][0]


async def test_research_sources_survive_save_readback_without_call_json_imitation(monkeypatch):
    payloads = []
    texts = {f"https://example.com/{i}": f"SOURCE_{i}_START " + "x" * 23000 + f" SOURCE_{i}_END"
             for i in range(3)}
    report = "REPORT_BODY_" + "y" * 30000

    def call(name, args):
        return {"id": str(len(payloads)), "type": "function", "function": {"name": name, "arguments": args}}

    class Adapter:
        async def chat(self, system, user, history=None, **kwargs):
            payloads.append(json.dumps((history or []) + [{"role": "user", "content": user}], ensure_ascii=False))
            if len(payloads) == 1:
                calls = [call("web_extract", {"url": url}) for url in texts]
            elif len(payloads) == 2:
                calls = [call("fixture_save", {"content": report})]
            elif len(payloads) == 3:
                calls = [call("fixture_readback", {})]
            else:
                return LLMResponse(content="Offline source-retention fixture.", usage={})
            return LLMResponse(content="", usage={}, tool_calls=calls)

    class Executor:
        async def execute(self, args):
            if "url" not in args:
                return {"ok": True, "text": "Fixture save/readback succeeded."}
            text = texts[args["url"]]
            return {"ok": True, "url": args["url"], "text": text,
                    "source": receipt(args["url"], text, truncated=False).model_dump(mode="json")}

    async def tools():
        return [{"key": name, "description": "Offline fixture"}
                for name in ("web_extract", "fixture_save", "fixture_readback")]

    for name in ("web_extract", "fixture_save", "fixture_readback"):
        monkeypatch.setitem(tool_loop.EXECUTORS, name, Executor())
    result = await tool_loop.run_native(system="Fixture", user_content="Compare and save", history=[],
        resolve_tools=tools, emit=lambda _: None, on_chunk=lambda _: None, adapter_override=Adapter())
    assert len(payloads) == 4
    assert all(text in payloads[-1] for text in texts.values())
    assert "REPORT_BODY_" not in payloads[-1]
    assert result["tool_trace"][3]["args"]["content"] == report
    assert '"tool":' not in payloads[-1]

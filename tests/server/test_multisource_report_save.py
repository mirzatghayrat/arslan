"""A multi-source report is saved, read back and its web reads compacted, with no extra model call.

Was test_research_review_default_off.py ("no reviewer call by default"). Research review was
removed in C8-2 (v0.1.63); the save path it guarded stays, and `len(adapter.calls) == 4` still
proves no extra model request rides on a saved report.
"""
from arslan.companion.research import receipt
from server.orchestrator import tool_loop
from tests.server.test_native_loop import _NativeAdapter, _LLMResp, _tc


def trace():
    result = []
    for i, text in enumerate(["Measured across 17 tasks. Repetitions not reported.",
                              "Embedding endpoints are configurable."]):
        url = f"https://example.org/source-{i}"
        result.append({"tool": "web_extract", "args": {"url": url}, "result": {
            "ok": True, "url": url, "text": text,
            "source": receipt(url, text, truncated=False).model_dump(mode="json")}})
    return result


async def test_a_multisource_report_saves_without_an_extra_model_call(monkeypatch, tmp_path):
    evidence = trace()
    content = "# Comparison\n\n" + "\n".join(e["result"]["url"] for e in evidence)
    adapter = _NativeAdapter([
        _LLMResp(tool_calls=[_tc("web_extract", e["args"]) for e in evidence]),
        _LLMResp(tool_calls=[_tc("write_file", {"path": "report.md", "content": content})]),
        _LLMResp(tool_calls=[_tc("read_file", {"path": "report.md"})]),
        _LLMResp(content="Saved and read back; sources are navigation, not fact verification."),
    ])

    async def resolve():
        return [{"key": k, "description": k} for k in ("web_extract", "write_file", "read_file")]

    async def dispatch(name, args, assistant_content, **kwargs):
        if name == "web_extract":
            result = next(e["result"] for e in evidence if e["args"] == args)
        elif name == "write_file":
            (tmp_path / "report.md").write_text(args["content"])
            result = {"ok": True, "external": False}
        else:
            result = {"ok": True, "text": (tmp_path / "report.md").read_text()}
        return tool_loop._record_tool_result(name, args, result, kwargs["emit"],
            kwargs["tool_trace"], assistant_content, kwargs["convo"])

    monkeypatch.setattr(tool_loop, "_dispatch_tool", dispatch)
    result = await tool_loop.run_native(system="s", user_content="Compare and save.", history=[],
        emit=lambda _: None, on_chunk=lambda _: None, resolve_tools=resolve, adapter_override=adapter)
    assert (tmp_path / "report.md").read_text() == content
    assert any(e["tool"] == "read_file" and e["result"]["text"] == content for e in result["tool_trace"])
    assert len(adapter.calls) == 4
    assert "body_compacted_after_save" in str(adapter.calls[2])
    assert not any(e["result"].get("review") for e in result["tool_trace"])

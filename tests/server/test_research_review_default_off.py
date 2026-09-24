"""Default path regression: actual isolated disk write/read, no reviewer call."""
import pytest

from server.orchestrator import tool_loop
from tests.server.test_native_loop import _NativeAdapter, _LLMResp, _tc
from tests.server.test_research_review import trace


async def test_default_saves_multisource_report_without_review(monkeypatch, tmp_path):
    evidence = trace()
    content = "# Comparison\n\n" + "\n".join(e["result"]["url"] for e in evidence)
    adapter = _NativeAdapter([
        _LLMResp(tool_calls=[_tc("web_extract", e["args"]) for e in evidence]),
        _LLMResp(tool_calls=[_tc("write_file", {"path": "report.md", "content": content})]),
        _LLMResp(tool_calls=[_tc("read_file", {"path": "report.md"})]),
        _LLMResp(content="Saved and read back; sources are navigation, not fact verification."),
    ])

    async def forbidden(*args, **kwargs):
        pytest.fail("default path must not make a review/model call")

    monkeypatch.setattr("server.orchestrator.research_review.inspect", forbidden)

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
    assert not any(e["result"].get("review") for e in result["tool_trace"])

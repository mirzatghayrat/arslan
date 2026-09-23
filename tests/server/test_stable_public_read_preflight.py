"""Opt-in archived-public-byte replay; NOT live fetch or real-model acceptance."""
import hashlib
import json
import os

import httpx
import pytest

from evals.companion import stable_budget as budget
from evals.companion.stable_sources import sources
from server.registry import net_pin
from server.registry.executors import WebExtractExecutor
from server.orchestrator.tool_loop import _record_tool_result
from arslan.companion.research import admitted_sources
from arslan.runtime_policy import bounded_history

pytestmark = pytest.mark.skipif(os.environ.get("ARSLAN_STABLE_PUBLIC_PREFLIGHT") != "1",
                               reason="requires separately archived public inputs, no model calls")


@pytest.mark.parametrize("source", sources(), ids=lambda source: source["id"])
async def test_archived_source_reaches_bounded_conversation_without_hidden_cut(monkeypatch, source):
    folder = budget.EVIDENCE / "public-inputs"
    metadata = json.loads((folder / f"{source['id']}.json").read_text())
    body = (folder / metadata["file"]).read_bytes()
    assert metadata["url"] == source["url"]
    assert hashlib.sha256(body).hexdigest() == metadata["sha256"]
    if source.get("sha256"):
        assert metadata["sha256"] == source["sha256"]
    calls = []

    async def archived_response(url):
        assert url == source["url"]
        calls.append(url)
        return httpx.Response(200, content=body, headers={"Content-Type": metadata["content_type"]},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(net_pin, "pinned_get", archived_response)
    executor = WebExtractExecutor()
    initial = await executor.execute({"url": source["url"]})
    args = {"url": source["url"], "max_chars": 40_000}
    expanded = await executor.execute(args)
    assert expanded["ok"] is True and expanded["source"]["truncated"] is False
    assert expanded["returned_chars"] == expanded["total_chars"] <= 40_000
    assert initial["returned_chars"] <= 12_000
    trace, convo = [], []
    delivered = _record_tool_result("web_extract", args, expanded, lambda _: None, trace, "read source", convo)
    assert delivered["text"] == expanded["text"]
    assert delivered["source"]["truncated"] is False
    assert admitted_sources(trace)
    kept, compacted = bounded_history(convo)
    assert not compacted
    assert '"text_sha256"' in kept[-1]["content"] and '"truncated": false' in kept[-1]["content"]
    assert len(calls) == 2  # Both requests use archived bytes, never the network.
    output = budget.EVIDENCE / "public-reader-preflight-v1"
    output.mkdir(exist_ok=True)
    with (output / f"{source['id']}.json").open("x", encoding="utf-8") as stream:
        json.dump({"source": metadata, "transport": "archived bytes, no network",
                   "default_read_chars": initial["returned_chars"],
                   "default_truncated": initial["source"]["truncated"],
                   "expanded_result": delivered, "model_calls": 0, "quality_status": "not_run"},
                  stream, ensure_ascii=False, indent=2)

"""Exercise the exact research runner without a key, network or real model."""
from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from arslan.llm.adapter import LLMAdapter
from evals.companion import stable_budget as budget, stable_research as research
from server.registry import net_pin
from tests.server import test_stable_research_live as runner


async def test_research_runner_offline(execution_db, monkeypatch, tmp_path):
    evidence = tmp_path / "evidence"
    monkeypatch.setattr(budget, "EVIDENCE", evidence)
    monkeypatch.setenv("ARSLAN_STABLE_LIVE", "authorized-36-requests-usd5")
    monkeypatch.setenv("ARSLAN_STABLE_PRICING", "pricing.json")
    budget.initialize()
    urls = ["https://arxiv.org/abs/1807.06209v4", "https://arxiv.org/abs/2112.04510v3"]
    bodies = [b"<html><body><article><h1>Synthetic source</h1><p>Isolated fixture data for the first source. No actual scientific claims.</p></article></body></html>",
              b"<html><body><article><h1>Other synthetic source</h1><p>Isolated fixture data for the second source. No real scientific comparison.</p></article></body></html>"]
    inputs = []
    for index, body in enumerate(bodies):
        path = evidence / f"source-{index}.html"
        path.write_bytes(body)
        inputs.append({"path": path.name, "sha256": hashlib.sha256(body).hexdigest()})
    (evidence / "S2-R2-preflight.json").write_text(json.dumps({"case": "S2-R2", "status": "ready",
        "contract_sha256": budget.contract()[1], "inputs": inputs, "urls": urls,
        "prompt": "Compare the two synthetic sources", "public_same_scope_conflict_review": {"offline_fixture_only": True}}))
    research.freeze()
    (evidence / "pricing.json").write_text(json.dumps({
        "verified_on_utc": datetime.now(timezone.utc).date().isoformat(),
        "provider": "deepseek", "model": "deepseek-v4-flash", "endpoint": "https://api.deepseek.com",
        "source": "https://api-docs.deepseek.com/quick_start/pricing/",
        "input_usd_per_million": "0.30", "output_usd_per_million": "1.20"}))

    async def fake_get(url):
        return httpx.Response(200, content=bodies[urls.index(url)], request=httpx.Request("GET", url))

    monkeypatch.setattr(net_pin, "pinned_get", fake_get)

    def reply(calls=(), content=""):
        return SimpleNamespace(content=content, usage={"prompt_tokens": 100, "completion_tokens": 20},
            tool_calls=[{"id": str(index) + key, "type": "function", "function": {"name": key, "arguments": args}}
                        for index, (key, args) in enumerate(calls)])

    adapter = LLMAdapter("openai", "deepseek-v4-flash", base_url="https://api.deepseek.com", report_provider="deepseek")
    adapter.chat = AsyncMock(side_effect=[reply([("web_extract", {"url": url}) for url in urls]),
        reply([("write_file", {"path": "comparison.md", "content": "# Synthetic comparison\n" + "\n".join(urls)})]),
        reply([("read_file", {"path": "comparison.md"})]), reply(content="Synthetic execution fixture, not a quality pass.")])
    monkeypatch.setattr(runner, "primary_adapter", lambda *args: adapter)
    await runner.test_stable_research_host(execution_db, monkeypatch, tmp_path)
    assert budget.status()["by_case"]["S2-R2"] == adapter.chat.await_count == 4
    value = json.loads((evidence / "S2-R2-result.json").read_bytes())
    assert len(value["transport"]) == 2 and all(item["matches_frozen_input"] for item in value["transport"])
    assert value["persisted_in_isolated_db"]
    with pytest.raises(RuntimeError, match="no_automatic_case_repeat"):
        await runner.test_stable_research_host(execution_db, monkeypatch, tmp_path)
    # A changed additive plan is refused without touching the original preflight.
    path = evidence / "S2-R2-runner-plan-v1.json"
    changed = json.loads(path.read_bytes())
    changed["prompt"] += " changed"
    path.write_text(json.dumps(changed))
    with pytest.raises(RuntimeError, match="runner_changed"):
        research.verified()

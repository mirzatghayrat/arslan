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

# Offline runner behaviour against a current-tree copy of the stable contract;
# the historical contract itself is immutable (see conftest.offline_stable_contract).
pytestmark = pytest.mark.usefixtures("offline_stable_contract")


@pytest.mark.parametrize("case", research.CASES)
@pytest.mark.parametrize("failed_final", [False, True])
async def test_research_runner_offline(execution_db, monkeypatch, tmp_path, case, failed_final, protocol_correction=False):
    evidence = tmp_path / "evidence"
    monkeypatch.setattr(budget, "EVIDENCE", evidence)
    monkeypatch.setenv("ARSLAN_STABLE_LIVE", "authorized-36-requests-usd5")
    monkeypatch.setenv("ARSLAN_STABLE_PRICING", "pricing.json")
    budget.initialize()
    urls = ["https://arxiv.org/abs/1807.06209v4", "https://arxiv.org/abs/2112.04510v3"]
    if case == "S2-R4":
        urls = ["https://raw.githubusercontent.com/synthetic/repo/fixed/README.md",
                "https://raw.githubusercontent.com/synthetic/repo/fixed/README.zh-Hans.md"]
    bodies = [b"<html><body><article><h1>Synthetic source</h1><p>Isolated fixture data for the first source. No actual scientific claims.</p></article></body></html>",
              b"<html><body><article><h1>Other synthetic source</h1><p>Isolated fixture data for the second source. No real scientific comparison.</p></article></body></html>"]
    if case == "S2-R1":
        urls.append("https://example.com/third-public-source")
        bodies.append(b"<html><body><article><h1>Third synthetic source</h1><p>Third isolated fixture, not a live project.</p></article></body></html>")
    inputs = []
    for index, body in enumerate(bodies):
        path = evidence / f"source-{index}.html"
        path.write_bytes(body)
        inputs.append({"path": path.name, "sha256": hashlib.sha256(body).hexdigest()})
    (evidence / f"{case}-preflight.json").write_text(json.dumps({"case": case, "status": "ready",
        "contract_sha256": budget.contract()[1], "inputs": inputs, "urls": urls,
        "prompt": "Compare the supplied synthetic sources", "public_same_scope_conflict_review": {"offline_fixture_only": True}}))
    research.freeze(case)
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
    replies = [reply([("web_extract", {"url": url, "max_chars": 40000}) for url in urls]),
        reply([("write_file", {"path": "comparison.md", "content": "# Synthetic comparison\n" + "\n".join(urls)})]),
        reply([("read_file", {"path": "comparison.md"})]),
        RuntimeError("synthetic_final_failure") if failed_final else reply(content="Synthetic execution fixture, not a quality pass.")]
    if protocol_correction:
        replies.insert(1, reply(content='{"tool":"write_file","args":{"content":"auth = "none""}}'))
    adapter.chat = AsyncMock(side_effect=replies)
    monkeypatch.setattr(runner, "primary_adapter", lambda *args: adapter)
    if failed_final:
        with pytest.raises(AssertionError):
            await runner.test_stable_research_host(case, execution_db, monkeypatch, tmp_path)
    else:
        await runner.test_stable_research_host(case, execution_db, monkeypatch, tmp_path)
    assert budget.status()["by_case"][case] == adapter.chat.await_count == 4 + int(protocol_correction)
    value = json.loads((evidence / f"{case}-result.json").read_bytes())
    assert len(value["transport"]) == len(urls) and all(item["matches_frozen_input"] for item in value["transport"])
    assert value["persisted_in_isolated_db"] is not failed_final
    assert (evidence / f"{case}-comparison.md").read_text().startswith("# Synthetic comparison")
    assert all(json.loads((evidence / f"{case}-artifact-review.json").read_bytes())["checks"].values())
    if failed_final:
        assert value["answer"] is None and (evidence / "HALT").exists()
    with pytest.raises(RuntimeError, match="no_automatic_case_repeat"):
        await runner.test_stable_research_host(case, execution_db, monkeypatch, tmp_path)
    # A changed additive plan is refused without touching the original preflight.
    path = evidence / f"{case}-runner-plan-v1.json"
    changed = json.loads(path.read_bytes())
    changed["prompt"] += " changed"
    path.write_text(json.dumps(changed))
    with pytest.raises(RuntimeError, match="runner_changed"):
        research.verified(case)


async def test_r1_protocol_correction_reaches_real_file_and_owned_artifact(execution_db, monkeypatch, tmp_path):
    await test_research_runner_offline(execution_db, monkeypatch, tmp_path, "S2-R1", False, protocol_correction=True)

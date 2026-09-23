"""Offline exact-runner checks; no primary profile, key or paid provider."""
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from arslan.llm.adapter import LLMAdapter
from evals.companion import stable_budget as budget, stable_memory as inputs
from tests.server import test_stable_memory_live as runner


@pytest.mark.parametrize("case_id", inputs.CASES)
async def test_exact_memory_runner_and_context_boundary(execution_db, monkeypatch, tmp_path, case_id):
    monkeypatch.setattr(budget, "EVIDENCE", tmp_path / "evidence")
    monkeypatch.setenv("ARSLAN_STABLE_LIVE", "authorized-36-requests-usd5")
    monkeypatch.setenv("ARSLAN_STABLE_PRICING", "pricing.json")
    budget.initialize()
    inputs.freeze(case_id)
    (budget.EVIDENCE / "pricing.json").write_text(json.dumps({
        "verified_on_utc": datetime.now(timezone.utc).date().isoformat(), "provider": "deepseek",
        "model": "deepseek-v4-flash", "endpoint": "https://api.deepseek.com",
        "source": "https://api-docs.deepseek.com/quick_start/pricing/",
        "input_usd_per_million": "0.30", "output_usd_per_million": "1.20"}))
    adapter = LLMAdapter("openai", "deepseek-v4-flash", base_url="https://api.deepseek.com", report_provider="deepseek")
    adapter.chat = AsyncMock(return_value=SimpleNamespace(content="Synthetic smoke answer, not model-quality evidence.",
        tool_calls=[], usage={"prompt_tokens": 100, "completion_tokens": 20}))
    monkeypatch.setattr(runner, "primary_adapter", lambda *args: adapter)
    await runner.test_stable_memory_host(case_id, execution_db, monkeypatch, tmp_path)
    assert budget.status()["requests"] == adapter.chat.await_count == 2
    payloads = [(budget.EVIDENCE / f"request-{i:02d}.input.json").read_text() for i in (1, 2)]
    if case_id == "S2-M1":
        assert inputs.CASES[case_id]["entry"] in payloads[0]
        assert inputs.CASES[case_id]["entry"] not in payloads[1]
    elif case_id == "S2-M2":
        assert inputs.CASES[case_id]["entry"] not in payloads[0]
        assert inputs.CASES[case_id]["entry"] not in payloads[1]
        assert inputs.CASES[case_id]["correction"] in payloads[1]
    else:
        assert all("violet" not in payload.lower() for payload in payloads)
    result = json.loads((budget.EVIDENCE / f"{case_id}-result.json").read_bytes())
    assert all(turn["persisted"] for turn in result["turns"])
    assert result["quality_status"] == result["native_status"] == "not_run"
    if case_id == "S2-M3":
        assert result["deletion_evidence"]["old_summary_removed"]
        assert result["deletion_evidence"]["original_chat_retained"]
        assert result["deletion_evidence"]["regenerated_summaries"]
    with pytest.raises(RuntimeError, match="no_automatic_case_repeat"):
        await runner.test_stable_memory_host(case_id, execution_db, monkeypatch, tmp_path)


def test_memory_preflight_refuses_changed_inputs(monkeypatch, tmp_path):
    monkeypatch.setattr(budget, "EVIDENCE", tmp_path)
    inputs.freeze("S2-M1")
    path = tmp_path / "S2-M1-synthetic-memory.json"
    data = json.loads(path.read_bytes())
    data["projects"][1]["id"] = "project-a"
    path.write_text(json.dumps(data))
    with pytest.raises(RuntimeError, match="preflight_changed"):
        inputs.verified("S2-M1")

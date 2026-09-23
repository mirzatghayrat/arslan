"""Exercise the exact opt-in runner with a local provider double, never a key."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json

import pytest

from arslan.llm.adapter import LLMAdapter
from evals.companion import stable_budget as budget, stable_documents as documents
from tests.server import test_stable_document_live as runner


@pytest.mark.parametrize("case_id", documents.DOCUMENT_CASES)
async def test_document_runner_offline(execution_db, monkeypatch, tmp_path, case_id):
    evidence = tmp_path / "evidence"
    monkeypatch.setattr(budget, "EVIDENCE", evidence)
    monkeypatch.setenv("ARSLAN_STABLE_LIVE", "authorized-36-requests-usd5")
    monkeypatch.setenv("ARSLAN_STABLE_PRICING", "pricing.json")
    monkeypatch.setattr(documents.ingest.ocr_vision, "is_available", lambda: False)
    budget.initialize()
    documents.freeze(case_id)
    (evidence / "pricing.json").write_text(json.dumps({
        "verified_on_utc": datetime.now(timezone.utc).date().isoformat(),
        "provider": "deepseek", "model": "deepseek-v4-flash", "endpoint": "https://api.deepseek.com",
        "source": "https://api-docs.deepseek.com/quick_start/pricing/",
        "input_usd_per_million": "0.30", "output_usd_per_million": "1.20"}))
    adapter = LLMAdapter("openai", "deepseek-v4-flash", base_url="https://api.deepseek.com", report_provider="deepseek")
    adapter.chat = AsyncMock(return_value=SimpleNamespace(content="Synthetic runner smoke answer, not quality evidence.",
        tool_calls=[], usage={"prompt_tokens": 100, "completion_tokens": 20}))
    monkeypatch.setattr(runner, "primary_adapter", lambda *args: adapter)
    await runner.test_stable_document_host(case_id, execution_db, monkeypatch, tmp_path)
    assert budget.status()["requests"] == 1
    adapter.chat.assert_awaited_once()
    record = json.loads((evidence / f"{case_id}-result.json").read_bytes())
    assert record["persisted_in_isolated_db"] and record["quality_status"] == "not_run"
    with pytest.raises(RuntimeError, match="no_automatic_case_repeat"):
        await runner.test_stable_document_host(case_id, execution_db, monkeypatch, tmp_path)

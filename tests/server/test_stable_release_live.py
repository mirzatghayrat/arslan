import os
import json
from pathlib import Path
import pytest
from evals.companion import stable_release_retest as release

pytestmark = pytest.mark.skipif(os.environ.get("ARSLAN_STABLE_RELEASE") != release.OPT_IN,
                               reason="independent cumulative 60/$6 grant required")


@pytest.mark.parametrize("case", ["S2-R1", "S2-R4"])
@pytest.mark.timeout(600)
async def test_research(case, execution_db, monkeypatch, tmp_path):
    from tests.server.test_stable_research_live import test_stable_research_host
    with release.bound():
        await test_stable_research_host(case, execution_db, monkeypatch, tmp_path)


@pytest.mark.timeout(120)
async def test_registered_report_review(monkeypatch):
    """One accounted critique of retained data; NOT an end-to-end R4 pass."""
    import httpx
    from evals.companion import stable_budget as budget, stable_research as research
    from evals.companion.stable_live import StableAdapter, persist
    from evals.companion.stable_primary import primary_adapter, pricing_snapshot
    from evals.companion.stable_retest import digest
    from server.orchestrator import research_review
    with release.bound():
        assert os.environ["ARSLAN_RELEASE_ROUND"] == "7"
        assert budget.status()["requests"] == 0
        parent = release.MASTER / "round-6"
        response_file = parent / "request-06.response.json"
        result_file = parent / "S2-R4-result.json"
        assert digest(response_file) == "357231cca9a96fb9f70f79e6ea4760fb031fd8492498b19919e2ff4cdbb5edf3"
        assert digest(result_file) == "f35dea7fa6fab68ea10d18c80082c93936c5058e39d276786b17d39831894b87"
        ready = research.verified("S2-R4")
        call = json.loads(response_file.read_bytes())["tool_calls"][0]["function"]
        trace = json.loads(result_file.read_bytes())["tool_trace"]
        subject = research_review.subject(call["name"], call["arguments"], trace, request=ready["prompt"])
        assert subject is not None
        persist(budget.EVIDENCE / "review-probe-plan.json", {
            "kind": "single_registered_report_review_not_task_completion",
            "source_baseline": budget.contract()[0]["source_baseline"],
            "parent_response_sha256": digest(response_file), "parent_result_sha256": digest(result_file),
            "subject_sha256": subject[0], "max_requests": 1, "reserved_usd": "0.10"})
        original_send = httpx.AsyncClient.send

        async def send(client, request, **kwargs):
            if request.method != "POST" or str(request.url) not in {
                    "https://api.deepseek.com/chat/completions", "https://api.deepseek.com/v1/chat/completions"}:
                raise RuntimeError("review_probe_unapproved_network")
            return await original_send(client, request, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "send", send)
        pricing = pricing_snapshot(budget.EVIDENCE / os.environ["ARSLAN_STABLE_PRICING"])
        adapter = StableAdapter(primary_adapter(Path.home() / "Library/Application Support/Arslan",
            Path.home() / ".arslan/secret_key", pricing), "S2-R4", pricing, ready["preflight_sha256"])

        async def chat(adapter, system, user, **kwargs):
            return await adapter.chat(system, user, **kwargs)

        result = await research_review.inspect(subject, adapter=adapter, chat=chat, cache={})
        persist(budget.EVIDENCE / "review-probe-result.json", result)
        assert budget.status()["requests"] == 1

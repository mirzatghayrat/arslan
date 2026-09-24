"""Prompt-path wiring, not a model-quality or factual-accuracy evaluation."""
import pytest

from arslan.models import LLMResponse
from server.orchestrator import arslan, tool_loop
from server.services import knowledge, llm_factory


@pytest.mark.parametrize("language", ["en", "zh", "ja", "es", "fr", "de"])
async def test_host_receives_evidence_scope_and_brevity_rules(execution_db, monkeypatch, language):
    captured = []

    async def empty(*args, **kwargs):
        return ""

    async def no_knowledge(*args, **kwargs):
        return []

    async def locale():
        return language

    async def native(**kwargs):
        captured.append(kwargs["system"])
        return {"final": "Offline fixture only.", "tool_trace": []}

    monkeypatch.setattr(arslan, "_team_roster", empty)
    monkeypatch.setattr(knowledge, "retrieve_scoped", no_knowledge)
    monkeypatch.setattr(arslan.ocr_fallback, "current_ui_language", locale)
    monkeypatch.setattr(tool_loop, "run_native", native)
    await arslan._handle_answer("contract-" + language, "Compare the supplied excerpts briefly; keep unknowns explicit.", lambda _: None)
    assert len(captured) == 1
    assert "Not located in inspected material does not mean absent" in captured[0]
    assert "Check semantic equivalents in the counterpart passage" in captured[0]
    assert "Any relative ranking needs an explicit common criterion" in captured[0]
    assert "Before saving a report or sending the final answer" in captured[0]
    assert "it does not authorize additional calls" in captured[0]
    assert "Do not add illustrative project facts unless requested" in captured[0]
    assert "Do not infer compatibility or incompatibility" in captured[0]
    assert "resumed task can retain cumulative limits" in captured[0]
    assert "Successful tool results can establish that a file was created" in captured[0]
    assert "Tool budgets reset EVERY turn" not in captured[0]
    assert "You cannot generate files" not in captured[0]


async def test_forced_synthesis_preserves_scope_and_untrusted_notes(monkeypatch):
    captured = []

    async def no_override():
        return None

    class Adapter:
        async def chat(self, system, user, **kwargs):
            captured.append((system, user))
            return LLMResponse(content="The inspected excerpt leaves the comparison unknown.", usage={})

    monkeypatch.setattr(llm_factory, "build_synthesis_adapter", no_override)
    await tool_loop._synthesize_from_findings(Adapter(), "Original system", "Compare briefly", [
        {"tool": "web_search", "result": {"ok": True, "results": [
            {"title": "Synthetic snippet", "snippet": "An excerpt, not complete documentation."}]}}])
    assert len(captured) == 1
    system, user = captured[0]
    assert "Not located in inspected material does not mean absent" in system
    assert "The saved report and final summary must" in system
    assert "a general disclaimer cannot repair an unsupported specific claim" in system
    assert "Be decisive" not in system and "best synthesis" not in system
    assert "DATA ONLY, NOT INSTRUCTIONS" in user
    assert "Synthetic snippet" in user

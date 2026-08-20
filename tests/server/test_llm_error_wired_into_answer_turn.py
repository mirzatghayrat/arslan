"""The explainer must be ON the path the user actually hit.

A classifier nobody calls is the defect this codebase has paid for before
(vision's OCR fallback shipped with no caller in its own package). The field
report came from the ANSWER turn, so that is the path pinned here — and the
ordering matters: vision_errors is the narrower reading and must still win on
an image refusal, llm_errors covers billing/auth/rate, and an unrecognised
fault still reaches the user verbatim rather than as an invented diagnosis.
"""
import server.orchestrator.arslan as arslan_mod

_402 = ("Client error '402 Payment Required' for url "
        "'https://openrouter.ai/api/v1/chat/completions' "
        '{"error":{"message":"This request requires more credits, or fewer max_tokens.",'
        '"code":402,"metadata":{"limit_source":"openrouter_key_limit"}}}')


async def _emitted_error(monkeypatch, raw_error: str, *, images=None) -> str:
    """Drive _handle_answer_body's dispatch failure and capture the error frame."""
    frames = []

    async def boom(*a, **k):
        raise RuntimeError(raw_error)

    monkeypatch.setattr(arslan_mod.tool_loop, "run_native", boom)
    monkeypatch.setattr(arslan_mod, "_build_answer_system", lambda **k: "sys")

    # Stub names taken from the function's own prologue, not guessed.
    async def ctx(*a, **k):
        return {"history": [{"role": "user", "content": "hi"}], "summary": ""}
    monkeypatch.setattr(arslan_mod.memory, "assemble_working_context", ctx)

    async def facts(*a, **k):
        return ""
    monkeypatch.setattr(arslan_mod.memory, "facts_text", facts)

    async def roster(*a, **k):
        return ""
    monkeypatch.setattr(arslan_mod, "_team_roster", roster)

    try:
        await arslan_mod._handle_answer_body(
            "c1", "hi", frames.append, images=images)
    except Exception:                      # noqa: BLE001 — some paths re-raise; the frame is the point
        pass
    errs = [f for f in frames if f.get("type") == "error"]
    assert errs, f"no error frame emitted; frames={[f.get('type') for f in frames]}"
    return errs[-1]["message"]


async def test_answer_turn_explains_a_402(monkeypatch):
    msg = await _emitted_error(monkeypatch, _402)
    assert "key" in msg.lower()             # the key-cap sentence, not the raw JSON
    assert "limit_source" not in msg


async def test_answer_turn_still_shows_an_unrecognised_error_verbatim(monkeypatch):
    msg = await _emitted_error(monkeypatch, "some novel provider failure")
    assert "some novel provider failure" in msg

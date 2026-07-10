"""E1 / audit CRITICAL-2: the paired judge sees BOTH arms' step-evidence traces.

compare() renders each arm's evidence in BOTH position-swap passes, and when the
outputs swap positions the evidence swaps WITH its arm — evidence stays attached
to the output it belongs to. Default empty evidence keeps the old prompt shape
(existing compare tests stay green).
"""
import json

from arslan.models import LLMResponse
from server.services import compare_judge

EVIDENCE_A = "[tool_call] tool=web_search args=q=arm-A-query → ok found A sources"
EVIDENCE_B = "[tool_call] tool=run_python args=arm-B-script → ok B computed"

OUTPUT_A = "ARM-A-FINAL-OUTPUT"
OUTPUT_B = "ARM-B-FINAL-OUTPUT"


class _CapturingAdapter:
    """Returns canned content per chat() call (pass1 then pass2), capturing prompts."""

    def __init__(self, responses, captured: list):
        self._responses = list(responses)
        self._captured = captured

    async def chat(self, system, user):
        self._captured.append({"system": system, "user": user})
        return LLMResponse(content=self._responses.pop(0), usage={})


def _stub(monkeypatch, responses) -> list:
    captured: list = []

    async def fake_build(role=None):
        return _CapturingAdapter(responses, captured)
    monkeypatch.setattr(compare_judge, "build_adapter", fake_build)
    return captured


def _resp(value):
    return json.dumps({
        "dimensions": {"fabrication": value, "identity": value, "completion": value},
        "overall": value, "margin": 5, "reason": "r",
    })


async def test_C2_compare_prompt_contains_both_arm_traces(monkeypatch):
    captured = _stub(monkeypatch, [_resp("1"), _resp("2")])
    await compare_judge.compare(
        task="t", persona="p", output_a=OUTPUT_A, output_b=OUTPUT_B,
        evidence_a=EVIDENCE_A, evidence_b=EVIDENCE_B,
    )
    assert len(captured) == 2
    p1, p2 = captured[0]["user"], captured[1]["user"]

    # BOTH passes carry BOTH arms' evidence
    for p in (p1, p2):
        assert EVIDENCE_A in p
        assert EVIDENCE_B in p

    # pass 1: ①=A → order is output_a, evidence_a, output_b, evidence_b
    assert p1.index(OUTPUT_A) < p1.index(EVIDENCE_A) < p1.index(OUTPUT_B) < p1.index(EVIDENCE_B)
    # pass 2: positions swap and the evidence swaps WITH its arm
    assert p2.index(OUTPUT_B) < p2.index(EVIDENCE_B) < p2.index(OUTPUT_A) < p2.index(EVIDENCE_A)


async def test_default_empty_evidence_keeps_old_prompt_shape(monkeypatch):
    captured = _stub(monkeypatch, [_resp("1"), _resp("2")])
    out = await compare_judge.compare(
        task="t", persona="p", output_a=OUTPUT_A, output_b=OUTPUT_B,
    )
    assert out["overall"] == "a"  # old merge semantics untouched
    for c in captured:
        assert "执行证据" not in c["user"]


async def test_compare_system_has_verbosity_rubric(monkeypatch):
    captured = _stub(monkeypatch, [_resp("tie"), _resp("tie")])
    await compare_judge.compare(task="t", persona="p", output_a="A", output_b="B")
    assert "长答案不因长而胜" in captured[0]["system"]

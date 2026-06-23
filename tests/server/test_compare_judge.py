import pytest

from arslan.models import LLMResponse
from server.services import compare_judge


class _FakeAdapter:
    """Returns canned content per chat() call (pass1 then pass2)."""
    def __init__(self, responses):
        self._responses = list(responses)

    async def chat(self, system, user):
        return LLMResponse(content=self._responses.pop(0), usage={})


def _stub(monkeypatch, responses):
    async def fake_build(role=None):
        return _FakeAdapter(responses)
    monkeypatch.setattr(compare_judge, "build_adapter", fake_build)


def _resp(fab, ident, comp, overall, margin=5, reason="r"):
    import json
    return json.dumps({
        "dimensions": {"fabrication": fab, "identity": ident, "completion": comp},
        "overall": overall, "margin": margin, "reason": reason,
    })


async def test_consistent_winner_a(monkeypatch):
    # pass1 ①=A,②=B → "1" means A better. pass2 ①=B,②=A → "2" means A better.
    _stub(monkeypatch, [_resp("1", "1", "1", "1", margin=6),
                        _resp("2", "2", "2", "2", margin=4)])
    out = await compare_judge.compare(task="t", persona="p", output_a="A", output_b="B")
    assert out["overall"] == "a"
    assert out["dimensions"] == {"fabrication": "a", "identity": "a", "completion": "a"}
    assert out["position_sensitive"] is False
    assert out["margin"] == 5.0  # (6+4)/2


async def test_overall_flip_is_tie_and_position_sensitive(monkeypatch):
    # pass1 overall "1" → A. pass2 overall "1" → B (since ①=B). Flip → tie.
    _stub(monkeypatch, [_resp("1", "1", "1", "1"),
                        _resp("1", "1", "1", "1")])
    out = await compare_judge.compare(task="t", persona="p", output_a="A", output_b="B")
    assert out["overall"] == "tie"
    assert out["position_sensitive"] is True
    assert out["margin"] == 0.0


async def test_ab_mapping_across_swap(monkeypatch):
    # fabrication: pass1 "1"(A), pass2 "2"(A) → a.  identity: pass1 "2"(B), pass2 "1"(B) → b.
    # completion disagree → tie. overall tie.
    _stub(monkeypatch, [_resp("1", "2", "1", "tie"),
                        _resp("2", "1", "1", "tie")])
    out = await compare_judge.compare(task="t", persona="p", output_a="A", output_b="B")
    assert out["dimensions"]["fabrication"] == "a"
    assert out["dimensions"]["identity"] == "b"
    assert out["dimensions"]["completion"] == "tie"


async def test_degraded_on_unparseable(monkeypatch):
    _stub(monkeypatch, ["not json", _resp("1", "1", "1", "1")])
    out = await compare_judge.compare(task="t", persona="p", output_a="A", output_b="B")
    assert out["overall"] == "tie"
    assert out["position_sensitive"] is True
    assert out["dimensions"] == {"fabrication": "tie", "identity": "tie", "completion": "tie"}

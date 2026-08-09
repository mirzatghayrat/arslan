"""The chat turn reports which model answered it.

🔴 THE DATA WAS ALREADY BEING COMPUTED AND THROWN AWAY. usage_sink.detail() returns a
per-(model, provider) breakdown under "buckets", every turn, with a sticky `estimated`
flag — and _usage_frame dropped it, keeping only the numbers. Run rows carry
`model`/`provider`, but the CHAT answer path writes no Run row, so the one surface a
person actually watches has never said who answered.

That matters more now, not less: spec ② lets a task be routed to a different model on
purpose. "降级必须界面可见 —— 不许默默换模型花用户的钱" is only enforceable if the
frame says which model ran.

🔴 AND WHEN MORE THAN ONE MODEL RAN, ALL OF THEM ARE REPORTED. usage_sink.primary()
returns the biggest bucket, which is the right default for a single label — but using
it here would hide exactly the event this exists to surface. A turn that quietly used
two models must not look like a turn that used one.
"""
from __future__ import annotations

import pytest

from arslan.llm import usage_sink
from server.orchestrator import arslan


@pytest.fixture(autouse=True)
def _collecting():
    with usage_sink.collecting():
        yield


def _frame() -> dict:
    return arslan._usage_frame(usage_sink.detail())


class TestOneModel:
    def test_the_frame_names_it(self):
        usage_sink.report_detail(tokens_in=100, tokens_out=40,
                                 model="deepseek-chat", provider="deepseek")

        frame = _frame()

        assert frame["models"] == [{"model": "deepseek-chat", "provider": "deepseek"}]

    def test_the_numbers_are_untouched(self):
        # The frame's existing contract must not shift while a field is added to it.
        usage_sink.report_detail(tokens_in=100, tokens_out=40,
                                 model="deepseek-chat", provider="deepseek")
        usage_sink.report(140)

        frame = _frame()

        assert frame["tokens_in"] == 100
        assert frame["tokens_out"] == 40
        assert frame["estimated"] is False


class TestTwoModels:
    def test_both_are_reported_not_just_the_biggest(self):
        # THE case. usage_sink.primary() would answer "deepseek" here and the turn
        # would look single-model — hiding the swap this field exists to reveal.
        usage_sink.report_detail(tokens_in=1000, tokens_out=200,
                                 model="deepseek-chat", provider="deepseek")
        usage_sink.report_detail(tokens_in=10, tokens_out=5,
                                 model="gpt-4o-mini", provider="openai")

        models = _frame()["models"]

        assert len(models) == 2, models
        assert {m["model"] for m in models} == {"deepseek-chat", "gpt-4o-mini"}

    def test_the_biggest_bucket_leads(self):
        # Ordering is not cosmetic: the first entry is what a narrow UI shows, and the
        # model that did most of the work is the honest headline.
        usage_sink.report_detail(tokens_in=10, tokens_out=5,
                                 model="gpt-4o-mini", provider="openai")
        usage_sink.report_detail(tokens_in=1000, tokens_out=200,
                                 model="deepseek-chat", provider="deepseek")

        assert _frame()["models"][0]["model"] == "deepseek-chat"


class TestNothingToSay:
    def test_a_turn_with_no_llm_call_reports_no_models(self):
        # Empty list, not a fabricated entry: a turn that called no model must not
        # claim one.
        assert _frame()["models"] == []

    def test_a_bucket_with_no_model_name_is_dropped(self):
        # usage_sink allows model=None. Rendering "None" as a model name would be a
        # confident-looking lie on the one line meant to be trustworthy.
        usage_sink.report_detail(tokens_in=10, tokens_out=5, model=None, provider=None)

        assert _frame()["models"] == []


class TestTheFieldReachesTheClient:
    def test_the_frontend_type_declares_it(self):
        # Backend-only would be the containment shape again: a field on the wire that
        # nothing can consume. The TS interface is the contract the UI reads.
        import pathlib

        types = pathlib.Path(__file__).resolve().parents[2] / "web/src/api/client.types.ts"
        src = types.read_text()
        block = src[src.index("interface StreamUsage"):]
        block = block[:block.index("}")]
        assert "models" in block, "StreamUsage does not carry models"

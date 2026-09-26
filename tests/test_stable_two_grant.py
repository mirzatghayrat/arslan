import pytest
from evals.companion import stable_budget as budget, stable_four_retest as four, stable_two_retest as two


def test_two_grant_restores_original_envelope():
    original = four.EVIDENCE, four.CAPS, four.REQUESTS, four.USD
    with two.configured():
        assert four.CAPS == {"S2-R1": 6, "S2-R4": 6}
        assert four.REQUESTS == 12 and four.USD == "1.20"
        assert four.PARENT == original[0]
        assert four.EVIDENCE != original[0]
    assert (four.EVIDENCE, four.CAPS, four.REQUESTS, four.USD) == original


def test_twelve_call_grant_cannot_reserve_thirteen():
    assert budget.grant_limits({"max_requests": 12, "max_usd": "1.20"})[:2] == (12, "1.20")
    with pytest.raises(RuntimeError):
        budget.grant_limits({"max_requests": 13, "max_usd": "1.20"})

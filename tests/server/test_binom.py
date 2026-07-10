"""Exact one-sided binomial p-value + Wilson 95% CI (S2 E4 statistical honesty).

These back the evidence-tier label and the p-value/CI shown on every promotion card.
"""
from server.services import binom


def test_p_value_six_of_ten():
    # P(X>=6 | n=10, p=0.5) = (210+120+45+10+1)/1024 = 386/1024
    assert abs(binom.p_value(6, 10) - 0.376953125) < 1e-9
    assert abs(binom.p_value(6, 10) - 0.377) < 1e-3


def test_p_value_ten_of_ten():
    # P(X>=10 | n=10) = 1/1024
    assert abs(binom.p_value(10, 10) - 0.0009765625) < 1e-12
    assert abs(binom.p_value(10, 10) - 0.000977) < 1e-5


def test_p_value_zero_n_is_safe():
    # No trials -> no evidence -> p=1.0, never a ZeroDivisionError.
    assert binom.p_value(0, 0) == 1.0


def test_p_value_all_or_nothing_bounds():
    assert binom.p_value(0, 10) == 1.0          # X>=0 always true
    assert 0.0 < binom.p_value(10, 10) < 1.0
    # clamps out-of-range wins defensively
    assert binom.p_value(11, 10) == binom.p_value(10, 10)
    assert binom.p_value(-1, 10) == 1.0


def test_p_value_monotone_decreasing_in_wins():
    n = 12
    prev = 1.1
    for w in range(0, n + 1):
        p = binom.p_value(w, n)
        assert p <= prev + 1e-12   # non-increasing as wins climb
        prev = p


def test_wilson_ci_within_unit_interval():
    for w, n in [(0, 0), (0, 5), (3, 5), (5, 5), (6, 10), (50, 100)]:
        lo, hi = binom.wilson_ci95(w, n)
        assert 0.0 <= lo <= hi <= 1.0


def test_wilson_ci_zero_n_is_safe():
    assert binom.wilson_ci95(0, 0) == (0.0, 0.0)


def test_wilson_ci_monotone_in_wins():
    # more wins at fixed n -> both bounds shift up (or stay) — never down.
    n = 20
    prev_lo, prev_hi = -1.0, -1.0
    for w in range(0, n + 1):
        lo, hi = binom.wilson_ci95(w, n)
        assert lo >= prev_lo - 1e-12
        assert hi >= prev_hi - 1e-12
        prev_lo, prev_hi = lo, hi

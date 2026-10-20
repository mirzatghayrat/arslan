"""Tests for deliverable-verdict leveling signal (Task 7: staged orchestration)."""
from server.services import evolution_service as ev


def test_speed_weight_buckets():
    """Verify speed_weight bucketing: fast (<= 5s), normal (<= 60s), slow (> 60s)."""
    assert ev.speed_weight(2.0) == "fast"
    assert ev.speed_weight(5.0) == "fast"
    assert ev.speed_weight(20.0) == "normal"
    assert ev.speed_weight(60.0) == "normal"
    assert ev.speed_weight(300.0) == "slow"


def test_verdict_signal():
    """Verify accept/discard signals in quality_signal_for."""
    assert ev.quality_signal_for("accept") == 1
    assert ev.quality_signal_for("discard") == -1

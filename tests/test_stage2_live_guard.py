import json

import pytest

from evals.companion.live_guard import reserve


def test_reservations_are_durable_and_never_exceed_authorized_requests(tmp_path):
    path = tmp_path / "ledger"
    payload = {"max_tokens": 8192, "messages": []}
    for number in range(1, 37):
        assert reserve(path, payload) == number
    with pytest.raises(RuntimeError, match="budget"):
        reserve(path, payload)
    assert len(path.read_text().splitlines()) == 36


@pytest.mark.parametrize("payload", [{"max_tokens": 8193}, {"max_tokens": 8192, "text": "x" * 100_000}])
def test_payload_cap_before_reservation(tmp_path, payload):
    path = tmp_path / "ledger"
    with pytest.raises(RuntimeError, match="cap"):
        reserve(path, payload)
    assert not path.exists()


def test_corrupt_ledger_cannot_reset_spend(tmp_path):
    path = tmp_path / "ledger"
    path.write_text("not-json\n")
    with pytest.raises(json.JSONDecodeError):
        reserve(path, {"max_tokens": 8192})

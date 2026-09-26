import json
import pytest
from evals.companion import stable_budget as budget, stable_four_retest as four


def test_smaller_grant_is_not_a_36_call_ledger(tmp_path, monkeypatch):
    contract = {"authorization_id": "synthetic", "max_requests": 22, "max_usd": "3.00",
                "max_payload_bytes": 200000, "cases": [{"id": "fixture", "max_requests": 22}]}
    monkeypatch.setattr(budget, "contract", lambda: (contract, "fixture-hash"))
    monkeypatch.setattr(budget, "EVIDENCE", tmp_path)
    path = budget.initialize()
    assert json.loads(path.read_text())["max_requests"] == 22
    assert budget.status()["requests"] == 0
    with pytest.raises(FileExistsError):
        budget.initialize()
    with path.open("a") as stream:
        for number in range(1, 24):
            stream.write(json.dumps({"type": "reservation", "request": number, "case": "fixture", "reserved_usd": "0.10"}) + "\n")
    with pytest.raises(RuntimeError, match="over_budget"):
        budget.status()


@pytest.mark.parametrize("change", [{"max_requests": 37}, {"max_requests": 31, "max_usd": "3.00"},
                                    {"max_payload_bytes": 200001}])
def test_unbounded_or_underfunded_grant_refused(change):
    with pytest.raises(RuntimeError):
        budget.grant_limits(change)


def test_exact_four_case_allocation():
    assert four.CAPS == {"S2-R1": 8, "S2-R4": 7, "S2-D3": 4, "S2-M2": 3}
    assert sum(four.CAPS.values()) == 22

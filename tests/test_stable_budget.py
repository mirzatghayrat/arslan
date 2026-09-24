"""Offline tests only: never instantiate a provider or inspect real profiles."""
from datetime import datetime, timezone
import hashlib
import json

import pytest

from evals.companion import stable_budget as budget


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    # Unit accounting tests own a synthetic freeze. The historical live freeze
    # must keep its old hashes even after later registered input/checker repairs;
    # never rewrite that evidence just to run offline ledger tests.
    manifest = json.loads(budget.CONTRACT.read_bytes())
    frozen = tmp_path / "frozen-unit-input.txt"
    frozen.write_text("Synthetic immutable unit fixture")
    manifest["frozen_files"] = {frozen.name: hashlib.sha256(frozen.read_bytes()).hexdigest()}
    contract = tmp_path / "unit-contract.json"
    contract.write_text(json.dumps(manifest))
    monkeypatch.setattr(budget, "ROOT", tmp_path)
    monkeypatch.setattr(budget, "CONTRACT", contract)
    monkeypatch.setattr(budget, "EVIDENCE", tmp_path)
    monkeypatch.setenv("ARSLAN_STABLE_LIVE", "authorized-36-requests-usd5")
    path = budget.initialize()
    source = tmp_path / "synthetic.txt"
    source.write_text("Synthetic acceptance input, not real data")
    _, digest = budget.contract()
    preflights = {}
    for case in budget.contract()[0]["cases"]:
        value = {"case": case["id"], "contract_sha256": digest, "status": "ready",
                 "inputs": [{"path": source.name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]}
        if case["id"] == "S2-R2":
            value["public_same_scope_conflict_review"] = "Synthetic test marker only; not public evidence"
        target = tmp_path / f"{case['id']}-preflight.json"
        target.write_text(json.dumps(value))
        preflights[case["id"]] = hashlib.sha256(target.read_bytes()).hexdigest()
    return path, preflights


def pricing():
    return {"verified_on_utc": datetime.now(timezone.utc).date().isoformat(),
            "provider": "deepseek", "endpoint": "https://api.deepseek.com", "model": "fixture-model",
            "source": "https://api-docs.deepseek.com/quick_start/pricing/",
            "input_usd_per_million": "0.30", "output_usd_per_million": "1.20"}


def reserve(preflights, case="S2-R1", **kwargs):
    return budget.reserve(case, kwargs.pop("payload", {"model": "fixture-model", "max_tokens": 8192}),
                          pricing=kwargs.pop("prices", pricing()), preflight_sha256=preflights[case], **kwargs)


def test_contract_preserves_twelve_ids_and_original_inputs():
    # Historical manifest shape, not a claim its source hashes match HEAD.
    value = json.loads(budget.CONTRACT.read_bytes())
    assert [case["id"] for case in value["cases"]] == [f"S2-{group}{i}" for group in "RDM" for i in range(1, 5)]
    assert sum(case["max_requests"] for case in value["cases"]) == 36
    assert value["cases"][1]["status"] == "blocked_inputs"
    assert value["cases"][1]["input"] is None
    assert all(case["acceptance"] and case["preflight"] for case in value["cases"])


def test_frozen_source_mutation_still_refuses(isolated):
    path, _ = isolated
    (path.parent / "frozen-unit-input.txt").write_text("Changed")
    with pytest.raises(RuntimeError, match="stable_input_freeze_changed"):
        budget.contract()


def test_initialization_is_exclusive_and_zero_spend(isolated):
    path, _ = isolated
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        budget.initialize()
    assert path.read_bytes() == before
    assert budget.status()["requests"] == 0


def test_global_and_per_case_caps_retain_every_reservation(isolated):
    _, preflights = isolated
    number = 0
    for case in budget.contract()[0]["cases"]:
        for _ in range(case["max_requests"]):
            number += 1
            assert reserve(preflights, case["id"]) == number
        with pytest.raises(RuntimeError, match="budget_exhausted"):
            reserve(preflights, case["id"])
    assert budget.status()["requests"] == 36
    assert budget.status()["reserved_usd"] == "3.60"


@pytest.mark.parametrize("change", [
    {"verified_on_utc": "2000-01-01"}, {"model": "different"}, {"provider": "unknown"},
    {"input_usd_per_million": "NaN"}, {"input_usd_per_million": "-1"},
    {"output_usd_per_million": "0"}, {"output_usd_per_million": "100"},
])
def test_stale_unknown_or_unbounded_price_reserves_nothing(isolated, change):
    path, preflights = isolated
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="pric"):
        reserve(preflights, prices={**pricing(), **change})
    assert path.read_bytes() == before


def test_missing_ledger_does_not_reset_budget(isolated):
    path, preflights = isolated
    path.unlink()
    with pytest.raises(FileNotFoundError):
        reserve(preflights)
    assert not path.exists()


@pytest.mark.parametrize("row", ["not-json\n", '{"type":"reservation","request":2,"reserved_usd":"0.10","case":"S2-R1"}\n'])
def test_damaged_or_noncontiguous_ledger_fails_closed(isolated, row):
    path, preflights = isolated
    with path.open("a") as stream:
        stream.write(row)
    before = path.read_bytes()
    with pytest.raises((RuntimeError, json.JSONDecodeError)):
        reserve(preflights)
    assert path.read_bytes() == before


def test_halt_and_missing_opt_in_fail_before_spend(isolated, monkeypatch):
    path, preflights = isolated
    monkeypatch.delenv("ARSLAN_STABLE_LIVE")
    with pytest.raises(RuntimeError, match="authorization_missing"):
        reserve(preflights)
    monkeypatch.setenv("ARSLAN_STABLE_LIVE", "authorized-36-requests-usd5")
    (path.parent / "HALT").write_text("usage unknown")
    with pytest.raises(RuntimeError, match="halted"):
        reserve(preflights)
    assert budget.status()["requests"] == 0


@pytest.mark.parametrize("payload", [{"max_tokens": 8193, "model": "fixture-model"},
    {"max_tokens": 8192, "model": "fixture-model", "content": "x" * 100_000}])
def test_payload_caps(isolated, payload):
    _, preflights = isolated
    with pytest.raises(RuntimeError, match="payload_cap"):
        reserve(preflights, payload=payload)
    assert budget.status()["requests"] == 0


def test_input_mutation_and_missing_conflict_review_refuse(isolated):
    path, preflights = isolated
    target = path.parent / "S2-R2-preflight.json"
    ready = json.loads(target.read_text())
    ready.pop("public_same_scope_conflict_review")
    target.write_text(json.dumps(ready))
    preflights["S2-R2"] = hashlib.sha256(target.read_bytes()).hexdigest()
    with pytest.raises(RuntimeError, match="conflict_review_missing"):
        reserve(preflights, "S2-R2")
    (path.parent / "synthetic.txt").write_text("Changed after freeze")
    with pytest.raises(RuntimeError, match="input_changed"):
        reserve(preflights)
    assert budget.status()["requests"] == 0


def test_concurrent_reservations_cannot_exceed_case_budget(isolated):
    from concurrent.futures import ThreadPoolExecutor
    _, preflights = isolated

    def attempt(_):
        try:
            return reserve(preflights)
        except RuntimeError as error:
            assert str(error) == "stable_budget_exhausted"
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(12)))
    assert sorted(number for number in results if number is not None) == [1, 2, 3, 4, 5]
    assert budget.status()["requests"] == 5


@pytest.mark.parametrize("field,value", [("contract_sha256", "changed"), ("max_requests", 100), ("max_usd", "50.00")])
def test_changed_authorization_never_silently_resets(isolated, field, value):
    path, preflights = isolated
    header = json.loads(path.read_text())
    header[field] = value
    path.write_text(json.dumps(header) + "\n")
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="stable_"):
        reserve(preflights)
    assert path.read_bytes() == before

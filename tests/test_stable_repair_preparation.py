"""Offline inventory checks: no real ledger changes, credentials, or network."""
import json

import pytest

from evals.companion import stable_budget as budget, stable_repair_preparation as prep


@pytest.fixture
def prepared_inputs(tmp_path, monkeypatch):
    evidence = tmp_path / "original"
    evidence.mkdir()
    monkeypatch.setattr(budget, "EVIDENCE", evidence)
    budget.initialize()
    _, digest = budget.contract()
    source = evidence / "synthetic.txt"
    source.write_text("synthetic-only")
    for case in prep.PROPOSALS:
        (evidence / f"{case}-preflight.json").write_text(json.dumps({
            "case": case, "contract_sha256": digest,
            "inputs": [{"path": source.name, "sha256": prep.digest(source)}]}))
    return evidence


def test_inventory_copies_acceptance_without_authorization_or_ledger_writes(prepared_inputs, tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "reserve", lambda *a, **k: pytest.fail("no reservation permitted"))
    ledger = prepared_inputs / "budget.jsonl"
    before = ledger.read_bytes()
    output = tmp_path / "proposal/inventory.json"
    value = prep.save(output, "a" * 40)
    assert ledger.read_bytes() == before
    assert value["authorization"] is None and value["execution_enabled"] is False
    assert value["proposed_total_requests_not_authorized"] == 34
    assert len(value["cases"]) == 8 and all(not c["runner_ready"] for c in value["cases"])
    original = {c["id"]: c["acceptance"] for c in budget.contract()[0]["cases"]}
    assert all(c["unchanged_acceptance"] == original[c["case"]] for c in value["cases"])
    with pytest.raises(FileExistsError):
        prep.save(output, "a" * 40)


def test_no_writes_to_original_evidence(prepared_inputs):
    with pytest.raises(RuntimeError, match="cannot_write_original"):
        prep.save(prepared_inputs / "new-budget.jsonl", "a" * 40)
    assert not (prepared_inputs / "new-budget.jsonl").exists()


@pytest.mark.parametrize("change,error", [("bytes", "input_changed"), ("escape", "outside_evidence"),
                                         ("identity", "preflight_mismatch")])
def test_tampered_original_inputs_refused(prepared_inputs, change, error):
    path = prepared_inputs / "S2-D1-preflight.json"
    value = json.loads(path.read_text())
    if change == "bytes":
        (prepared_inputs / "synthetic.txt").write_text("changed")
    elif change == "escape":
        value["inputs"][0]["path"] = "../outside"
    else:
        value["case"] = "S2-D3"
    path.write_text(json.dumps(value))
    with pytest.raises(RuntimeError, match=error):
        prep.build("a" * 40)

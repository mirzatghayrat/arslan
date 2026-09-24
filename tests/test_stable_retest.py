"""Offline additional-ledger isolation; synthetic grants cannot enable real runs."""
import json
import os

import pytest

from evals.companion import stable_budget as budget, stable_retest as retest
from tests.test_stable_budget import pricing


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    old = tmp_path / "original"
    monkeypatch.setattr(budget, "EVIDENCE", old)
    budget.initialize()
    new = tmp_path / "additional"
    new.mkdir()
    monkeypatch.setattr(retest, "ORIGINAL", old)
    monkeypatch.setattr(retest, "EVIDENCE", new)
    monkeypatch.setenv("ARSLAN_STABLE_RETEST", retest.OPT_IN)
    (new / "authorization.json").write_text(json.dumps({"id": retest.GRANT_ID,
        "max_requests": 36, "max_usd": "5.00", "explicit_user_approval": True,
        "approved_at": "synthetic-test-only", "user_reply": "synthetic-test-only"}))
    retest.freeze_contract()
    return old, new


def test_new_ledger_retains_original_and_restores_bindings(isolated):
    old, new = isolated
    before = (old / "budget.jsonl").read_bytes()
    previous = os.environ.get("ARSLAN_STABLE_LIVE")
    with retest.bound():
        budget.initialize()
        assert budget.status()["authorization_id"] == retest.GRANT_ID
        data = new / "synthetic.txt"
        data.write_text("synthetic-only")
        ready = new / "S2-D1-preflight.json"
        ready.write_text(json.dumps({"case": "S2-D1", "status": "ready",
            "contract_sha256": budget.contract()[1],
            "inputs": [{"path": data.name, "sha256": retest.digest(data)}]}))
        payload = {"model": "fixture-model", "max_tokens": 8192}
        assert budget.reserve("S2-D1", payload, pricing=pricing(), preflight_sha256=retest.digest(ready)) == 1
        with pytest.raises(RuntimeError, match="budget_exhausted"):
            budget.reserve("S2-D1", payload, pricing=pricing(), preflight_sha256=retest.digest(ready))
    assert budget.EVIDENCE == old and os.environ.get("ARSLAN_STABLE_LIVE") == previous
    assert (old / "budget.jsonl").read_bytes() == before
    with retest.bound():
        assert budget.status()["requests"] == 1
        with pytest.raises(FileExistsError):
            budget.initialize()


def test_old_opt_in_cannot_authorize_new_grant(isolated, monkeypatch):
    monkeypatch.delenv("ARSLAN_STABLE_RETEST")
    monkeypatch.setenv("ARSLAN_STABLE_LIVE", "authorized-36-requests-usd5")
    with pytest.raises(RuntimeError, match="additional_authorization_missing"):
        with retest.bound():
            pytest.fail("must not bind")


@pytest.mark.parametrize("mutation", ["parent", "grant", "source", "caps"])
def test_changed_identity_fails_and_restores_globals(isolated, monkeypatch, mutation):
    old, new = isolated
    if mutation == "parent":
        with (old / "budget.jsonl").open("a") as stream:
            stream.write("changed\n")
    elif mutation == "grant":
        with (new / "authorization.json").open("a") as stream:
            stream.write(" ")
    elif mutation == "source":
        monkeypatch.setattr(retest, "source_sha", lambda: "different")
    else:
        path = new / "contract.json"
        value = json.loads(path.read_bytes())
        value["cases"][0]["max_requests"] += 1
        path.write_text(json.dumps(value))
    with pytest.raises(RuntimeError, match="retest_"):
        with retest.bound():
            pytest.fail("must not bind")
    assert budget.EVIDENCE == old
    assert not (new / "budget.jsonl").exists()

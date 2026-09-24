"""Disposable offline contracts; never refresh historical paid-run manifests."""
import hashlib
import json
from evals.companion import stable_budget as budget


def current_unit_contract(tmp_path, monkeypatch):
    value = json.loads(budget.CONTRACT.read_bytes())
    value["frozen_files"] = {path: hashlib.sha256((budget.ROOT / path).read_bytes()).hexdigest()
                             for path in value["frozen_files"]}
    target = tmp_path / "offline-current-source-contract.json"
    target.write_text(json.dumps(value))
    monkeypatch.setattr(budget, "CONTRACT", target)
    return target

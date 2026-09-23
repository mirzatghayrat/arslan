"""Immutable synthetic inputs for the stable project/confirmation memory cases."""
import hashlib
import json

from evals.companion import stable_budget as budget
from evals.companion.stable_live import persist

CASES = {
    "S2-M1": {"projects": [{"id": "project-a", "name": "Notes"}, {"id": "project-b", "name": "Notes"}],
        "entry": "Project Notes uses orange release diagrams.",
        "turns": [{"conversation": "S2-M1-A", "project": "project-a",
                   "prompt": "For Project Notes, what confirmed diagram color should this report use? If no preference is available, say unknown; do not invent one."},
                  {"conversation": "S2-M1-B", "project": "project-b",
                   "prompt": "For Project Notes, what confirmed diagram color should this report use? If no preference is available, say unknown; do not invent one."}]},
    "S2-M2": {"entry": "Use blue report headings.", "correction": "Use green report headings.",
        "turns": [{"conversation": "S2-M2-before", "project": None,
                   "prompt": "What confirmed report heading color do I prefer? State unknown if I have not confirmed one."},
                  {"conversation": "S2-M2-after", "project": None,
                   "prompt": "Prepare a one-line report style brief using my confirmed heading preference."}]},
}
RUNNER = "tests/server/test_stable_memory_live.py"


def freeze(case_id):
    raw = json.dumps(CASES[case_id], ensure_ascii=False, indent=2).encode()
    name = f"{case_id}-synthetic-memory.json"
    with (budget.EVIDENCE / name).open("xb") as stream:
        stream.write(raw)
    persist(budget.EVIDENCE / f"{case_id}-preflight.json", {
        "case": case_id, "contract_sha256": budget.contract()[1], "status": "ready",
        "inputs": [{"path": name, "sha256": hashlib.sha256(raw).hexdigest()}],
        "runner_sha256": hashlib.sha256((budget.ROOT / RUNNER).read_bytes()).hexdigest(),
        "acceptance": next(case["acceptance"] for case in budget.contract()[0]["cases"] if case["id"] == case_id),
        "quality_status": "not_run", "native_status": "not_run"})


def verified(case_id):
    raw = (budget.EVIDENCE / f"{case_id}-preflight.json").read_bytes()
    ready = json.loads(raw)
    inputs = json.loads((budget.EVIDENCE / f"{case_id}-synthetic-memory.json").read_bytes())
    if (inputs != CASES[case_id] or ready["contract_sha256"] != budget.contract()[1]
            or ready["runner_sha256"] != hashlib.sha256((budget.ROOT / RUNNER).read_bytes()).hexdigest()):
        raise RuntimeError("stable_memory_preflight_changed")
    return inputs, hashlib.sha256(raw).hexdigest()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=CASES)
    args = parser.parse_args()
    freeze(args.case)
    print(json.dumps({"case": args.case, "preflight": "ready", "model_calls": 0}))

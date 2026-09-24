"""Offline additive-retest inventory. This module cannot authorize or run calls.

Keeps the original ledger/preflights untouched. A prepared inventory is NOT a
new contract, a ready runner, current pricing, or evidence of answer quality.
"""
import hashlib
import json
from pathlib import Path
import subprocess

from evals.companion import stable_budget as budget

PROPOSALS = {
    "S2-D1": (1, "tests/server/test_stable_document_live.py",
              "Replace legacy ingest._extract_file input with actual POST /api/v1/extract response; freeze changed prompt and page inventory before calls"),
    "S2-D3": (4, "tests/server/test_stable_document_live.py",
              "Preserve production file-tool schemas/descriptions and narrow write/read approval; reopen actual CSV and review missing-value claims"),
    "S2-M2": (3, "tests/server/test_stable_memory_live.py",
              "Fresh proposed/confirmed memory states; keep unknown-before-confirmation and source-only brief checks; no inherited conversation"),
    "S2-R1": (6, "tests/server/test_stable_research_live.py",
              "Actual full pinned source reads, native call correction under unchanged permissions, artifact write/read and claim-by-claim source review"),
    "S2-R2": (4, "tests/server/test_stable_research_live.py",
              "Preserve selected public claims and dates; explicitly label abstract-only scope, do not invent uncertainty convention/methodology"),
    "S2-R3": (4, "tests/server/test_stable_research_live.py",
              "Use repaired plain-text README reader; separate commit/release dates and leave untested compatibility unknown"),
    "S2-R4": (5, "tests/server/test_stable_research_live.py",
              "Actual bilingual same-commit source reads; only hash-matched successful refetch allowed; review absence/locality/conflict claims"),
    "S2-M4": (7, "evals/companion/stable_recovery.py",
              "Fresh isolated crash/resume pair with one cumulative task budget; no paid auto-resume or repeated write; review final answer"),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def retained_input(item):
    relative = Path(item["path"])
    path = (budget.EVIDENCE / relative).resolve()
    if (relative.is_absolute() or ".." in relative.parts
            or not path.is_relative_to(budget.EVIDENCE.resolve())):
        raise RuntimeError("repair_input_outside_evidence")
    if digest(path) != item["sha256"]:
        raise RuntimeError("repair_input_changed")
    return {"path": relative.as_posix(), "sha256": item["sha256"], "bytes": path.stat().st_size}


def build(source_sha):
    contract, contract_hash = budget.contract()
    ledger = budget.EVIDENCE / "budget.jsonl"
    ledger_hash = digest(ledger)
    status = budget.status()
    if digest(ledger) != ledger_hash:
        raise RuntimeError("repair_ledger_changed_during_snapshot")
    cases = []
    for case_id, (cap, runner, change) in PROPOSALS.items():
        original = next(c for c in contract["cases"] if c["id"] == case_id)
        preflight = budget.EVIDENCE / f"{case_id}-preflight.json"
        ready = json.loads(preflight.read_bytes())
        if ready.get("case") != case_id or ready.get("contract_sha256") != contract_hash:
            raise RuntimeError("repair_original_preflight_mismatch")
        cases.append({"case": case_id, "proposed_max_requests_not_authorized": cap,
                      "original_calls_used": status["by_case"][case_id],
                      "original_preflight_sha256": digest(preflight),
                      "retained_inputs": [retained_input(item) for item in ready["inputs"]],
                      "unchanged_acceptance": original["acceptance"],
                      "existing_runner": runner, "existing_runner_sha256": digest(budget.ROOT / runner),
                      "required_change_or_review": change, "runner_ready": False,
                      "quality_status": "not_run", "native_status": "separate_gate"})
    if digest(ledger) != ledger_hash:
        raise RuntimeError("repair_ledger_changed_during_snapshot")
    return {"kind": "planning_only_not_executable", "source_sha": source_sha,
            "authorization": None, "execution_enabled": False,
            "original_contract_sha256": contract_hash, "original_ledger_sha256": ledger_hash,
            "original_budget": status, "cases": cases,
            "proposed_total_requests_not_authorized": sum(c[0] for c in PROPOSALS.values()),
            "before_execution": ["Explicit independent additional user authorization",
                                 "Separate linked ledger; preserve old reservations, no resets",
                                 "Reviewed additive runners with no automatic retries",
                                 "Freeze candidate, new prompts, runner and checker hashes",
                                 "Same-day verified pricing and durable per-call reservation"],
            "not_claimed": ["new budget granted", "all runners ready", "model quality passed",
                            "original failed cases replaced", "native or signed-package acceptance"]}


def save(output, source_sha):
    output = Path(output).absolute()
    # Never write under the old evidence tree, even when explicitly passed.
    if output.resolve().is_relative_to(budget.EVIDENCE.resolve()):
        raise RuntimeError("repair_cannot_write_original_evidence")
    result = build(source_sha)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=budget.ROOT, text=True).strip()
    save(args.output, sha)
    print(json.dumps({"status": "planning_only_not_executable", "cases": 8,
                      "model_calls": 0, "sha256": digest(args.output)}))

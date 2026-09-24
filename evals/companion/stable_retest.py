"""Bind existing acceptance runners to one explicitly additional grant.

No initialization, credentials or calls occur on import. The original ledger
is linked by hash and never reopened for writing. Production paths are fixed.
"""
from contextlib import contextmanager
import hashlib
import json
import os
import subprocess

from evals.companion import stable_budget as budget
from evals.companion.stable_live import persist
from evals.companion.stable_repair_preparation import PROPOSALS

ORIGINAL = budget.EVIDENCE
ORIGINAL_CONTRACT = budget.CONTRACT
EVIDENCE = budget.ROOT.parent / "stable-0140-retest-evidence-20260924"
GRANT_ID = "arslan-stable-0140-repair-primary-20260924"
OPT_IN = "authorized-additional-36-requests-usd5"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_sha():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=budget.ROOT, text=True).strip()


def require_grant():
    if os.environ.get("ARSLAN_STABLE_RETEST") != OPT_IN:
        raise RuntimeError("retest_additional_authorization_missing")
    value = json.loads((EVIDENCE / "authorization.json").read_bytes())
    if (value.get("id") != GRANT_ID or value.get("max_requests") != 36
            or value.get("max_usd") != "5.00" or value.get("explicit_user_approval") is not True
            or not value.get("approved_at") or not value.get("user_reply")):
        raise RuntimeError("retest_additional_authorization_invalid")
    return value


def freeze_contract():
    """Requires an independently recorded user grant; does not create a ledger."""
    require_grant()
    if EVIDENCE.resolve() == ORIGINAL.resolve() or EVIDENCE.resolve().is_relative_to(ORIGINAL.resolve()):
        raise RuntimeError("retest_original_evidence_overlap")
    original = json.loads(ORIGINAL_CONTRACT.read_bytes())
    value = {**original, "revision": 2, "authorization_id": GRANT_ID,
             "source_baseline": source_sha(), "parent_contract_sha256": digest(ORIGINAL_CONTRACT),
             "parent_ledger_sha256": digest(ORIGINAL / "budget.jsonl"),
             "grant_sha256": digest(EVIDENCE / "authorization.json"),
             "cases": [{**case, "max_requests": PROPOSALS[case["id"]][0],
                         "status": "requires_additive_preflight"}
                        for case in original["cases"] if case["id"] in PROPOSALS]}
    value["frozen_files"] = {**original["frozen_files"]}
    for path in ("evals/companion/stable_retest.py", "evals/companion/stable_budget.py",
                 "evals/companion/stable_live.py", "evals/companion/stable_primary.py",
                 "evals/companion/stable_pdf_repair.py", "evals/companion/stable_documents.py",
                 "evals/companion/stable_repair_preparation.py",
                 "evals/companion/stable_research.py", "evals/companion/stable_memory.py",
                 "evals/companion/stable_recovery.py", "tests/server/test_stable_document_live.py",
                 "tests/server/test_stable_memory_live.py", "tests/server/test_stable_research_live.py",
                 "tests/server/test_stable_retest_live.py"):
        value["frozen_files"][path] = digest(budget.ROOT / path)
    persist(EVIDENCE / "contract.json", value)
    return value


def freeze_inputs(pdf_response):
    """Copy original sources; only D1 context changes to real upload output."""
    from evals.companion import stable_documents as documents, stable_research as research
    from evals.companion.stable_repair_preparation import retained_input

    originals = {}
    for case in PROPOSALS:
        path = ORIGINAL / f"{case}-preflight.json"
        ready = json.loads(path.read_bytes())
        for item in ready["inputs"]:
            retained_input(item)
            target = EVIDENCE / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            data = (ORIGINAL / item["path"]).read_bytes()
            if target.exists():
                if target.read_bytes() != data:
                    raise RuntimeError("retest_copied_input_changed")
            else:
                with target.open("xb") as stream:
                    stream.write(data)
        originals[case] = ready, digest(path)
    with bound():
        _, contract_hash = budget.contract()
        for case, (ready, original_hash) in originals.items():
            ready.update({"contract_sha256": contract_hash,
                          "original_preflight_sha256": original_hash,
                          "runner_sha256": digest(budget.ROOT / PROPOSALS[case][1])})
            if case == "S2-D1":
                ready["extracted"] = pdf_response["text"]
                ready["prompt"] = documents.prompt(case, ready["extracted"])
                ready["attachment_api_response"] = pdf_response
            persist(EVIDENCE / f"{case}-preflight.json", ready)
        for case in research.CASES:
            persist(EVIDENCE / f"{case}-runner-plan-v1.json", research.plan(case))


@contextmanager
def bound():
    """Reuse locks, caps, HALT, reservations and accounting under the new grant."""
    require_grant()
    contract_path = EVIDENCE / "contract.json"
    original_contract_fn = budget.contract
    previous_evidence, previous_contract = budget.EVIDENCE, budget.CONTRACT
    previous_opt = os.environ.get("ARSLAN_STABLE_LIVE")
    from evals.companion import stable_research as research
    original_research_plan = research.plan

    def additional_plan(case):
        value = original_research_plan(case)
        value["limits"] = (f"Independent {GRANT_ID}: {case} cap {PROPOSALS[case][0]}; "
                           "36/$5 additional grant; original ledger retained; no automatic retry")
        return value

    def checked_contract():
        value, hashed = original_contract_fn()
        if (value.get("authorization_id") != GRANT_ID
                or value.get("grant_sha256") != digest(EVIDENCE / "authorization.json")
                or value.get("parent_contract_sha256") != digest(ORIGINAL_CONTRACT)
                or value.get("parent_ledger_sha256") != digest(ORIGINAL / "budget.jsonl")
                or value.get("source_baseline") != source_sha()):
            raise RuntimeError("retest_frozen_identity_changed")
        if {c["id"]: c["max_requests"] for c in value["cases"]} != {k: v[0] for k, v in PROPOSALS.items()}:
            raise RuntimeError("retest_case_caps_changed")
        require_grant()
        return value, hashed

    if EVIDENCE.resolve() == ORIGINAL.resolve() or EVIDENCE.resolve().is_relative_to(ORIGINAL.resolve()):
        raise RuntimeError("retest_original_evidence_overlap")
    try:
        budget.EVIDENCE, budget.CONTRACT, budget.contract = EVIDENCE, contract_path, checked_contract
        research.plan = additional_plan
        checked_contract()
        os.environ["ARSLAN_STABLE_LIVE"] = "authorized-36-requests-usd5"
        yield
    finally:
        budget.EVIDENCE, budget.CONTRACT, budget.contract = previous_evidence, previous_contract, original_contract_fn
        research.plan = original_research_plan
        if previous_opt is None:
            os.environ.pop("ARSLAN_STABLE_LIVE", None)
        else:
            os.environ["ARSLAN_STABLE_LIVE"] = previous_opt


if __name__ == "__main__":
    # Forward only the existing process-recovery CLI under the verified new
    # grant. Each phase is still a separate process; no automatic resume.
    import runpy
    import sys
    if len(sys.argv) < 2 or sys.argv[1] not in {"crash", "resume"}:
        raise SystemExit("Use crash or resume with the existing recovery arguments")
    with bound():
        runpy.run_module("evals.companion.stable_recovery", run_name="__main__")

"""Explicit 22/$3 four-case grant; prior evidence is read-only and hash-linked."""
from contextlib import contextmanager
import json
import os

from evals.companion import stable_budget as budget, stable_documents as documents, stable_research as research
from evals.companion.stable_live import persist
from evals.companion.stable_retest import digest, source_sha

PARENT = budget.ROOT.parent / "stable-0140-retest-evidence-20260924"
EVIDENCE = budget.ROOT.parent / "stable-0140-four-retest-evidence-20260924"
GRANT_ID = "arslan-stable-four-22-usd3-20260924"
OPT_IN = "authorized-four-22-requests-usd3"
ENV = "ARSLAN_STABLE_FOUR"
REQUESTS, USD = 22, "3.00"
EXTRA_FILES = set()
MAX_REVIEW_OUTPUT_TOKENS = 8192
CAPS = {"S2-R1": 8, "S2-R4": 7, "S2-D3": 4, "S2-M2": 3}
RUNNERS = {case: "tests/server/test_stable_" + (
    "research" if case.startswith("S2-R") else "document" if case == "S2-D3" else "memory") + "_live.py"
    for case in CAPS}


def grant():
    value = json.loads((EVIDENCE / "authorization.json").read_bytes())
    if (os.environ.get(ENV) != OPT_IN or value.get("id") != GRANT_ID
            or value.get("max_requests") != REQUESTS or value.get("max_usd") != USD
            or value.get("explicit_user_approval") is not True or not value.get("user_reply")):
        raise RuntimeError("four_explicit_authorization_required")
    return value


@contextmanager
def bound():
    grant()
    old = budget.EVIDENCE, budget.CONTRACT, budget.contract, research.plan
    previous = os.environ.get("ARSLAN_STABLE_LIVE")

    def checked():
        value, hashed = old[2]()
        if (value["authorization_id"] != GRANT_ID or value["source_baseline"] != source_sha()
                or value["parent_ledger_sha256"] != digest(PARENT / "budget.jsonl")
                or value["parent_contract_sha256"] != digest(PARENT / "contract.json")
                or value["grant_sha256"] != digest(EVIDENCE / "authorization.json")
                or budget.grant_limits(value) != (REQUESTS, USD, 200_000)
                or {c["id"]: c["max_requests"] for c in value["cases"]} != CAPS):
            raise RuntimeError("four_frozen_identity_changed")
        grant()
        return value, hashed

    def plan(case):
        value = old[3](case)
        value["limits"] = f"Independent {GRANT_ID}; case cap {CAPS[case]}; total {REQUESTS}/${USD}; no automatic retry"
        return value

    try:
        budget.EVIDENCE, budget.CONTRACT, budget.contract = EVIDENCE, EVIDENCE / "contract.json", checked
        research.plan = plan
        checked()
        os.environ["ARSLAN_STABLE_LIVE"] = "authorized-36-requests-usd5"
        yield
    finally:
        budget.EVIDENCE, budget.CONTRACT, budget.contract, research.plan = old
        if previous is None:
            os.environ.pop("ARSLAN_STABLE_LIVE", None)
        else:
            os.environ["ARSLAN_STABLE_LIVE"] = previous


def freeze():
    grant()
    parent = json.loads((PARENT / "contract.json").read_bytes())
    files = set(parent["frozen_files"]) | set(RUNNERS.values()) | EXTRA_FILES | {
        "evals/companion/stable_four_retest.py", "tests/server/test_stable_four_live.py",
        "tests/test_stable_four_grant.py", "server/services/input_formats.py",
        "server/orchestrator/arslan.py", "server/orchestrator/tool_loop.py"}
    value = {**parent, "revision": 3, "authorization_id": GRANT_ID,
             "max_requests": REQUESTS, "max_usd": USD, "max_payload_bytes": 200_000,
             "max_review_output_tokens": MAX_REVIEW_OUTPUT_TOKENS,
             "source_baseline": source_sha(), "parent_contract_sha256": digest(PARENT / "contract.json"),
             "parent_ledger_sha256": digest(PARENT / "budget.jsonl"),
             "grant_sha256": digest(EVIDENCE / "authorization.json"),
             "frozen_files": {path: digest(budget.ROOT / path) for path in files},
             "cases": [{**case, "max_requests": CAPS[case["id"]]} for case in parent["cases"] if case["id"] in CAPS]}
    persist(EVIDENCE / "contract.json", value)
    with bound():
        for case in CAPS:
            ready = json.loads((PARENT / f"{case}-preflight.json").read_bytes())
            for item in ready["inputs"]:
                source = PARENT / item["path"]
                if not source.resolve().is_relative_to(PARENT.resolve()) or digest(source) != item["sha256"]:
                    raise RuntimeError("four_parent_input_changed")
                target = EVIDENCE / item["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    if target.is_symlink() or digest(target) != item["sha256"]:
                        raise RuntimeError("four_shared_input_changed")
                else:
                    with target.open("xb") as stream:
                        stream.write(source.read_bytes())
            ready.update(contract_sha256=budget.contract()[1], runner_sha256=digest(budget.ROOT / RUNNERS[case]),
                         previous_preflight_sha256=digest(PARENT / f"{case}-preflight.json"))
            if case == "S2-D3":
                ready["extracted"] = documents.read_inputs(case, documents.inputs(case))
                ready["prompt"] = documents.prompt(case, ready["extracted"])
                ready["representation_change"] = "Same CSV bytes, logical-record locators; no oracle supplied"
            persist(EVIDENCE / f"{case}-preflight.json", ready)
        for case in ("S2-R1", "S2-R4"):
            persist(EVIDENCE / f"{case}-runner-plan-v1.json", research.plan(case))
        budget.initialize()
        return budget.status()


if __name__ == "__main__":
    import sys
    if sys.argv[1:] != ["freeze"]:
        raise SystemExit("freeze only; no calls from this CLI")
    print(json.dumps(freeze()))

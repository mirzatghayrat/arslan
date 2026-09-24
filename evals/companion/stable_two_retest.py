"""New explicit two-case grant, preserving all prior attempt ledgers."""
from contextlib import contextmanager
import json

from evals.companion import stable_four_retest as four

OPT_IN = "authorized-two-12-requests-usd120"


@contextmanager
def configured():
    values = {
        "PARENT": four.budget.ROOT.parent / "stable-0140-four-retest-evidence-20260924",
        "EVIDENCE": four.budget.ROOT.parent / "stable-0140-two-retest-evidence-20260924",
        "GRANT_ID": "arslan-stable-two-12-usd120-20260924",
        "ENV": "ARSLAN_STABLE_TWO", "OPT_IN": OPT_IN,
        "REQUESTS": 12, "USD": "1.20", "CAPS": {"S2-R1": 6, "S2-R4": 6},
        "EXTRA_FILES": {"evals/companion/stable_two_retest.py",
                        "tests/server/test_stable_two_live.py", "tests/test_stable_two_grant.py",
                        "server/orchestrator/answer_contract.py"},
    }
    old = {key: getattr(four, key) for key in values}
    try:
        for key, value in values.items():
            setattr(four, key, value)
        yield
    finally:
        for key, value in old.items():
            setattr(four, key, value)


@contextmanager
def bound():
    with configured(), four.bound():
        yield


if __name__ == "__main__":
    import sys
    if sys.argv[1:] != ["freeze"]:
        raise SystemExit("freeze only")
    with configured():
        print(json.dumps(four.freeze()))

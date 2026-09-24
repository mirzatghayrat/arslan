"""One 60/$6 cumulative grant across separately frozen repair rounds."""
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import json
import os

from evals.companion import stable_budget as budget, stable_four_retest as four
from evals.companion.stable_live import persist
from evals.companion.stable_retest import digest

MASTER = budget.ROOT.parent / "stable-0140-release-evidence-20260924"
OPT_IN = "authorized-release-60-requests-usd6"


def authority():
    value = json.loads((MASTER / "authorization.json").read_bytes())
    if (os.environ.get("ARSLAN_STABLE_RELEASE") != OPT_IN or value.get("max_requests") != 60
            or value.get("max_usd") != "6.00" or value.get("explicit_user_approval") is not True):
        raise RuntimeError("release_authorization_required")
    return digest(MASTER / "authorization.json")


def initialize():
    hashed = authority()
    with (MASTER / "budget.jsonl").open("x") as stream:
        stream.write(json.dumps({"type": "authorization", "sha256": hashed, "requests": 60, "usd": "6.00"}) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def reserve_global(round_number, local_number, case):
    hashed = authority()
    with (MASTER / "budget.jsonl").open("r+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        rows = [json.loads(line) for line in stream]
        if not rows or rows[0] != {"type": "authorization", "sha256": hashed, "requests": 60, "usd": "6.00"}:
            raise RuntimeError("release_ledger_identity")
        if len(rows) > 60:
            raise RuntimeError("release_budget_exhausted")
        for index, row in enumerate(rows[1:], 1):
            if (row.get("request") != index or row.get("reserved_usd") != "0.10"
                    or type(row.get("round")) is not int or not 1 <= row["round"] <= 9
                    or type(row.get("local_request")) is not int or not 1 <= row["local_request"] <= 24):
                raise RuntimeError("release_ledger_invalid")
            accounted = MASTER / f"round-{row['round']}" / f"request-{row['local_request']:02d}.accounted.json"
            if not accounted.is_file():
                raise RuntimeError("release_prior_request_unaccounted")
            value = json.loads(accounted.read_bytes())
            estimate = Decimal(value.get("peak_rate_estimate_usd", "NaN"))
            if (value.get("request") != row["local_request"] or value.get("reserved_usd") != "0.10"
                    or value.get("reservation_refunded") is not False or not estimate.is_finite()
                    or not Decimal(0) <= estimate <= Decimal("0.10")):
                raise RuntimeError("release_prior_accounting_invalid")
        stream.write(json.dumps({"type": "reservation", "request": len(rows), "round": round_number,
            "local_request": local_number, "case": case, "reserved_usd": "0.10",
            "round_contract_sha256": digest(budget.CONTRACT),
            "created_at": datetime.now(timezone.utc).isoformat()}) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def configured():
    authority()
    number = int(os.environ["ARSLAN_RELEASE_ROUND"])
    if not 1 <= number <= 9:
        raise RuntimeError("invalid_round")
    values = {"PARENT": budget.ROOT.parent / "stable-0140-two-retest-evidence-20260924",
        "EVIDENCE": MASTER / f"round-{number}", "GRANT_ID": f"release-60-usd6-round-{number}",
        "ENV": "ARSLAN_STABLE_RELEASE", "OPT_IN": OPT_IN, "REQUESTS": 24, "USD": "3.00",
        "CAPS": {"S2-R1": 12, "S2-R4": 12},
        "EXTRA_FILES": {"evals/companion/stable_release_retest.py", "tests/server/test_stable_release_live.py",
                        "tests/test_stable_release_grant.py", "server/orchestrator/research_review.py"}}
    old = {key: getattr(four, key) for key in values}
    try:
        for key, value in values.items():
            setattr(four, key, value)
        yield number
    finally:
        for key, value in old.items():
            setattr(four, key, value)


@contextmanager
def bound():
    with configured() as number, four.bound():
        original = budget.reserve

        def reserve(*args, **kwargs):
            local = original(*args, **kwargs)
            reserve_global(number, local, args[0])
            return local
        budget.reserve = reserve
        try:
            yield
        finally:
            budget.reserve = original


def freeze():
    with configured():
        four.EVIDENCE.mkdir(exist_ok=False)
        persist(four.EVIDENCE / "authorization.json", {"id": four.GRANT_ID,
            "max_requests": 24, "max_usd": "3.00", "explicit_user_approval": True,
            "user_reply": "批准：最多 60 次／US$6", "parent_authorization_sha256": authority(),
            "scope": "Registered two-case repair round; all requests also reserve against shared 60/$6 ledger"})
        return four.freeze()


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["initialize"]:
        initialize()
    elif sys.argv[1:] == ["freeze"]:
        print(json.dumps(freeze()))
    else:
        raise SystemExit("initialize or freeze only")

"""One 60/$6 cumulative grant across separately frozen repair rounds."""
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import hashlib
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


def abandoned_bound(row):
    """A stopped round can retain a whole slot without inventing response usage.

    Only a separately recorded cancellation disposition is accepted. Validate
    the original pre-POST payload/rates; charge the FULL reservation forever.
    This does not remove HALT, resume that round, or retry the interrupted call.
    """
    directory = MASTER / f"round-{row['round']}"
    prefix = directory / f"request-{row['local_request']:02d}"
    receipt = json.loads(prefix.with_suffix(".abandoned.json").read_bytes())
    reason = json.loads((directory / "HALT").read_bytes()).get("reason")
    status = {"CancelledError": "cancelled_usage_unknown", "BudgetExceeded": "budget_stop_usage_unknown"}.get(reason)
    expected = {"request": row["local_request"], "status": status,
                "charged_budget_usd": "0.10", "reservation_refunded": False,
                "automatic_retry": False, "invoice": False,
                "input_sha256": digest(prefix.with_suffix(".input.json"))}
    if status is None or receipt != expected:
        raise RuntimeError("release_abandonment_invalid")
    if prefix.with_suffix(".response.json").exists() or prefix.with_suffix(".accounted.json").exists():
        raise RuntimeError("release_abandonment_has_response")
    rows = [json.loads(line) for line in (directory / "budget.jsonl").read_text().splitlines()]
    reservation = rows[row["local_request"]]
    original = json.loads(prefix.with_suffix(".input.json").read_bytes())
    payload = json.dumps(original["payload"], ensure_ascii=False).encode()
    price = reservation["pricing"]
    if (reservation["request"] != row["local_request"] or reservation["case"] != row["case"]
            or reservation["reserved_usd"] != "0.10" or len(payload) > 200_000
            or hashlib.sha256(payload).hexdigest() != reservation["payload_sha256"]
            or original["payload"].get("max_tokens") != 8192
            or original["payload"].get("model") != "deepseek-v4-flash"
            or price.get("endpoint") != "https://api.deepseek.com"
            or price.get("input_usd_per_million") != "0.30"
            or price.get("output_usd_per_million") != "1.20"):
        raise RuntimeError("release_abandonment_bound_unverified")
    # Same conservative ceiling admitted before POST, not a fabricated invoice:
    # 200k input + 8192 output at the frozen peak rates < the retained $0.10.
    return Decimal("0.10")


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
                    or type(row.get("round")) is not int or not 1 <= row["round"] <= 10
                    or type(row.get("local_request")) is not int or not 1 <= row["local_request"] <= 24):
                raise RuntimeError("release_ledger_invalid")
            accounted = MASTER / f"round-{row['round']}" / f"request-{row['local_request']:02d}.accounted.json"
            if not accounted.is_file():
                try:
                    abandoned_bound(row)
                except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
                    raise RuntimeError("release_prior_request_unaccounted") from error
                continue
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
    if not 1 <= number <= 10:
        raise RuntimeError("invalid_round")
    values = {"PARENT": budget.ROOT.parent / "stable-0140-two-retest-evidence-20260924",
        "EVIDENCE": MASTER / f"round-{number}", "GRANT_ID": f"release-60-usd6-round-{number}",
        "ENV": "ARSLAN_STABLE_RELEASE", "OPT_IN": OPT_IN, "REQUESTS": 24, "USD": "3.00",
        "CAPS": {"S2-R1": 12, "S2-R4": 12},
        "EXTRA_FILES": {"evals/companion/stable_release_retest.py", "tests/server/test_stable_release_live.py",
                        "tests/test_stable_release_grant.py", "server/orchestrator/research_review.py",
                        "arslan/llm/request_policy.py", "arslan/llm/providers/openai_provider.py",
                        "evals/companion/stable_live.py", "tests/test_stable_live.py"}}
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
            execution_admitted()
            local = original(*args, **kwargs)
            reserve_global(number, local, args[0])
            return local
        budget.reserve = reserve
        try:
            yield
        finally:
            budget.reserve = original


def execution_admitted():
    """Check task admission before reserving; never widen the product ceiling."""
    from arslan.execution_budget import current
    execution = current()
    if execution is not None:
        execution.check()
        if execution.model_requests >= execution.limits.model_requests:
            execution.stop("model_requests")
        if execution.tokens >= execution.limits.tokens:
            execution.stop("tokens")


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

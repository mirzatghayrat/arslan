"""Offline budget bookkeeping for the independently authorized stable pilot.

No provider, credentials or network imports. A future runner must use this one
canonical ledger, verify current pricing, then reserve before every HTTP call.
This module alone does not enable the historical stage-2 live test runner.
"""
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT.parent / "stable-0140-live-evidence-20260924"
CONTRACT = ROOT / "evals/companion/stable-0140-acceptance.json"


def contract():
    raw = CONTRACT.read_bytes()
    value = json.loads(raw)
    for relative, digest in value["frozen_files"].items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != digest:
            raise RuntimeError("stable_input_freeze_changed")
    return value, hashlib.sha256(raw).hexdigest()


def initialize():
    """Exclusive creation; never truncate or silently create a second ledger."""
    value, digest = contract()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE / "budget.jsonl"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps({"type": "authorization", "id": value["authorization_id"],
            "contract_sha256": digest, "max_requests": 36, "max_usd": "5.00",
            "created_at": datetime.now(timezone.utc).isoformat()}) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return path


def _records(stream, value, digest):
    stream.seek(0)
    rows = [json.loads(line) for line in stream]
    if not rows or rows[0].get("type") != "authorization" or rows[0].get("id") != value["authorization_id"]:
        raise RuntimeError("stable_authorization_invalid")
    if rows[0].get("contract_sha256") != digest:
        raise RuntimeError("stable_contract_changed")
    if rows[0].get("max_requests") != 36 or rows[0].get("max_usd") != "5.00":
        raise RuntimeError("stable_authorization_invalid")
    limits = {case["id"]: case["max_requests"] for case in value["cases"]}
    counts = dict.fromkeys(limits, 0)
    for number, row in enumerate(rows[1:], 1):
        if (row.get("type") != "reservation" or type(row.get("request")) is not int
                or row["request"] != number or row.get("reserved_usd") != "0.10"
                or row.get("case") not in limits):
            raise RuntimeError("stable_ledger_invalid")
        counts[row["case"]] += 1
    if len(rows) - 1 > 36 or any(counts[key] > limits[key] for key in counts):
        raise RuntimeError("stable_ledger_over_budget")
    return rows, counts, limits


def status():
    value, digest = contract()
    with (EVIDENCE / "budget.jsonl").open("r", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_SH)
        rows, counts, _ = _records(stream, value, digest)
    return {"authorization_id": value["authorization_id"], "requests": len(rows) - 1,
            "reserved_usd": str(Decimal("0.10") * (len(rows) - 1)), "by_case": counts}


def reserve(case_id, payload, *, pricing, preflight_sha256):
    """Reserve irreversibly before calling; failures and interruptions cost a slot.

    Pricing is a caller-reviewed same-day snapshot, not a fetched price claim.
    Unknown/stale pricing or missing frozen-input preflight prevents reservation.
    Response usage/accounting remains a separate required runner responsibility.
    """
    if os.environ.get("ARSLAN_STABLE_LIVE") != "authorized-36-requests-usd5":
        raise RuntimeError("stable_authorization_missing")
    if (EVIDENCE / "HALT").exists():
        raise RuntimeError("stable_halted")
    value, digest = contract()
    case = next((case for case in value["cases"] if case["id"] == case_id), None)
    if case is None:
        raise RuntimeError("stable_case_inputs_unready")
    preflight = EVIDENCE / f"{case_id}-preflight.json"
    if not preflight.is_file() or hashlib.sha256(preflight.read_bytes()).hexdigest() != preflight_sha256:
        raise RuntimeError("stable_preflight_missing_or_changed")
    ready = json.loads(preflight.read_bytes())
    if (ready.get("case") != case_id or ready.get("contract_sha256") != digest
            or ready.get("status") != "ready" or not ready.get("inputs")):
        raise RuntimeError("stable_case_inputs_unready")
    for item in ready["inputs"]:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("stable_input_path_outside_evidence")
        source = (EVIDENCE / relative).resolve()
        if not source.is_relative_to(EVIDENCE.resolve()) or hashlib.sha256(source.read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError("stable_input_changed")
    if case_id == "S2-R2" and not ready.get("public_same_scope_conflict_review"):
        raise RuntimeError("stable_conflict_review_missing")
    today = datetime.now(timezone.utc).date().isoformat()
    if (pricing.get("verified_on_utc") != today or pricing.get("model") != payload.get("model")
            or pricing.get("source") != "https://api-docs.deepseek.com/quick_start/pricing/"
            or pricing.get("provider") != "deepseek" or pricing.get("endpoint") != "https://api.deepseek.com"):
        raise RuntimeError("stable_pricing_unverified")
    try:
        rates = [Decimal(str(pricing[key])) for key in ("input_usd_per_million", "output_usd_per_million")]
        if not all(rate.is_finite() and rate > 0 for rate in rates):
            raise ValueError
        ceiling = (200_000 * rates[0] + 8192 * rates[1]) / 1_000_000
        if ceiling > Decimal("0.10"):
            raise ValueError
    except (ValueError, ArithmeticError, KeyError) as error:
        raise RuntimeError("stable_price_exceeds_reservation_or_unknown") from error
    raw = json.dumps(payload, ensure_ascii=False).encode()
    if len(raw) > 100_000 or payload.get("max_tokens") != 8192:
        raise RuntimeError("stable_payload_cap")
    # r+ deliberately refuses a missing ledger: no zero-spend reset on deletion.
    with (EVIDENCE / "budget.jsonl").open("r+", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        rows, counts, limits = _records(stream, value, digest)
        if (EVIDENCE / "HALT").exists():
            raise RuntimeError("stable_halted")
        if len(rows) - 1 >= 36 or counts[case_id] >= limits[case_id]:
            raise RuntimeError("stable_budget_exhausted")
        number = len(rows)
        stream.seek(0, os.SEEK_END)
        stream.write(json.dumps({"type": "reservation", "request": number, "case": case_id,
            "reserved_usd": "0.10", "payload_bytes": len(raw),
            "payload_sha256": hashlib.sha256(raw).hexdigest(), "preflight_sha256": preflight_sha256,
            "pricing": pricing, "created_at": datetime.now(timezone.utc).isoformat()}) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
        return number


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initialize", action="store_true", help="Create once; never reset an existing ledger")
    args = parser.parse_args()
    if args.initialize:
        initialize()
    print(json.dumps(status(), indent=2))

"""0.1.41 calibration of the after-save source review (task brief A10).

Authorized by the product owner on 2026-09-26: at most 13 requests, at most
US$0.20 reserved, on the configured primary (official DeepSeek flash). Reuses
the retained 0.1.40 critique inputs (draft + frozen source bodies + request)
byte-for-byte, deduplicated by draft hash, and runs the 0.1.41 critique
(narrowed prompt, thinking off, temperature 0, 2048 output cap) ONCE each.

Every request is reserved in an exclusive ledger BEFORE it is sent; there are
no retries; a failed request keeps its reservation. The API key is decrypted
read-only from the owner's profile by the existing stable_primary path and is
never printed or written. Outputs are model critiques, not factual verdicts:
precision and recall are adjudicated afterwards by reading the sources.

    ARSLAN_0141_CALIBRATION=authorized-13-requests-usd0.20 \
      python -m evals.companion.review_calibration_0141 --evidence <sibling dir> \
        --out <new dir> --pricing <verified pricing json>
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import math
import os
import sqlite3
from decimal import ROUND_UP, Decimal
from pathlib import Path
from types import SimpleNamespace

AUTHORIZATION = "authorized-13-requests-usd0.20"
MAX_REQUESTS = 13
MAX_USD = Decimal("0.20")


def retained_subjects(evidence: Path) -> list[dict]:
    """The distinct drafts that 0.1.40 critiques actually saw, oldest round first."""
    seen, out = set(), []
    for path in sorted(evidence.glob("round-*/request-*.input.json"),
                       key=lambda p: (int(p.parent.name.split("-")[1]), p.name)):
        record = json.loads(path.read_text(encoding="utf-8"))
        messages = (record.get("payload") or {}).get("messages") or []
        if not messages or not str(messages[0].get("content", "")).startswith(("Review the draft", "Adjudicate")):
            continue
        wrapped = messages[1]["content"]
        raw = wrapped.split("\n", 1)[1].rsplit("\n<<<END_EXTERNAL", 1)[0]
        data = json.loads(raw)
        draft_sha = hashlib.sha256(data["draft"].encode()).hexdigest()
        if draft_sha in seen:
            continue
        seen.add(draft_sha)
        sources = {s["id"]: (SimpleNamespace(url=s.get("url", "")), s["text"]) for s in data["sources"]}
        out.append({"origin": f"{path.parent.name}/{path.name}", "case": record.get("case"),
                    "draft_sha256": draft_sha, "raw": raw, "sources": sources,
                    "subject": (hashlib.sha256(raw.encode()).hexdigest(), raw, sources)})
    return out


def primary_adapter(profile: Path, secret_file: Path, pricing: dict):
    """Same two read-only queries as the 0.1.40 stable runner, but gated by THIS
    authorization only — the 0.1.40 grants are closed and must not be drawn on."""
    if os.environ.get("ARSLAN_0141_CALIBRATION") != AUTHORIZATION:
        raise RuntimeError("calibration_authorization_missing")
    with sqlite3.connect(f"file:{profile / 'arslan.db'}?mode=ro", uri=True) as db:
        rows = db.execute("SELECT provider, model, base_url, api_key FROM provider_configs WHERE is_primary=1").fetchall()
        salt = db.execute("SELECT value FROM settings WHERE key='crypto_salt_b64'").fetchone()
    if len(rows) != 1 or not salt:
        raise RuntimeError("primary_or_salt_missing")
    provider, model, base_url, encrypted = rows[0]
    if (provider != "deepseek" or model != pricing["model"] or model != "deepseek-v4-flash"
            or (base_url or "").rstrip("/") not in {"", "https://api.deepseek.com", "https://api.deepseek.com/v1"}):
        raise RuntimeError("primary_changed_reverify_pricing")
    from arslan.llm.adapter import LLMAdapter
    from server.crypto_material import keyring
    key = keyring(secret_file.read_text().strip(), base64.b64decode(salt[0], validate=True)).decrypt(encrypted.encode()).decode()
    return LLMAdapter("openai", model, api_key=key, base_url=(base_url or "https://api.deepseek.com").rstrip("/"),
                      report_provider="deepseek")


def worst_case_usd(raw: str, pricing: dict) -> Decimal:
    from arslan.llm.request_policy import CRITIQUE_MAX_OUTPUT_TOKENS
    from server.orchestrator.research_review import PROMPT
    tokens_in = math.ceil((len(raw.encode()) + len(PROMPT.encode())) / 2)  # overestimates
    usd = (Decimal(tokens_in) * Decimal(pricing["input_usd_per_million"])
           + Decimal(CRITIQUE_MAX_OUTPUT_TOKENS) * Decimal(pricing["output_usd_per_million"])) / Decimal(1_000_000)
    return usd.quantize(Decimal("0.0001"), rounding=ROUND_UP)


def reserve(ledger: Path, draft_sha: str, usd: Decimal) -> int:
    rows = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()] if ledger.exists() else []
    spent = sum(Decimal(r["reserved_usd"]) for r in rows)
    if len(rows) >= MAX_REQUESTS or spent + usd > MAX_USD:
        raise RuntimeError("calibration_budget_exhausted")
    number = len(rows) + 1
    with ledger.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"request": number, "draft_sha256": draft_sha, "reserved_usd": str(usd),
                                 "invoice": False}) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return number


async def main() -> None:
    if os.environ.get("ARSLAN_0141_CALIBRATION") != AUTHORIZATION:
        raise SystemExit("calibration_authorization_missing")
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pricing", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    pricing = json.loads(args.pricing.read_text())
    subjects = retained_subjects(args.evidence)[:MAX_REQUESTS]
    plan = [{"origin": s["origin"], "case": s["case"], "draft_sha256": s["draft_sha256"],
             "worst_case_usd": str(worst_case_usd(s["raw"], pricing))} for s in subjects]
    total = sum(Decimal(p["worst_case_usd"]) for p in plan)
    print(json.dumps({"drafts": len(plan), "worst_case_total_usd": str(total)}, indent=1))
    if args.dry_run:
        print(json.dumps(plan, indent=1))
        return
    if total > MAX_USD:
        raise SystemExit("plan_exceeds_authorization")
    args.out.mkdir(parents=True, exist_ok=False)            # a fresh, never-reused directory
    (args.out / "plan.json").write_text(json.dumps({"pricing": pricing, "plan": plan}, indent=1))
    from server.orchestrator import research_review
    home = Path.home()
    adapter = primary_adapter(home / "Library/Application Support/Arslan", home / ".arslan/secret_key", pricing)
    ledger = args.out / "budget.jsonl"

    async def once(a, system, user, **kwargs):              # no retry of any kind
        return await a.chat(system, user, tools=None)

    for subject in subjects:
        number = reserve(ledger, subject["draft_sha256"], worst_case_usd(subject["raw"], pricing))
        result = await research_review.inspect(subject["subject"], adapter=adapter, chat=once, cache={})
        note = research_review.note(result, subject["sources"])
        (args.out / f"request-{number:02d}.result.json").write_text(json.dumps(
            {"request": number, "origin": subject["origin"], "case": subject["case"],
             "draft_sha256": subject["draft_sha256"], "note": note,
             "rejected_objections": result.get("rejected_objections")}, ensure_ascii=False, indent=1))
        print(f"#{number:02d} {subject['case']} {subject['origin']} -> {note['status']} "
              f"issues={len(note['issues'])}")


if __name__ == "__main__":
    asyncio.run(main())

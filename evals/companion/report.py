"""Validate and summarize existing checker evidence; never execute agent tasks.

python -m evals.companion.report --attempts evidence.json --output new-report.json
Omit --attempts to report the complete, currently unrun catalog denominator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from pydantic import TypeAdapter

from evals.companion.schema import Attempt, Catalog
from evals.companion.scoring import summarize

CATALOG_PATH = Path(__file__).with_name("catalog.json")


def load_catalog(path: Path = CATALOG_PATH) -> Catalog:
    return Catalog.model_validate_json(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    parser.add_argument("--attempts", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    catalog = load_catalog(args.catalog)
    attempts = TypeAdapter(list[Attempt]).validate_json(
        args.attempts.read_text(encoding="utf-8")
    ) if args.attempts else []
    report = summarize(catalog, attempts)
    report["catalog_sha256"] = hashlib.sha256(args.catalog.read_bytes()).hexdigest()
    report["evidence_sha256"] = (
        hashlib.sha256(args.attempts.read_bytes()).hexdigest() if args.attempts else None
    )
    # New evidence only: do not silently overwrite an earlier report.
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: report[key] for key in
                      ("passed", "denominator", "observed", "live_score_eligible")}))


if __name__ == "__main__":
    main()

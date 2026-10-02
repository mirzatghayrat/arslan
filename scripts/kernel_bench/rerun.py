"""Re-run specific bench cells (e.g. ones an environment fault invalidated).

    python -m scripts.kernel_bench.rerun T3:arslan:1 T2:hermes:1

Uses runner.run_one unchanged; the new record is appended to results.jsonl and
supersedes the earlier one with the same run label (report: last record wins).
"""
import json
import sys

from scripts.kernel_bench import runner


def main(cells: list[str]) -> None:
    prompts = json.loads((runner.HERE / "prompts.json").read_text())
    sb = runner.sandbox_profile()
    for cell in cells:
        task, who, n = cell.split(":")
        rec = runner.run_one(task, who, int(n), prompts, sb)
        print(json.dumps({k: rec[k] for k in ("run", "passed", "rc")} | {
            "score": rec["check"].get("score"), "usd_peak": rec["usage"]["usd_peak"],
            "span_s": rec["usage"]["span_s"], "rerun": True}), flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])

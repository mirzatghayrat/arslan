"""python -m scripts.shell_agreement [--corpus FILE] [--forms] [--strict] [--jobs N] [--report FILE]"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from scripts.shell_agreement import corpus as corpus_module, harness, oracle, sandbox


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.shell_agreement", description=__doc__)
    parser.add_argument("--corpus", type=Path, help="one command per line, or JSON lines with a command field")
    parser.add_argument("--forms", action="store_true", help="also check every mechanical form of each command")
    parser.add_argument("--strict", action="store_true",
                        help="fail on ask-above too (an ask text that started a forbidden program), not only "
                             "on the run-level kinds")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    parser.add_argument("--limit", type=int, default=0, help="only the first N commands (before the forms)")
    parser.add_argument("--timeout", type=float, default=sandbox.DEFAULT_TIMEOUT_S, help="seconds per run")
    parser.add_argument("--report", type=Path, help="write the full JSON report here")
    args = parser.parse_args(argv)

    commands = corpus_module.from_file(args.corpus) if args.corpus else corpus_module.from_tests()
    if args.limit:
        commands = commands[:args.limit]
    print(f"{len(commands)} commands", flush=True)
    report = harness.compare(commands, forms=args.forms, jobs=args.jobs, timeout_s=args.timeout,
                             progress=lambda done, total: print(f"  {done}/{total}", flush=True))
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in report.items() if k not in ("disagreements", "results")},
                     ensure_ascii=False))
    for d in report["disagreements"]:
        print(f"DISAGREE [{d['kind']}] {d['command']!r} judged {d['verdict']}; shell started {d['started']!r} "
              f"(stubs exit {d['stub_exit']}): {d['detail']}")
    failing = {k for k in report["kinds"] if k in oracle.HARD or args.strict}
    print(f"{len(report['disagreements'])} disagreements, {sum(report['kinds'].get(k, 0) for k in failing)} failing")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())

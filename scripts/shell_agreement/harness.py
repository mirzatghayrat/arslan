"""The whole comparison: a corpus, its forms, the sandbox runs, the verdicts, a report."""
from __future__ import annotations

import tempfile
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from scripts.shell_agreement import mutate, oracle, sandbox, stubs
from server.services import terminal_policy

_BWRAP = ""
_STUBS: Path | None = None


def _init(bwrap: str, stub_dir: str) -> None:
    global _BWRAP, _STUBS
    _BWRAP, _STUBS = bwrap, Path(stub_dir)


def check_one(command: str, timeout_s: float = sandbox.DEFAULT_TIMEOUT_S) -> dict:
    """Run `command` both ways (every stub succeeding, every stub failing) and judge each. A forbidden
    text is not run: nothing the shell starts can rank above it."""
    verdict = terminal_policy.assess(command)
    out = {"command": command, "level": verdict.level, "rule": verdict.rule, "runs": 0, "started": 0,
           "timed_out": 0, "disagreements": []}
    if verdict.level == "forbid":
        return out
    for stub_exit in (0, 1):
        run = sandbox.run(_BWRAP, _STUBS, command, stub_exit=stub_exit, timeout_s=timeout_s)
        out["runs"] += 1
        out["started"] += len(run.started)
        out["timed_out"] += int(run.timed_out)
        out["disagreements"] += [d.as_dict() for d in oracle.judge(run)]
    return out


def check(commands: list[str], *, jobs: int, timeout_s: float = sandbox.DEFAULT_TIMEOUT_S,
          progress=None) -> list[dict]:
    """Every command through the sandbox, `jobs` at a time. The stub directory is built once for the
    whole corpus (every word of it becomes a stub) and lives for the call."""
    bwrap = sandbox.require()
    with tempfile.TemporaryDirectory(prefix="shell-agreement-stubs-") as tmp:
        stub_dir = stubs.build(Path(tmp), commands)
        results: list[dict] = []
        with ProcessPoolExecutor(max_workers=max(1, jobs), initializer=_init,
                                 initargs=(bwrap, str(stub_dir))) as pool:
            for result in pool.map(check_one, commands, [timeout_s] * len(commands), chunksize=8):
                results.append(result)
                if progress and len(results) % 500 == 0:
                    progress(len(results), len(commands))
        return results


def expand(commands: list[str], *, forms: bool) -> list[str]:
    """The corpus, and with `forms` every mechanical form of each command, each text once."""
    seen: dict[str, None] = dict.fromkeys(commands)
    if forms:
        for command in commands:
            for _template, form in mutate.forms(command):
                seen.setdefault(form)
    return list(seen)


def summary(results: list[dict], seconds: float = 0.0) -> dict:
    disagreements = [d for r in results for d in r["disagreements"]]
    return {"commands": len(results), "levels": dict(Counter(r["level"] for r in results)),
            "runs": sum(r["runs"] for r in results), "programs_started": sum(r["started"] for r in results),
            "timed_out": sum(r["timed_out"] for r in results),
            "kinds": dict(Counter(d["kind"] for d in disagreements)), "seconds": round(seconds, 1),
            "disagreements": disagreements}


def compare(commands: list[str], *, forms: bool, jobs: int, timeout_s: float = sandbox.DEFAULT_TIMEOUT_S,
            progress=None) -> dict:
    started = time.monotonic()
    results = check(expand(commands, forms=forms), jobs=jobs, timeout_s=timeout_s, progress=progress)
    report = summary(results, time.monotonic() - started)
    report["results"] = results
    return report

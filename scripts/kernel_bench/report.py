"""Summarise a bench run: Pass^k per task, entrant and model, plus cost, model time and calls.

    python -m scripts.kernel_bench.report [results.jsonl] [--offpeak]

Pass^k = every one of the k repeats passed (score 3). That is the reliability bar; a
single success only shows a task is possible. The same entrant on two models is two rows.
Cost is shown at peak price, or halved with --offpeak (DeepSeek off-peak hours; it does not
apply to Claude models, so compare those rows without it). --round NAME keeps only that round's
runs (labels ending in `-NAME`, runner.ROUND).

Under the table, per entrant and model, two totals of tasks passed every time (v0.1.64 M64):
the old figure over every task, an unsupported task counting as not passed, and the same-task
figure over only the tasks every entrant on that model supports (R64's gate uses the second).
Code-review tasks (T13–T15) add bugs caught / planted and false positives, summed over repeats.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path


def load(path: str) -> list[dict]:
    return [json.loads(line) for line in open(path) if line.strip()]


def summarise(records: list[dict], offpeak: bool = False) -> list[dict]:
    groups: dict = defaultdict(list)
    for r in records:
        # Rows judged by an older pass rule (score only, before M1a) never mix with newer ones.
        groups[(r["task"], r["entrant"], r.get("model", "?"), r.get("judge", 1))].append(r)
    rows = []
    for (task, who, model, judged), rs in sorted(groups.items()):
        k = len(rs)
        passes = sum(1 for r in rs if r.get("passed"))
        usd = sum(r["usage"]["usd_peak"] for r in rs) / k / (2 if offpeak else 1)
        checks = [r.get("check") or {} for r in rs]
        review = [c for c in checks if "planted" in c]
        rows.append({"task": task, "entrant": who, "old_rule": judged < 2, "model": model, "k": k, "passes": passes, "pass_all": passes == k,
                     "unsupported": any(c.get("unsupported") for c in checks),
                     "review": {"caught": sum(c["caught"] for c in review), "planted": sum(c["planted"] for c in review),
                                "false_positives": sum(c["false_positives"] for c in review)} if review else None,
                     "mean_usd": round(usd, 4),
                     "mean_span_s": round(sum(r["usage"]["span_s"] for r in rs) / k, 1),
                     "mean_calls": round(sum(r["usage"]["model_calls"] for r in rs) / k, 1),
                     "ends": sorted({str(r.get("rc")) for r in rs})})
    return rows


def totals(rows: list[dict]) -> list[dict]:
    """Per entrant and model: tasks passed every time (Pass^k) over every task it has rows for, an
    unsupported task counting as not passed (the old figure), and over the same tasks only: those
    every entrant on that model ran (has rows for, none unsupported)."""
    by_model: dict = defaultdict(list)
    for r in rows:
        by_model[r["model"]].append(r)
    out = []
    for model, rs in sorted(by_model.items()):
        groups = sorted({(r["entrant"], r["old_rule"]) for r in rs})
        tasks = {r["task"] for r in rs}
        same = set(tasks)
        for g in groups:
            same &= {r["task"] for r in rs if (r["entrant"], r["old_rule"]) == g and not r["unsupported"]}
        for who, old in groups:
            mine = [r for r in rs if (r["entrant"], r["old_rule"]) == (who, old)]
            out.append({"entrant": who, "old_rule": old, "model": model, "k": sorted({r["k"] for r in mine}),
                        "pass_all": sum(1 for r in mine if r["pass_all"]), "tasks": len(tasks),
                        "same_pass_all": sum(1 for r in mine if r["pass_all"] and r["task"] in same),
                        "same_tasks": len(same), "same": sorted(same)})
    return out


def paired(records: list[dict]) -> dict:
    """task -> repeat -> {entrant: passed}: who passed on the same task and repeat."""
    out: dict = defaultdict(lambda: defaultdict(dict))
    for r in records:
        out[r["task"]][r["repeat"]][r["entrant"]] = r.get("passed")
    return {t: dict(v) for t, v in out.items()}


def render(rows: list[dict]) -> str:
    lines = ["| task | entrant | model | Pass^k | passes | mean $ | model time | calls | caught / planted | false pos. |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        who = r["entrant"] + (" (old rule)" if r.get("old_rule") else "")
        review = r.get("review")
        found = f"{review['caught']}/{review['planted']} | {review['false_positives']}" if review else "— | —"
        lines.append(f"| {r['task']} | {who} | {r['model']} | {'yes' if r['pass_all'] else 'no'} | "
                     f"{r['passes']}/{r['k']} | "
                     f"{r['mean_usd']:.3f} | {r['mean_span_s']}s | {r['mean_calls']} | {found} |")
    return "\n".join(lines)


def render_totals(rows: list[dict]) -> str:
    lines = ["| entrant | model | k | Pass^k, every task (unsupported = 0) | same-task Pass^k | same tasks |",
             "| --- | --- | --- | --- | --- | --- |"]
    for t in totals(rows):
        who = t["entrant"] + (" (old rule)" if t["old_rule"] else "")
        lines.append(f"| {who} | {t['model']} | {','.join(map(str, t['k']))} | {t['pass_all']}/{t['tasks']} | "
                     f"{t['same_pass_all']}/{t['same_tasks']} | {' '.join(t['same'])} |")
    return "\n".join(lines)


def sandbox_cards(records: list[dict], *, per_task: bool = False) -> dict:
    """SBX-7: per entrant and model (and, for SBX-8, per policy and task), the runs under Arslan's own sandbox, their
    run_command calls, every card, and the cards to leave the sandbox."""
    out: dict = {}
    for r in records:
        cards = r.get("sandbox_cards") or {}
        if cards.get("leave") is None:
            continue
        key = (r["entrant"], r.get("model", "?"), *((r.get("shell_policy") or "?", r["task"]) if per_task else ()))
        seen = out.setdefault(key, {"runs": 0, "run_commands": 0, "asked": 0, "leave": 0})
        seen["runs"] += 1
        for name in ("run_commands", "asked", "leave"):
            seen[name] += cards.get(name) or 0
    return out


def leave_share(c: dict) -> float | None:
    """The SBX card's number 2 ("The two numbers"): of the run_command calls, how many asked to leave the sandbox. A
    denial goes back to the model, so leaving is its own request, and each card is one call. None with no calls."""
    return c["leave"] / c["run_commands"] if c["run_commands"] else None


def _cards_row(c: dict) -> str:
    share = leave_share(c)
    return f"{c['runs']} | {c['run_commands']} | {c['asked']} | {c['leave']} | {'–' if share is None else f'{share:.0%}'} |"


def render_sandbox_cards(records: list[dict]) -> str:
    lines = ["| entrant | model | runs | run_command calls | cards | cards to leave the sandbox | share |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    lines += [f"| {who} | {model} | {_cards_row(c)}" for (who, model), c in sorted(sandbox_cards(records).items())]
    return "\n".join(lines)


def render_cards_per_task(records: list[dict]) -> str:
    lines = ["| entrant | model | policy | task | runs | run_command calls | cards | cards to leave the sandbox | share |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    lines += [f"| {who} | {model} | {policy} | {task} | {_cards_row(c)}"
              for (who, model, policy, task), c in sorted(sandbox_cards(records, per_task=True).items())]
    return "\n".join(lines)


def in_round(records: list[dict], name: str) -> list[dict]:
    return [r for r in records if str(r.get("run", "")).endswith(f"-{name}")]


# ── L7 goal mode: the completion bar (docs/plans/0164/L7-goal-mode.md, Bench plan) ──────────────────────────────────
# Per look: 4 goal tasks at k=6 and 13 other tasks at k=3 in each arm. The one full rerun a miss allows is pooled with
# the first look, and both thresholds double (+16 of 48, -6 of 78).
BAR_GAIN = 8
BAR_LOSS = 3
FALSE_PASS = ("False-pass rate (a goal mode with no real effect passing; exact, from the card): at most 1.47% at one "
              "look (gate 1, every rate 0.5); with the one pooled rerun, 1.31% for the whole bar (gate 1 alone 1.49%).")


def completed(record: dict) -> bool:
    """Complete means checked, never claimed: the task's checker gave 3, whatever the run's end or the goal said."""
    return (record.get("check") or {}).get("score") == 3


def _latest(records: list[dict]) -> list[dict]:
    """The last record of each run label (rerun.py's rule: a cell an environment fault invalidated is run again)."""
    by_label = {}
    for r in records:
        by_label[r.get("run")] = r
    return list(by_label.values())


def _per_task(records: list[dict]) -> dict:
    out: dict = defaultdict(int)
    for r in records:
        out[r["task"]] += 1
    return dict(out)


def completion_bar(off: list[dict], on: list[dict]) -> dict:
    """`on` against `off`, on the same build branch: (1) on the goal tasks, `on` completes at least `off` + 8 per look;
    (2) on the 13 other tasks, at least `off` - 3 per look. Judged only when both arms have exactly k=6 runs of each
    goal task and k=3 of each other task per look, every `on` run went as a goal on an instance that took goal mode,
    and no `off` run did."""
    from scripts.kernel_bench.goal_tasks import GOAL_TASKS, GOAL_TASK_REPEATS, OTHER_TASK_REPEATS, OTHER_TASKS
    off, on = _latest(off), _latest(on)
    goal_runs = len(GOAL_TASKS) * GOAL_TASK_REPEATS
    looks = len([r for r in off if r["task"] in GOAL_TASKS]) // goal_runs
    want = {**{t: GOAL_TASK_REPEATS * looks for t in GOAL_TASKS}, **{t: OTHER_TASK_REPEATS * looks for t in OTHER_TASKS}}
    why = None
    if looks not in (1, 2):
        why = f"the off arm has {looks} look(s) of goal-task runs; the bar takes one, or one pooled rerun"
    elif _per_task(off) != want or _per_task(on) != want:
        why = (f"each arm needs exactly {want['T18']} runs of each goal task and {want['T1']} of each of the 13 others "
               f"(off has {len(off)}, on has {len(on)} runs)")
    elif any((r.get("goal") or {}).get("setting") != "on" for r in on):
        why = "some on-arm runs did not go as goals on an instance that took goal mode"
    elif any(r.get("goal") is not None for r in off):
        why = "some off-arm runs went as goals"

    def side(tasks: tuple, margin: int) -> dict:
        n_off = sum(completed(r) for r in off if r["task"] in tasks)
        n_on = sum(completed(r) for r in on if r["task"] in tasks)
        need = n_off + margin * looks
        return {"off": n_off, "on": n_on, "runs": len(tasks) * want.get(tasks[0], 0), "need": need, "pass": n_on >= need}

    goal_side, other_side = side(GOAL_TASKS, BAR_GAIN), side(OTHER_TASKS, -BAR_LOSS)
    states = [r.get("goal") or {} for r in on]
    claimed = sum(1 for r, g in zip(on, states)
                  if not completed(r) and (g.get("status") == "complete" if g.get("status") else r.get("end") == "done"))
    return {"judged": why is None, "why": why, "looks": looks, "goal": goal_side, "other": other_side,
            "pass": why is None and goal_side["pass"] and other_side["pass"],
            "flagged_runs": sum(1 for g in states if (g.get("flagged") or 0) > 0),
            "flag_unseen_runs": sum(1 for g in states if g.get("setting") == "on" and g.get("flagged") is None),
            "claimed_not_checked": claimed}


def render_bar(bar: dict) -> str:
    def line(name: str, s: dict, rule: str) -> str:
        return (f"| {name} | {s['off']}/{s['runs']} | {s['on']}/{s['runs']} | {rule}: at least {s['need']} | "
                f"{'yes' if s['pass'] else 'no'} |")
    looks = max(bar["looks"], 1)
    verdict = "PASS" if bar["pass"] else ("FAIL" if bar["judged"] else f"NOT JUDGED: {bar['why']}")
    return "\n".join([
        f"Completion bar (L7, {looks} look{'s' if looks > 1 else ''}): {verdict}",
        "",
        "| side | off complete | on complete | needed | met |",
        "| --- | --- | --- | --- | --- |",
        line("goal tasks T18-T21", bar["goal"], f"off + {BAR_GAIN * looks}"),
        line("13 other tasks", bar["other"], f"off - {BAR_LOSS * looks}"),
        "",
        f"Reported, not gated: on runs with a flagged drafted check {bar['flagged_runs']} (flag not visible in the "
        f"frames: {bar['flag_unseen_runs']}); on runs the goal or the run called complete whose checker failed "
        f"{bar['claimed_not_checked']}.",
        FALSE_PASS,
    ])


def _option(argv: list[str], name: str) -> str | None:
    return argv[argv.index(name) + 1] if name in argv else None


def _rounds(records: list[dict], names: str) -> list[dict]:
    return [r for name in names.split(",") for r in in_round(records, name)]


if __name__ == "__main__":
    argv = sys.argv[1:]
    valued = ("--round", "--off-round", "--on-round")
    name = _option(argv, "--round")
    args = [a for i, a in enumerate(argv) if not a.startswith("--") and not (i and argv[i - 1] in valued)]
    path = args[0] if args else str(Path(os.environ.get("BENCH_ROOT", "/tmp/arslan-kernel-bench")) / "results.jsonl")
    recs = load(path)
    if "--bar" in argv:
        # --off-round / --on-round: a round name, or two comma-separated for the one pooled rerun.
        print(render_bar(completion_bar(_rounds(recs, _option(argv, "--off-round") or ""),
                                        _rounds(recs, _option(argv, "--on-round") or ""))))
        sys.exit(0)
    if name:
        recs = in_round(recs, name)
    rows = summarise(recs, offpeak="--offpeak" in sys.argv)
    print(render(rows))
    print()
    print(render_totals(rows))
    print()
    print(render_sandbox_cards(recs))
    print()
    print(render_cards_per_task(recs))

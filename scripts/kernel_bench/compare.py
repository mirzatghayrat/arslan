"""H0 PR 1 (docs/plans/2026-11-11-harness-plan.md §4.2, §4.3): one settings switch, off against on.

    python -m scripts.kernel_bench.compare run --tasks T1,T3 --runs 2 --switch KEY --off VALUE --on VALUE
        [--model MODEL] [--round NAME]
    python -m scripts.kernel_bench.compare report --switch KEY [--commit SHA] [--round NAME] [--table PATH]
    python -m scripts.kernel_bench.compare classify ROW_ID CLASS "One sentence of cause."

`run` runs every task `--runs` times in each arm on Arslan, the same day, model and commit, off then on for each
task and repeat (so drift during a round lands on both arms). Each arm sets the switch through
BENCH_ARSLAN_SETTINGS (#310; the driver PUTs it to the test instance's settings before the turn), on top of any
other settings already in that variable, and gets its own round in the run label (`<round>-<switch>-off|on`): the
meter caps and the run folders are per label. Every run goes through runner.run_one, so results.jsonl still gets
its record; this adds one row per run to the results table, `<BENCH_ROOT>/harness_results.jsonl`.

The table (§4.2) is keyed by commit, switch, arm, model, task, repeat and round (`row_id`). It holds what the bench
can observe of each run: pass, end state, tool steps, model requests, tokens in and out, cache hits, dollars (peak
price), time, cards shown, "done without evidence" (done_without_evidence.py), the tools the model was offered and
the request settings (temperature, max tokens, thinking, effort) as the metering proxy saw them sent, and a
failure class from harness plan §1.3 with one sentence of cause. The bench fills the class where the end says it
(auto_class); otherwise a reader does, with `classify`. Hand classes live in their own file,
`<BENCH_ROOT>/failure_classes.jsonl`, so rewriting or rerunning a row never loses them; the last one for a row wins.

`report` prints off against on per §4.3. The four task sets don't exist yet (H0 PR 2 and PR 3), so it applies the
rules to the tasks that ran, and says so: the veto as if they were the regression set, "counts as working" as if
they were the capability set; the behaviour and held-out lines are not judged.

Repeats per task: `--runs N` is one count for every task (runs_per_task). PR #864 (L7-0) makes the runner's
`--repeats` take `per-task` through goal_tasks.repeats_for; once it lands, runs_per_task can return that mapping
and this loop is unchanged.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

from scripts.kernel_bench import done_without_evidence, runner, tool_record

TABLE = "harness_results.jsonl"
CLASS_FILE = "failure_classes.jsonl"
ARMS = ("off", "on")
#: Harness plan §1.3's loss classes.
CLASSES = {
    "wait": "stopped to wait for the user",
    "incomplete": "incomplete result",
    "instruction": "missed an instruction detail",
    "facts": "facts or sources",
    "tool": "tool or environment",
    "bench": "the bench itself",
    "regression": "a regression from Arslan's own change",
    "other": "other",
}
#: The driver sets these itself (arslan_driver.settings_body); a switch on them would never reach the instance.
DRIVER_OWNED = frozenset({"shell_confirm_policy", "workspace_dir"})
KEY_FIELDS = ("commit", "switch", "arm", "model", "task", "repeat", "round")

# §4.3's rules. The regression set runs each task 5 times: a task that passed every off run and lost two or more
# on runs (5/5 to 3/5 or lower) vetoes, at any k.
VETO_TASK_DROP = 2
VETO_TOTAL_DROP = 2           # the total may fall by 2 runs, not more
VETO_COST_RISE = 0.25         # cost per run may rise 25%, not more, unless passes rise too
WORKS_GAIN = 3                # passes up by 3 or more counts as working

# ── one row ───────────────────────────────────────────────────────────────────

END_STATES = {"done": "done", "timeout": "timeout", "task_failed": "failed", "task_cancelled": "cancelled",
              "job_stopped": "cancelled", "job_out_of_budget": "budget", "job_blocked": "waiting",
              None: "no_report"}


def row_id(row: dict) -> str:
    return "/".join(str(row.get(k)) for k in KEY_FIELDS)


def end_state(record: dict, pause: str | None = None) -> str:
    """§4.2's end state: done, waiting, budget (used up), or how else it ended. A task turn left waiting because
    it used up its budget is `budget`; any other wait (needs the user, no progress) is `waiting`."""
    end = record.get("end")
    if end == "task_waiting_user":
        return "budget" if pause == "task_budget_exhausted" else "waiting"
    return END_STATES.get(end, end)


def pause_reason(folder: str) -> str | None:
    """The pause reason on the run's last task_state frame (task_service._state_frame carries it)."""
    frames = Path(f"{str(folder).rstrip('/')}.frames.jsonl")
    if not frames.is_file():
        return None
    states = [f for f in tool_record._jsonl(frames) if f.get("type") == "task_state"]
    return states[-1].get("pause_reason") if states else None


def auto_class(row: dict) -> tuple[str | None, str | None]:
    """The failure class the bench can tell from the run's end alone; (None, None) for a pass or when a reader
    has to look (the run ended "done" or timed out and the checker failed it)."""
    if row.get("passed"):
        return None, None
    state = row.get("end_state")
    if state == "waiting":
        return "wait", f"The run ended waiting for the user ({row.get('pause_reason') or row.get('end')})."
    if state == "budget":
        return "incomplete", "The run used up its budget before the task was done."
    if state == "no_report":
        return "bench", "The driver never reported how the run ended."
    if row.get("rate_limited_429"):
        return "tool", f"The provider refused {row['rate_limited_429']} model call(s) with 429."
    return None, None


def requests_sent(label: str, usage_rows: list[dict], since: float) -> dict:
    """The run's model requests as the metering proxy saw them sent: the tools offered (their union, in first-seen
    order) and each request setting's distinct values. Rows from a meter older than H0 carry none of it.
    #879 review, later item 4: only the rows from when the run started (`since`, as runner.usage reads them), so a
    rerun of the same round, whose label is the same, doesn't mix in the earlier run's requests."""
    mine = [r for r in usage_rows if r.get("cand") == label and r.get("model") != "?" and r.get("t", 0.0) >= since]
    sent = [r["req"] for r in mine if isinstance(r.get("req"), dict)]
    if not sent:
        return {"source": "not observed (no request settings in the meter's log)", "tools_offered": None,
                "settings": None}
    tools: list[str] = []
    settings: dict = {"model": sorted({str(r.get("model")) for r in mine})}
    for req in sent:
        tools += [t for t in req.get("tools") or [] if t not in tools]
        for key, value in req.items():
            if key != "tools" and value not in settings.setdefault(key, []):
                settings[key].append(value)
    return {"source": "metering proxy (as sent)", "tools_offered": tools, "settings": settings}


def table_row(record: dict, *, commit: str, dirty: bool, switch: str, arm: str, value: str, round_name: str,
              day: str, usage_rows: list[dict]) -> dict:
    folder = (record.get("artifacts") or {}).get("folder", "")
    steps = tool_record.calls("arslan", folder, {}) if folder else None
    dwe_steps = done_without_evidence.steps(folder) if folder else None
    usage = record.get("usage") or {}
    hit, miss = usage.get("cache_hit_tokens", 0), usage.get("cache_miss_tokens", 0)
    pause = pause_reason(folder) if folder else None
    sent = requests_sent(record["run"], usage_rows, record["started"])   # run() passes the record run_one just made
    row = {"commit": commit, "dirty": dirty, "switch": switch, "arm": arm, "value": value,
           "model": record.get("model"), "task": record["task"], "repeat": record["repeat"], "round": round_name,
           "day": day, "run": record["run"], "passed": bool(record.get("passed")),
           "check_score": (record.get("check") or {}).get("score"), "end": record.get("end"),
           "pause_reason": pause, "end_state": end_state(record, pause),
           "tool_steps": None if steps is None else len(steps), "model_requests": usage.get("model_calls", 0),
           "input_tokens": hit + miss, "output_tokens": usage.get("out_tokens", 0), "cache_hit_tokens": hit,
           "usd": usage.get("usd_peak", 0.0), "seconds": record.get("wall_s"),
           "cards_shown": (record.get("sandbox_cards") or {}).get("asked"),
           "done_without_evidence": None if dwe_steps is None else (
               done_without_evidence.claims_done(record.get("reply_tail") or "")
               and done_without_evidence.unchecked_write(dwe_steps)),
           "rate_limited_429": record.get("rate_limited_429", 0),
           "tools_offered": sent["tools_offered"], "request_settings": sent["settings"],
           "request_source": sent["source"]}
    row["failure_class"], row["failure_cause"] = auto_class(row)
    row["class_source"] = "auto" if row["failure_class"] else None
    row["id"] = row_id(row)
    return row


# ── the table and the hand classes ────────────────────────────────────────────

def _jsonl(path: Path) -> list[dict]:
    return list(tool_record._jsonl(path)) if path.is_file() else []


def append(rows: list[dict], root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with open(root / TABLE, "a") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def correct(root: Path, rid: str, cls: str, cause: str) -> dict:
    """A reader's class for one row, kept apart from the table so a rerun or rewrite of the row keeps it."""
    if cls not in CLASSES:
        raise SystemExit(f"class must be one of: {', '.join(CLASSES)}")
    if not cause.strip():
        raise SystemExit("give one sentence of cause")
    entry = {"id": rid, "class": cls, "cause": cause.strip(),
             "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    root.mkdir(parents=True, exist_ok=True)
    with open(root / CLASS_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def load(root: Path, table: Path | None = None) -> list[dict]:
    """The table's rows, the last one per key, each with its hand class over the bench's own where there is one."""
    rows: dict = {}
    for row in _jsonl(table or root / TABLE):
        rows[row["id"]] = row
    for entry in _jsonl(root / CLASS_FILE):
        if entry.get("id") in rows:
            rows[entry["id"]].update(failure_class=entry["class"], failure_cause=entry["cause"], class_source="hand")
    return list(rows.values())


# ── the verdict (§4.3) ────────────────────────────────────────────────────────

def _side(rows: list[dict]) -> dict:
    steps = [r["tool_steps"] for r in rows if r.get("tool_steps") is not None]
    classes: dict = {}
    for r in rows:
        if not r.get("passed"):
            key = r.get("failure_class") or "unclassified"
            classes[key] = classes.get(key, 0) + 1
    usd = sum(r.get("usd") or 0.0 for r in rows)
    return {"passes": sum(1 for r in rows if r.get("passed")), "runs": len(rows),
            "usd": round(usd, 4), "usd_per_run": usd / len(rows) if rows else 0.0,
            "median_steps": statistics.median(steps) if steps else None, "classes": classes}


def _per_task(rows: list[dict]) -> dict:
    out: dict = {}
    for r in rows:
        p, k = out.get(r["task"], (0, 0))
        out[r["task"]] = (p + bool(r.get("passed")), k + 1)
    return out


def verdict(off: list[dict], on: list[dict]) -> dict:
    """Off against on per §4.3, over whatever tasks ran (the sets don't exist yet)."""
    why = None
    for name in ("model", "commit", "day", "switch"):
        values = {r.get(name) for r in off + on}
        if len(values) > 1:
            why = f"the arms differ in {name} ({', '.join(sorted(map(str, values)))})"
            break
    tasks_off, tasks_on = _per_task(off), _per_task(on)
    if why is None and (not off or {t: k for t, (_, k) in tasks_off.items()} != {t: k for t, (_, k) in tasks_on.items()}):
        why = "the arms did not run the same tasks the same number of times"
    a, b = _side(off), _side(on)
    reasons = []
    for task, (p_off, k) in sorted(tasks_off.items()):
        p_on = tasks_on.get(task, (0, 0))[0]
        if p_off == k and p_on <= k - VETO_TASK_DROP:
            reasons.append(f"{task} fell from {p_off}/{k} to {p_on}/{k}")
    gain = b["passes"] - a["passes"]
    if gain < -VETO_TOTAL_DROP:
        reasons.append(f"the total fell by {-gain} runs (more than {VETO_TOTAL_DROP})")
    rise = (b["usd_per_run"] / a["usd_per_run"] - 1) if a["usd_per_run"] else (float("inf") if b["usd_per_run"] else 0.0)
    if b["usd_per_run"] > a["usd_per_run"] * (1 + VETO_COST_RISE) and gain <= 0:
        reasons.append(f"cost per run rose {rise:+.0%} with no gain in passes")
    works = gain >= WORKS_GAIN and not reasons
    judged = why is None
    return {"judged": judged, "why": why, "off": a, "on": b, "tasks": {t: (tasks_off[t], tasks_on.get(t, (0, 0)))
                                                                         for t in sorted(tasks_off)},
            "gain": gain, "cost_rise": rise, "veto": bool(reasons), "veto_reasons": reasons, "works": works,
            "verdict": "NOT JUDGED" if not judged else "VETO" if reasons else "WORKS" if works else "NO EFFECT"}


def _classes(c: dict) -> str:
    return ", ".join(f"{k} {n}" for k, n in sorted(c.items())) or "none"


def render(off: list[dict], on: list[dict]) -> str:
    v = verdict(off, on)
    first = (off + on)[0] if off + on else {}
    lines = [f"Off/on: switch `{first.get('switch')}` (off {next((r['value'] for r in off), '?')!r}, "
             f"on {next((r['value'] for r in on), '?')!r}); commit {str(first.get('commit'))[:12]}"
             f"{' (dirty)' if any(r.get('dirty') for r in off + on) else ''}; model {first.get('model')}; "
             f"day {first.get('day')}; round {first.get('round')}",
             "Sets: there is no regression, capability, held-out or behaviour set yet (H0 PR 2 and PR 3). The rules "
             "are applied to the tasks that ran: the veto as if they were the regression set, \"counts as working\" "
             "as if they were the capability set.",
             "",
             "| task | off passes | on passes |",
             "| --- | --- | --- |"]
    for task, ((p_off, k_off), (p_on, k_on)) in v["tasks"].items():
        lines.append(f"| {task} | {p_off}/{k_off} | {p_on}/{k_on} |")
    a, b = v["off"], v["on"]

    def steps(s: dict) -> str:
        return "–" if s["median_steps"] is None else f"{s['median_steps']:g}"
    lines += ["", "| arm | passes | median tool steps | $ per run | $ total | failure classes |",
              "| --- | --- | --- | --- | --- | --- |",
              f"| off | {a['passes']}/{a['runs']} | {steps(a)} | {a['usd_per_run']:.4f} | {a['usd']:.4f} | "
              f"{_classes(a['classes'])} |",
              f"| on | {b['passes']}/{b['runs']} | {steps(b)} | {b['usd_per_run']:.4f} | {b['usd']:.4f} | "
              f"{_classes(b['classes'])} |", ""]
    cost = "n/a" if v["cost_rise"] == float("inf") else f"{v['cost_rise']:+.0%}"
    lines.append(f"Veto: {'yes' if v['veto'] else 'no'} ({'; '.join(v['veto_reasons']) or 'no task fell 2 from all'}"
                 f"; total {v['gain']:+d}, the veto is below -{VETO_TOTAL_DROP}; cost per run {cost}, the veto is above "
                 f"+{VETO_COST_RISE:.0%} with no gain; behaviour set: not run)")
    lines.append(f"Counts as working: {'yes' if v['works'] else 'no'} (passes {v['gain']:+d}, needs +{WORKS_GAIN}; "
                 f"held-out set: not run)")
    lines.append(f"Verdict: {v['verdict']}" + (f" ({v['why']})" if v["why"] else ""))
    failed = [r for r in off + on if not r.get("passed")]
    if failed:
        lines += ["", "Failed runs (classify with `compare classify ROW_ID CLASS \"cause\"`):"]
        lines += [f"- {r['id']}: {r.get('end_state')}; {r.get('failure_class') or 'unclassified'}"
                  f"{' (' + r['class_source'] + ')' if r.get('class_source') else ''}"
                  f"{': ' + r['failure_cause'] if r.get('failure_cause') else ''}" for r in failed]
    return "\n".join(lines)


# ── running both arms ─────────────────────────────────────────────────────────

def runs_per_task(spec: str, tasks: list[str]) -> dict:
    n = int(spec)
    if n < 1:
        raise SystemExit("--runs must be at least 1")
    return {task: n for task in tasks}


def arm_settings(switch: str, value: str) -> dict:
    if switch in DRIVER_OWNED:
        raise SystemExit(f"{switch} is set by the driver; it cannot be the switch")
    base = json.loads(os.environ.get("BENCH_ARSLAN_SETTINGS") or "{}")
    if switch in base:
        raise SystemExit(f"BENCH_ARSLAN_SETTINGS already sets {switch}; the comparison sets it per arm")
    if not isinstance(value, str):
        raise SystemExit("a switch value is a string, as the settings API stores it")
    return {**base, switch: value}


@contextlib.contextmanager
def _arm(round_name: str, settings: dict):
    """The runner reads its round (runner.ROUND, at each run) and passes this process's environment to the driver
    (runner.command), which reads BENCH_ARSLAN_SETTINGS. Both are set for the arm and put back after, so runner.py
    needs no change for the comparison."""
    old_round, old_settings = runner.ROUND, os.environ.get("BENCH_ARSLAN_SETTINGS")
    runner.ROUND = round_name
    os.environ["BENCH_ARSLAN_SETTINGS"] = json.dumps(settings)
    try:
        yield
    finally:
        runner.ROUND = old_round
        if old_settings is None:
            os.environ.pop("BENCH_ARSLAN_SETTINGS", None)
        else:
            os.environ["BENCH_ARSLAN_SETTINGS"] = old_settings


def commit_of() -> tuple[str, bool]:
    """The commit of the Arslan under test (BENCH_REPO, as start_arslan.sh starts it; else this checkout), and
    whether its tracked files have changes."""
    repo = os.environ.get("BENCH_REPO") or str(runner.HERE.parents[1])

    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout.strip()
    return git("rev-parse", "HEAD"), bool(git("status", "--porcelain", "--untracked-files=no"))


def run(tasks: list[str], runs: dict, switch: str, values: dict, *, model: str, round_name: str) -> list[dict]:
    commit, dirty = commit_of()
    day = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    settings = {arm: arm_settings(switch, values[arm]) for arm in ARMS}
    (runner.ROOT / "tmp").mkdir(parents=True, exist_ok=True)
    prompts = json.loads((runner.HERE / "prompts.json").read_text())
    sb = runner.sandbox_profile()
    rows = []
    for n in range(1, max(runs.values()) + 1):
        for task in (t for t in tasks if n <= runs[t]):
            for arm in ARMS:                                # off, then on, for each task and repeat
                arm_round = f"{round_name}-{switch}-{arm}"
                with _arm(arm_round, settings[arm]):
                    record = runner.run_one(task, "arslan", n, prompts, sb, models={"arslan": model})
                row = table_row(record, commit=commit, dirty=dirty, switch=switch, arm=arm, value=values[arm],
                                round_name=round_name, day=day, usage_rows=runner._usage_rows())
                append([row], runner.ROOT)
                rows.append(row)
                print(json.dumps({k: row[k] for k in ("id", "passed", "end_state", "tool_steps", "usd",
                                                      "failure_class")}), flush=True)
    return rows


def select(rows: list[dict], switch: str, commit: str | None, round_name: str | None) -> tuple[list, list]:
    """One comparison's arms: the switch, at the commit given (else the last one it ran at), the round given
    (else that commit's last round)."""
    mine = [r for r in rows if r["switch"] == switch]
    if commit:
        mine = [r for r in mine if str(r["commit"]).startswith(commit)]
    elif mine:
        mine = [r for r in mine if r["commit"] == mine[-1]["commit"]]
    if round_name:
        mine = [r for r in mine if r["round"] == round_name]
    elif mine:
        mine = [r for r in mine if r["round"] == mine[-1]["round"]]
    return [r for r in mine if r["arm"] == "off"], [r for r in mine if r["arm"] == "on"]


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="compare")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--tasks", required=True)
    r.add_argument("--runs", default="1", help="runs per task in each arm")
    r.add_argument("--switch", required=True, help="a settings key, set through BENCH_ARSLAN_SETTINGS")
    r.add_argument("--off", required=True, help="its value in the off arm (explicit: a kept instance keeps settings)")
    r.add_argument("--on", required=True)
    r.add_argument("--model", default=runner.MODEL)
    r.add_argument("--round", default="", help="default: BENCH_ROUND, else h0-<UTC time>")
    p = sub.add_parser("report")
    p.add_argument("--switch", required=True)
    p.add_argument("--commit")
    p.add_argument("--round")
    p.add_argument("--table")
    c = sub.add_parser("classify")
    c.add_argument("row_id")
    c.add_argument("cls", choices=sorted(CLASSES))
    c.add_argument("cause")
    a = ap.parse_args(argv)
    if a.cmd == "run":
        tasks = a.tasks.split(",")
        name = a.round or runner.ROUND or "h0-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M")
        run(tasks, runs_per_task(a.runs, tasks), a.switch, {"off": a.off, "on": a.on}, model=a.model,
            round_name=name)
    elif a.cmd == "report":
        off, on = select(load(runner.ROOT, Path(a.table) if a.table else None), a.switch, a.commit, a.round)
        if not off and not on:
            raise SystemExit(f"no rows for {a.switch} in the table")
        print(render(off, on))
    else:
        print(json.dumps(correct(runner.ROOT, a.row_id, a.cls, a.cause), ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])

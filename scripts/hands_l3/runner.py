"""L3 runner (plan docs/specs/hands-v2-bakeoff/2026-10-10-l3-plan.md): each task through an Arslan test
instance with the development Arslan Hands, the model only through the metering proxy.

    scripts/hands_l3/start_instance.sh                   # the test instance, :8764
    scripts/kernel_bench/start_proxy.sh                  # the user starts it: only it holds the key
    .venv/bin/python -m scripts.hands_l3.runner --tasks P1,P2,P3,P4,P5 --nobatch P1,P3

Per task: set up the test content, run the conversation as a person at the window would (cards
answered by `policy.CardPolicy`), then judge: the task's checker, the risky-card audit of Hands'
trace, tool calls, model calls and cost from the proxy's log, wall time. One JSON line per run in
`$L3_ROOT/results.jsonl`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path

from scripts.hands_l3 import policy, tasks
from scripts.kernel_bench import arslan_driver

ROOT = Path(os.environ.get("L3_ROOT", "/tmp/arslan-hands-l3")).resolve()
PROXY = os.environ.get("BENCH_PROXY", "http://127.0.0.1:8900/c")
MODEL = os.environ.get("BENCH_MODEL", "deepseek-v4-pro")
API = os.environ.get("ARSLAN_API", "http://127.0.0.1:8764/api/v1")
INSTANCE = os.environ.get("L3_INSTANCE", "l3")          # start_instance.sh's name: its data dir
NOBATCH_SUFFIX = "-nobatch"                              # the proxy withholds desktop_batch for these


class L3Tracker(arslan_driver.TurnTracker):
    """The bench driver's idea of when a run is over, with L3's cards and tool counts."""

    def __init__(self, run_dir: str, cards: policy.CardPolicy, tools: policy.ToolCount):
        super().__init__(run_dir)
        self.cards, self.tools = cards, tools

    def on_frame(self, frame: dict, now: float) -> dict | None:
        self.tools.on_frame(frame)
        if frame.get("type") == "propose_action":
            self.last_activity = now
            self.approvals += 1
            allowed = self.cards.decide(frame, time.time())
            self.declined += 0 if allowed else 1
            return {"type": "confirm_action" if allowed else "cancel_action", "call_id": frame["call_id"]}
        return super().on_frame(frame, now)


async def converse(api: str, run_dir: str, prompt: str, transcript: Path, tracker: L3Tracker) -> dict:
    import websockets
    ws_url = api.replace("http", "ws", 1).rstrip("/").removesuffix("/api/v1") + "/ws/arslan/l3-" + uuid.uuid4().hex[:8]
    started = time.monotonic()
    tracker.last_activity = started
    with transcript.open("w") as log:
        async with websockets.connect(ws_url, max_size=None) as ws:
            await ws.recv()                                         # history
            await ws.send(json.dumps({"type": "user_message", "content": prompt}))
            while not tracker.finished(time.monotonic(), started):
                try:
                    frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                except asyncio.TimeoutError:
                    continue
                log.write(json.dumps(frame, ensure_ascii=False) + "\n")
                reply = tracker.on_frame(frame, time.monotonic())
                if reply:
                    await ws.send(json.dumps(reply))
    # Wall time ends at the last activity, not after the quiet period that confirms the end.
    return {"wall_s": round(tracker.last_activity - started, 1), "end": tracker.end_reason,
            "final": "".join(tracker.final_text)[-3000:]}


def hands_trace(since: float, until: float) -> list[dict]:
    """This instance's Hands trace entries between two wall-clock times, each with `t` (epoch s)."""
    folder = ROOT / "data" / INSTANCE / "hands" / "trace"
    out = []
    for path in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
        for line in path.read_text().splitlines():
            try:
                entry = json.loads(line)
                entry["t"] = datetime.fromisoformat(entry["at"]).timestamp()
            except (ValueError, KeyError):
                continue
            if since - 1 <= entry["t"] <= until + 5:
                out.append(entry)
    return out


def usage(label: str) -> dict:
    log = ROOT / "usage.jsonl"
    rows = [json.loads(line) for line in log.open()] if log.exists() else []
    mine = [r for r in rows if r["cand"] == label and r["model"] != "?"]
    return {"model_calls": len(mine), "usd_peak": round(sum(r["usd_peak"] for r in mine), 5)}


def fixture_up(run: Path) -> subprocess.Popen:
    from scripts.hands_harness.run import build, launch
    subprocess.run(["pkill", "-x", "HarnessFixture"], capture_output=True)
    fixture, _ = build(run)
    proc = launch(fixture, {"HARNESS_LOG": str(run / "events.log"), "HARNESS_STATE": str(run / "state.json"),
                            "HARNESS_CMD": str(run / "cmd")})
    time.sleep(2)
    return proc


def run_task(task: tasks.Task, run_id: str, nobatch: bool) -> dict:
    label = f"{run_id}-{task.id}" + (NOBATCH_SUFFIX if nobatch else "")
    run = ROOT / "runs" / label
    run.mkdir(parents=True, exist_ok=True)
    record: dict = {"run": label, "task": task.id, "nobatch": nobatch, "model": MODEL}
    fixture = None
    try:
        task.setup()                                                # a setup that fails is this run's error, not the round's
        fixture = fixture_up(run) if task.fixture else None
        arslan_driver.configure(API, str(tasks.ROOT), f"{PROXY}/{label}", MODEL)
        cards = policy.CardPolicy(risky_ok=task.risky_ok)
        tools = policy.ToolCount(withheld=("desktop_batch",) if nobatch else ())
        started = time.time()
        out = asyncio.run(converse(API, str(tasks.ROOT), task.prompt, run / "frames.jsonl",
                                   L3Tracker(str(tasks.ROOT), cards, tools)))
        ended = time.time()
        time.sleep(1)                                               # the last trace line and Notes' save
        trace = hands_trace(started, ended)
        cards_out = [vars(c) for c in cards.cards]
        ok, detail = task.check({"fixture_dir": str(run), "cards": cards_out})
        record.update(out, done=ok, check=detail, cards=cards_out, tool_calls=tools.calls,
                      tool_total=tools.total, used_withheld=tools.used_withheld, model_errors=tools.model_errors,
                      risky_without_card=policy.audit(trace, cards.cards), hands_calls=len(trace),
                      **usage(label))
    except Exception as exc:                                        # a broken run is recorded, not hidden
        record.update(done=False, error=f"{type(exc).__name__}: {exc}"[:500])
    finally:
        if fixture is not None:
            fixture.terminate()
    record["counted"], record["not_counted_because"] = policy.counted(record)
    with (ROOT / "results.jsonl").open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", default="P1,P2,P3,P4,P5")
    parser.add_argument("--nobatch", default="", help="tasks to run again with desktop_batch withheld")
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    run_id = time.strftime("l3-%m%d-%H%M")
    picked = [tasks.TASKS[t] for t in args.tasks.split(",") if t]
    again = [tasks.NOBATCH.get(t, tasks.TASKS[t]) for t in args.nobatch.split(",") if t]
    for task, nobatch in [(t, False) for t in picked] + [(t, True) for t in again]:
        record = run_task(task, run_id, nobatch)
        print(json.dumps({k: record.get(k) for k in ("run", "done", "check", "wall_s", "tool_total", "model_calls",
                                                     "usd_peak", "risky_without_card", "counted", "not_counted_because")},
                         ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""0.1.52 acceptance items 1 and 3 (task book A5), against an Arslan test instance and the
metering proxy (see README.md). Paid model calls; run only with an approved cap.

    python -m scripts.kernel_bench.accept_0152 memory    # 1: a preference from an earlier conversation
    python -m scripts.kernel_bench.accept_0152 lessons   # 3: AppleScript refused once -> next T1 goes to EventKit

Item 3 asks run 1 to TRY AppleScript first: on this Mac Reminders refuses Apple Events from the
bench's process (macOS automation permission), while Swift/EventKit is allowed. Left to itself
the model often goes to EventKit straight away, which would show nothing about learning.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx

from scripts.kernel_bench import arslan_driver, check_t1

ROOT = Path(os.environ.get("BENCH_ROOT", "/tmp/arslan-accept-0152")).resolve()
API = os.environ.get("ARSLAN_API", "http://127.0.0.1:8762/api/v1")
PROXY = os.environ.get("BENCH_PROXY", "http://127.0.0.1:8900/c")
MODEL = os.environ.get("BENCH_MODEL", "deepseek-v4-pro")
ROUND = os.environ.get("BENCH_ROUND", "a")


def turn(label: str, prompt: str) -> dict:
    run = ROOT / "runs" / label
    run.mkdir(parents=True, exist_ok=True)
    arslan_driver.configure(API, str(run), f"{PROXY}/{label}", MODEL)
    started = time.monotonic()
    out = asyncio.run(arslan_driver.run(API, str(run), prompt, f"{run}.frames.jsonl"))
    out["wall_s"] = round(time.monotonic() - started)
    out["steps"] = steps(Path(f"{run}.frames.jsonl"))
    return out


def steps(frames: Path) -> list[str]:
    out = []
    for line in frames.read_text().splitlines():
        frame = json.loads(line)
        if frame.get("type") == "tool_call":
            out.append(f"{frame.get('tool')}: {str(frame.get('args_summary'))[:100]}")
    return out


def get(path: str):
    return httpx.get(f"{API}{path}", timeout=30).json()


def wait_for(predicate, timeout_s: float = 90.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(3)
    return predicate()


def memory() -> dict:
    a = turn(f"accept-mem-{ROUND}-1", "以后回答我的时候，请简短、先给结论，再用要点列出理由。记住这一点。")
    saved = wait_for(lambda: [e for e in get("/memory/entries") if e.get("status") == "active"], 60)
    b = turn(f"accept-mem-{ROUND}-2", "我喜欢什么样的回答？")
    reply = b["final"]
    hits = [w for w in ("简短", "结论", "要点") if w in reply]
    denies = [w for w in ("没存", "还没存", "没有记", "不知道你") if w in reply]
    return {"item": 1, "saved_active": [(e["content"], e.get("confirmation_kind")) for e in saved],
            "reply": reply[:600], "keywords_in_reply": hits, "denials_in_reply": denies,
            "passed": bool(saved) and len(hits) >= 2 and not denies,
            "turn_a": a, "turn_b": {k: b[k] for k in ("secs", "steps")}}


T1 = "在「提醒事项」里新建一个列表「{list}」，加 3 条提醒：明早 9 点交周报、周五买牛奶、下周一给房东打电话。"


def first_reminder_route(step_lines: list[str]) -> str:
    for line in step_lines:
        low = line.lower()
        if "osascript" in low or "applescript" in low or "tell application" in low:
            return "applescript"
        if "eventkit" in low or "swift" in low or "ekeventstore" in low:
            return "eventkit"
    return "unknown"


def lessons() -> dict:
    before = {item["id"] for item in get("/lessons")}
    l1 = f"验收-0152-{ROUND}-r1"          # cleanup_t1.py knows this prefix
    r1 = turn(f"arslan-T1-accept-{ROUND}-r1", "先试试用 AppleScript（osascript）。" + T1.format(list=l1))
    learned = wait_for(lambda: [x for x in get("/lessons") if x["id"] not in before], 120)
    l2 = f"验收-0152-{ROUND}-r2"
    r2 = turn(f"arslan-T1-accept-{ROUND}-r2", T1.format(list=l2))
    after = {item["id"]: item for item in wait_for(lambda: [x for x in get("/lessons") if x["followed"]], 60) or get("/lessons")}
    tool_calls = lambda r: len(r["steps"])  # noqa: E731
    return {
        "item": 3,
        "run1": {"route_first": first_reminder_route(r1["steps"]), "steps": r1["steps"], "secs": r1["secs"],
                 "check": check_t1.check(l1, r1["final"])["score"]},
        "learned": [{k: x[k] for k in ("id", "text", "source", "status")} for x in learned],
        "run2": {"route_first": first_reminder_route(r2["steps"]), "steps": r2["steps"], "secs": r2["secs"],
                 "check": check_t1.check(l2, r2["final"])["score"]},
        "counters": [{k: x[k] for k in ("id", "recalled", "followed", "succeeded", "failed")} for x in after.values()],
        "passed": bool(learned) and first_reminder_route(r2["steps"]) == "eventkit"
                  and tool_calls(r2) < tool_calls(r1) and r2["secs"] < r1["secs"],
    }


if __name__ == "__main__":
    which = sys.argv[1]
    result = memory() if which == "memory" else lessons()
    out = ROOT / f"accept-{which}-{ROUND}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in result.items() if k not in ("turn_a",)}, ensure_ascii=False, indent=1))

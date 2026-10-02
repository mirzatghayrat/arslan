"""Run one task through an Arslan test instance, as a person at the window would.

Approves confirmation cards for work inside the task folder, declines anything else,
waits for background jobs, and writes every frame to a transcript.

    python -m scripts.kernel_bench.arslan_driver <api_base> <run_dir> <prompt_file>

The decision of WHEN a run is over lives in `TurnTracker` (pure, unit-tested):
heartbeat pings are not activity — in the sample bake-off they kept resetting an idle
timer and a finished 66 s run was recorded as 330 s.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from dataclasses import dataclass, field

import os

TERMINAL_TASK_PHASES = {"completed", "failed", "cancelled", "waiting_user"}
# Outside the bench sandbox (BENCH_SANDBOX=none: Arslan's browser cannot start
# inside sandbox-exec — seatbelt does not nest), nothing in the kernel keeps a
# command off the real disk, so the stand-in person declines every card that asks
# (deleting, installing, sending, acting in pages). Commands Arslan runs without a
# card (reads, scripts, downloads into the task folder) and page reads still run.
DECLINE_CARDS = os.environ.get("BENCH_DECLINE_CARDS") == "1"
IDLE_AFTER_TURN_S = 20      # quiet period after the answer before we call it done
RUN_TIMEOUT_S = 15 * 60


@dataclass
class TurnTracker:
    run_dir: str
    turn_done: bool = False
    jobs_open: set = field(default_factory=set)
    final_text: list = field(default_factory=list)
    approvals: int = 0
    last_activity: float = 0.0
    end_reason: str = ""

    def inside(self, path: str) -> bool:
        return bool(path) and (path.startswith(self.run_dir) or not path.startswith("/"))

    def on_frame(self, frame: dict, now: float) -> dict | None:
        """Update state from one frame; return the reply to send, if any."""
        t = frame.get("type")
        if t in ("ping", "pong"):
            return None                       # heartbeats are not activity
        self.last_activity = now
        if t == "stream_chunk":
            self.final_text.append(frame.get("content") or "")
        elif t == "stream_end":
            self.turn_done = True
        elif t == "task_state" and frame.get("phase") in TERMINAL_TASK_PHASES:
            self.turn_done = True
            if frame.get("phase") != "completed":
                self.end_reason = f"task_{frame.get('phase')}"
        elif t == "job_update":
            job = frame.get("job_id")
            if frame.get("phase") == "finished":
                self.jobs_open.discard(job)
            else:
                self.jobs_open.add(job)
        elif t == "propose_run_command":
            self.approvals += 1
            if DECLINE_CARDS:
                return {"type": "cancel_run_command", "call_id": frame["call_id"]}
            return {"type": "confirm_run_command", "call_id": frame["call_id"], "remember": False}
        elif t == "propose_workspace_write":
            self.approvals += 1
            ok = self.inside(frame.get("path", ""))
            return {"type": "confirm_workspace_write" if ok else "cancel_workspace_write", "call_id": frame["call_id"]}
        elif t == "propose_action":
            self.approvals += 1
            return {"type": "cancel_action" if DECLINE_CARDS else "confirm_action", "call_id": frame["call_id"]}
        elif t in ("propose_schedule", "propose_connect_mcp", "propose_enroll_node"):
            self.approvals += 1
            return {"type": "cancel_schedule" if t == "propose_schedule" else "cancel_action", "call_id": frame["call_id"]}
        return None

    def finished(self, now: float, started: float) -> bool:
        if now - started >= RUN_TIMEOUT_S:
            self.end_reason = self.end_reason or "timeout"
            return True
        if self.turn_done and not self.jobs_open and now - self.last_activity >= IDLE_AFTER_TURN_S:
            self.end_reason = self.end_reason or "done"
            return True
        return False


async def run(api: str, run_dir: str, prompt: str, transcript: str) -> dict:
    import websockets
    ws_url = api.replace("http", "ws", 1).rstrip("/").removesuffix("/api/v1") + "/ws/arslan/bakeoff-" + uuid.uuid4().hex[:8]
    tracker = TurnTracker(run_dir)
    started = time.monotonic()
    tracker.last_activity = started
    with open(transcript, "w") as log:
        async with websockets.connect(ws_url, max_size=None) as ws:
            await ws.recv()                                     # history
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
    return {"secs": round(time.monotonic() - started), "approvals": tracker.approvals,
            "end": tracker.end_reason, "final": "".join(tracker.final_text)[-4000:]}


def configure(api: str, run_dir: str, base_url: str, model: str) -> None:
    """Point the test instance's model at the metering proxy and its workspace at the run folder."""
    import httpx
    with httpx.Client(timeout=30) as c:
        cfgs = c.get(f"{api}/settings/provider-configs").json()
        cfg = next((x for x in cfgs if x["label"] == "bench"), None)
        body = {"label": "bench", "provider": "openai", "model": model, "base_url": base_url, "api_key": "bench-dummy"}
        cfg = c.put(f"{api}/settings/provider-configs/{cfg['id']}", json=body).json() if cfg else \
            c.post(f"{api}/settings/provider-configs", json=body).json()
        c.patch(f"{api}/settings/provider-configs/{cfg['id']}/primary").raise_for_status()
        c.put(f"{api}/settings", json={"workspace_dir": run_dir}).raise_for_status()


if __name__ == "__main__":
    api, run_dir, prompt_file, base_url, model = sys.argv[1:6]
    configure(api, run_dir, base_url, model)
    out = asyncio.run(run(api, run_dir, open(prompt_file).read().strip(), run_dir.rstrip("/") + ".frames.jsonl"))
    print(json.dumps(out, ensure_ascii=False))

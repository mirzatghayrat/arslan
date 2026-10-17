"""Run one task through an Arslan test instance, as a person at the window would.

Approves confirmation cards for work inside the task folder, declines anything else,
waits for background jobs, and writes every frame to a transcript.

    python -m scripts.kernel_bench.arslan_driver <api_base> <run_dir> <prompt_file> <base_url> <model>
        [--provider openai|anthropic] [--decline-rule RULE ...] [--decline-note TEXT]

The prompt file holds one prompt, or a JSON list of prompts for a task of several turns:
each is sent once the previous turn is over, and the run folder is copied to
`<run_dir>.turn<N>` in between so a checker can compare the turns.

The decision of WHEN a run is over lives in `TurnTracker` (pure, unit-tested):
heartbeat pings are not activity — in the sample bake-off they kept resetting an idle
timer and a finished 66 s run was recorded as 330 s.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field

# The server's task phases (arslan/companion/contracts.py TaskState.phase). The bench
# used to wait for "completed", which the server never sends.
TERMINAL_TASK_PHASES = {"succeeded", "failed", "cancelled", "waiting_user"}
# Outside the bench sandbox (BENCH_SANDBOX=none: Arslan's browser cannot start
# inside sandbox-exec — seatbelt does not nest), nothing in the kernel keeps a
# command off the real disk, so the stand-in person declines every card that asks
# (deleting, installing, sending, acting in pages). Commands Arslan runs without a
# card (reads, scripts, downloads into the task folder) and page reads still run.
DECLINE_CARDS = os.environ.get("BENCH_DECLINE_CARDS") == "1"
# 0.1.51 P3 rounds (BENCH_CARDS=sandboxed): Arslan's own sandbox now keeps commands
# inside the task folder, temp and caches, so the stand-in answers cards as a user
# would: deleting and installing INSIDE the sandbox are approved; a card that would
# let a command OUT of the sandbox is declined (this is the real disk), and so is
# anything outward or that drives other apps — Apple Events bypass the file sandbox
# (Finder does the work) — except Reminders for T1, which is the task itself.
CARDS = os.environ.get("BENCH_CARDS", "")
APPROVE_IN_SANDBOX = {"", "delete", "install"}
IDLE_AFTER_TURN_S = 20      # quiet period after the answer before we call it done
RUN_TIMEOUT_S = 15 * 60


@dataclass
class TurnTracker:
    run_dir: str
    turn_done: bool = False
    # A task turn is over at its final task_state, which can come well after stream_end (the
    # post-turn review runs first): until then the run is not over (③Hands' review of #190).
    task_open: bool = False
    jobs_open: set = field(default_factory=set)
    final_text: list = field(default_factory=list)
    approvals: int = 0
    sandbox_cards: int = 0
    declined: int = 0
    last_activity: float = 0.0
    end_reason: str = ""
    # A stand-in person who says no to command cards whose rule matches one of these patterns
    # (regular expressions: the same deletion comes as `delete`, `hermes:find -delete`, ...),
    # with a sentence (the card's note: server/services/approvals.py reads it).
    decline_rules: frozenset = frozenset()
    decline_note: str = ""
    idle_after_s: float = IDLE_AFTER_TURN_S

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
            self.turn_done, self.task_open = True, False
            if frame.get("phase") != "succeeded":
                self.end_reason = f"task_{frame.get('phase')}"
        elif t == "task_state":
            self.task_open = True
        elif t == "job_update":
            job = frame.get("job_id")
            if frame.get("phase") == "finished":
                self.jobs_open.discard(job)
                # A background job never sends task_state to the chat; how it ended is only
                # its outcome (server/services/background_jobs.py outcome_of).
                if frame.get("outcome") not in (None, "done"):
                    self.end_reason = f"job_{frame.get('outcome')}"
            else:
                self.jobs_open.add(job)
        elif t == "propose_run_command":
            self.approvals += 1
            if any(re.search(p, frame.get("rule") or "") for p in self.decline_rules):
                self.declined += 1
                return {"type": "cancel_run_command", "call_id": frame["call_id"], "note": self.decline_note}
            if self._approve_command(frame):
                return {"type": "confirm_run_command", "call_id": frame["call_id"], "remember": False}
            self.declined += 1
            return {"type": "cancel_run_command", "call_id": frame["call_id"]}
        elif t == "propose_workspace_write":
            self.approvals += 1
            ok = self.inside(frame.get("path", ""))
            if not ok:
                return {"type": "cancel_workspace_write", "call_id": frame["call_id"]}
            # 0.1.61 PR 2b: a yes carries its scope. "In this conversation" keeps one card per run, as
            # before (a scope-less yes is once only now, and every write would ask again).
            reply = {"type": "confirm_workspace_write", "call_id": frame["call_id"]}
            if "conversation" in (frame.get("options") or []):
                reply["scope"] = "conversation"
            return reply
        elif t == "propose_action":
            self.approvals += 1
            return {"type": "cancel_action" if DECLINE_CARDS else "confirm_action", "call_id": frame["call_id"]}
        elif t in ("propose_schedule", "propose_connect_mcp", "propose_enroll_node"):
            self.approvals += 1
            return {"type": "cancel_schedule" if t == "propose_schedule" else "cancel_action", "call_id": frame["call_id"]}
        return None

    def _approve_command(self, frame: dict) -> bool:
        if DECLINE_CARDS:
            return False
        if CARDS != "sandboxed":
            # Apple Events reach other apps (Finder would move files to the user's real Trash,
            # outside the bench folder): declined, except Reminders for T1, which is the task.
            return frame.get("rule") != "apple-events" or "-T1-" in self.run_dir
        if frame.get("sandbox"):
            self.sandbox_cards += 1
            return False
        rule = frame.get("rule") or ""
        return rule in APPROVE_IN_SANDBOX or (rule == "apple-events" and "-T1-" in self.run_dir)

    def finished(self, now: float, started: float) -> bool:
        if now - started >= RUN_TIMEOUT_S:
            self.end_reason = self.end_reason or "timeout"
            return True
        if self.turn_done and not self.task_open and not self.jobs_open and now - self.last_activity >= self.idle_after_s:
            self.end_reason = self.end_reason or "done"
            return True
        return False

    def next_turn(self, now: float) -> str:
        """Close this turn and start the next; returns this turn's answer."""
        answer = "".join(self.final_text)
        self.final_text, self.turn_done, self.last_activity = [], False, now
        return answer


def load_prompts(path: str) -> list[str]:
    """One prompt, or a JSON list of prompts (one per turn)."""
    text = open(path, encoding="utf-8").read().strip()
    if text.startswith("["):
        try:
            turns = json.loads(text)
            if isinstance(turns, list) and all(isinstance(x, str) for x in turns):
                return turns
        except json.JSONDecodeError:
            pass
    return [text]


def snapshot(run_dir: str, turn: int) -> str:
    """Copy the run folder as it stands after `turn` (1-based) next to it."""
    dest = f"{run_dir.rstrip('/')}.turn{turn}"
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(run_dir, dest, symlinks=True)
    return dest


async def run(api: str, run_dir: str, prompts: list[str] | str, transcript: str, *,
              decline_rules: frozenset = frozenset(), decline_note: str = "", connect=None,
              idle_after_s: float = IDLE_AFTER_TURN_S, recv_timeout: float = 2) -> dict:
    """Send each prompt in turn on one conversation; the next goes only once the previous
    turn is over (answer ended, no background job open, quiet for `idle_after_s`)."""
    if isinstance(prompts, str):                       # older callers (accept_0152) pass one prompt
        prompts = [prompts]
    if connect is None:
        import websockets
        connect = websockets.connect
    ws_url = api.replace("http", "ws", 1).rstrip("/").removesuffix("/api/v1") + "/ws/arslan/bakeoff-" + uuid.uuid4().hex[:8]
    tracker = TurnTracker(run_dir, decline_rules=decline_rules, decline_note=decline_note, idle_after_s=idle_after_s)
    started = time.monotonic()
    tracker.last_activity = started
    replies: list[str] = []
    with open(transcript, "w") as log:
        async with connect(ws_url, max_size=None) as ws:
            await ws.recv()                                     # history
            for n, prompt in enumerate(prompts, 1):
                turn_started = time.monotonic()
                await ws.send(json.dumps({"type": "user_message", "content": prompt}))
                while not tracker.finished(time.monotonic(), turn_started):
                    try:
                        frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=recv_timeout))
                    except asyncio.TimeoutError:
                        continue
                    log.write(json.dumps(frame, ensure_ascii=False) + "\n")
                    reply = tracker.on_frame(frame, time.monotonic())
                    if reply:
                        await ws.send(json.dumps(reply))
                replies.append(tracker.next_turn(time.monotonic()))
                if tracker.end_reason == "timeout":
                    break
                if n < len(prompts):
                    snapshot(run_dir, n)
    return {"secs": round(time.monotonic() - started), "approvals": tracker.approvals,
            "sandbox_cards": tracker.sandbox_cards, "declined": tracker.declined,
            "end": tracker.end_reason, "turns": len(replies),
            "replies": [r[-4000:] for r in replies], "final": (replies[-1] if replies else "")[-4000:]}


def provider_body(provider: str, model: str, base_url: str) -> dict:
    """The bench's provider config. Anthropic: base_url ends in /v1 (the provider posts to
    <base_url>/messages); OpenAI-compatible: the proxy path without /v1."""
    return {"label": "bench", "provider": provider, "model": model, "base_url": base_url, "api_key": "bench-dummy"}


def configure(api: str, run_dir: str, base_url: str, model: str, provider: str = "openai") -> None:
    """Point the test instance's model at the metering proxy and its workspace at the run folder."""
    import httpx
    with httpx.Client(timeout=30) as c:
        cfgs = c.get(f"{api}/settings/provider-configs").json()
        cfg = next((x for x in cfgs if x["label"] == "bench"), None)
        body = provider_body(provider, model, base_url)
        cfg = c.put(f"{api}/settings/provider-configs/{cfg['id']}", json=body).json() if cfg else \
            c.post(f"{api}/settings/provider-configs", json=body).json()
        c.patch(f"{api}/settings/provider-configs/{cfg['id']}/primary").raise_for_status()
        c.put(f"{api}/settings", json={"workspace_dir": run_dir}).raise_for_status()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("api")
    ap.add_argument("run_dir")
    ap.add_argument("prompt_file")
    ap.add_argument("base_url")
    ap.add_argument("model")
    ap.add_argument("--provider", default="openai", choices=("openai", "anthropic"))
    ap.add_argument("--decline-rule", action="append", default=[], help="regular expression on the card's rule")
    ap.add_argument("--decline-note", default="")
    a = ap.parse_args()
    configure(a.api, a.run_dir, a.base_url, a.model, a.provider)
    out = asyncio.run(run(a.api, a.run_dir, load_prompts(a.prompt_file), a.run_dir.rstrip("/") + ".frames.jsonl",
                          decline_rules=frozenset(a.decline_rule), decline_note=a.decline_note))
    print(json.dumps(out, ensure_ascii=False))

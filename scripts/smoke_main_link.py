#!/usr/bin/env python3
"""Main-link smoke test — run after EVERY dead-code deletion during cleanup.

    .venv/bin/python scripts/smoke_main_link.py

What it does (real process, no network LLM, no touching your real data/):
  1. boots the REAL server (uvicorn + main.py lifespan migration chain) against a
     throwaway ARSLAN_DATA_DIR, with the LLM adapter mocked via scripts/smoke_app.py
  2. hits GET /api/v1/brain/graph until ready  → proves boot + migrations + REST
  3. opens ws://…/ws/arslan/main and sends one user message
  4. asserts the three main-link invariants:
       [routing]  a router_decisions row was persisted for the turn
       [reply]    stream_start → non-empty stream_chunk(s) → stream_end came back
       [persist]  arslan_messages holds the user row + an assistant/spawn_summary row
  5. prints a ✓/✗ report and exits 0 (all pass) / 1 (any fail)
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = str(REPO / ".venv" / "bin" / "python")
BOOT_TIMEOUT_S = 45
TURN_TIMEOUT_S = 60


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_ready(port: int, log_path: Path) -> dict:
    deadline = time.time() + BOOT_TIMEOUT_S
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/brain/graph", timeout=2) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(0.4)
    raise RuntimeError(f"server never became ready ({last_err}); see {log_path}")


async def ws_turn(port: int) -> dict:
    """Send one user message over /ws/arslan/main; collect stream frames."""
    import websockets

    out = {"stream_start": False, "chunks": [], "stream_end": False, "errors": [], "other": []}
    async with websockets.connect(f"ws://127.0.0.1:{port}/ws/arslan/main", open_timeout=10) as ws:
        await ws.send(json.dumps({"type": "user_message", "content": "冒烟测试:请确认主链路正常。"}))
        deadline = time.time() + TURN_TIMEOUT_S
        while time.time() < deadline:
            try:
                frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=deadline - time.time()))
            except (asyncio.TimeoutError, TimeoutError):
                break
            t = frame.get("type")
            if t == "stream_start":
                out["stream_start"] = True
            elif t == "stream_chunk":
                out["chunks"].append(frame.get("content") or "")
            elif t == "stream_end":
                out["stream_end"] = True
                break
            elif t == "error":
                out["errors"].append(frame)
                break
            else:
                out["other"].append(t)  # history / roster_update / fact_saved / …
    return out


def db_state(db_path: Path) -> dict:
    con = sqlite3.connect(db_path)
    try:
        decisions = con.execute("SELECT COUNT(*) FROM router_decisions").fetchone()[0]
        rows = con.execute(
            "SELECT role, COALESCE(display_content, content) FROM arslan_messages ORDER BY id"
        ).fetchall()
    finally:
        con.close()
    return {"router_decisions": decisions, "messages": rows}


def main() -> int:
    port = free_port()
    tmp = Path(tempfile.mkdtemp(prefix="arslan-smoke-"))
    data_dir = tmp / "data"
    data_dir.mkdir()
    env = {
        **os.environ,
        "ARSLAN_DATA_DIR": str(data_dir),
        "ARSLAN_SPAWNS_DIR": str(tmp / "spawns"),
        "ARSLAN_SECRET_KEY": "smoke-secret-key",
        "ARSLAN_API_TOKEN": "",
    }
    log_path = tmp / "server.log"
    checks: list[tuple[str, bool, str]] = []

    with open(log_path, "w") as log:
        proc = subprocess.Popen(
            [PY, "-m", "uvicorn", "scripts.smoke_app:app", "--port", str(port), "--host", "127.0.0.1"],
            cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            graph = wait_ready(port, log_path)
            checks.append(("boot: uvicorn + migration chain + REST up", True,
                           f"/brain/graph → {len(graph.get('nodes', []))} node(s)"))

            turn = asyncio.run(ws_turn(port))
            reply = "".join(turn["chunks"])
            checks.append(("reply: stream_start → chunks → stream_end", bool(
                turn["stream_start"] and reply.strip() and turn["stream_end"] and not turn["errors"]),
                f"reply={reply[:60]!r} errors={turn['errors'] or '—'} other={turn['other']}"))

            db = db_state(data_dir / "arslan.db")
            checks.append(("routing: router_decisions row persisted", db["router_decisions"] >= 1,
                           f"rows={db['router_decisions']}"))
            roles = [r for r, _ in db["messages"]]
            has_user = "user" in roles
            # answer turns persist role="arslan"; routed turns persist "spawn_summary"
            reply_row = next((c for r, c in db["messages"]
                              if r in ("arslan", "assistant", "spawn_summary") and (c or "").strip()), None)
            checks.append(("persist: user + arslan/spawn_summary reply in arslan_messages",
                           bool(has_user and reply_row), f"roles={roles}"))
        except Exception as e:  # noqa: BLE001
            checks.append(("smoke run", False, f"{type(e).__name__}: {e}"))
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    ok = all(passed for _, passed, _ in checks) and checks
    print("\n=== main-link smoke report ===")
    for name, passed, detail in checks:
        print(f"  {'✓' if passed else '✗'} {name}   [{detail}]")
    print(f"=== {'PASS' if ok else 'FAIL'} (server log: {log_path}) ===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

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
  5. (S4.1-C, permanent) asserts the inbound-MCP-server invariant against the SAME
     booted process — the door is fail-closed by default, opens when enabled+tokened,
     serves exactly the 3 read tools, rejects a wrong token, and closes again
     immediately on disable-restore:
       [mcp] disabled → 403
       [mcp] enabled+valid initialize → 200
       [mcp] tools/list → 3 read tools
       [mcp] wrong token → 401
       [mcp] disable-restore → 403
  6. prints a ✓/✗ report and exits 0 (all pass) / 1 (any fail)
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
    """Send one user message over /ws/arslan/main; collect stream frames.

    Connects with the real vite dev origin (`http://localhost:5173`) so the smoke
    exercises the daily dev flow THROUGH the new TrustedHost + WS Origin checks:
    proves a foreign-host reject didn't also kill the legitimate dev browser origin.
    """
    import websockets

    out = {"stream_start": False, "chunks": [], "stream_end": False, "errors": [], "other": []}
    async with websockets.connect(
        f"ws://127.0.0.1:{port}/ws/arslan/main",
        open_timeout=10,
        origin="http://localhost:5173",  # the vite dev origin — must pass the Origin check
    ) as ws:
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


MCP_INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "smoke", "version": "0"}}}
MCP_TOOLS_LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
MCP_HEADERS = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}


def _mcp_post(base: str, path: str, body, headers=None, timeout=10):
    """POST returning (status, bytes); HTTP errors return their status, never raise."""
    import urllib.error

    req = urllib.request.Request(
        base + path, data=json.dumps(body).encode() if body is not None else None,
        method="POST", headers={**MCP_HEADERS, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def check_mcp_server(port: int) -> list[tuple[str, bool, str]]:
    """Permanent MCP-server invariant (S4.1-C): the inbound door is fail-closed by
    default, serves MCP when enabled+tokened (real lifespan drives the session
    manager), and closes again immediately on disable (state restored).

    Sequence: disabled→403 · enable+generate · initialize→200 · tools/list→3 tools ·
    wrong token→401 · disable-restore→403.
    """
    base = f"http://127.0.0.1:{port}"
    checks: list[tuple[str, bool, str]] = []

    # 1. fail-closed by default
    c, _ = _mcp_post(base, "/mcp-server/", MCP_INIT)
    checks.append(("[mcp] disabled → 403", c == 403, f"got {c}"))

    # 2. enable + generate the dedicated token
    req = urllib.request.Request(
        f"{base}/api/v1/settings", data=json.dumps({"mcp_server_enabled": True}).encode(),
        method="PUT", headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).read()
    _, gen_body = _mcp_post(base, "/api/v1/settings/mcp-token/generate", None)
    token = json.loads(gen_body)["token"]
    auth = {"Authorization": f"Bearer {token}"}

    # 3. initialize through the REAL lifespan-driven session manager
    c, _ = _mcp_post(base, "/mcp-server/", MCP_INIT, auth)
    checks.append(("[mcp] enabled+valid initialize → 200", c == 200, f"got {c}"))

    # 4. tools/list exposes exactly the 3 read tools
    c, body = _mcp_post(base, "/mcp-server/", MCP_TOOLS_LIST, auth)
    try:
        names = sorted(t["name"] for t in json.loads(body)["result"]["tools"])
    except Exception:
        names = []
    expected = ["get_run_status", "list_capabilities", "list_spawns"]
    checks.append(("[mcp] tools/list → 3 read tools", c == 200 and names == expected,
                   f"got {c} {names}"))

    # 5. wrong token rejected
    c, _ = _mcp_post(base, "/mcp-server/", MCP_INIT, {"Authorization": "Bearer wrong"})
    checks.append(("[mcp] wrong token → 401", c == 401, f"got {c}"))

    # 6. disable-restore: toggle off + drop the token; the door closes immediately
    req = urllib.request.Request(
        f"{base}/api/v1/settings", data=json.dumps({"mcp_server_enabled": False}).encode(),
        method="PUT", headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).read()
    _mcp_post(base, "/api/v1/settings/mcp-token/disable", None)
    c, _ = _mcp_post(base, "/mcp-server/", MCP_INIT, auth)
    checks.append(("[mcp] disable-restore → 403", c == 403, f"got {c}"))
    return checks


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

            checks.extend(check_mcp_server(port))
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

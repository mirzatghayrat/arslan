#!/usr/bin/env python3
"""Hands v2 P1-2 on a real Mac (spec docs/specs/2026-10-08-0157-hands-v2.md §12 Q1, Q7):

  Q1  Cua Driver run by Arslan Hands holds Hands' Accessibility and Screen Recording,
      and the same binary run on its own (responsibility disclaimed) holds neither.
  Q7  The worker opens no network socket and writes nothing outside Hands' folder.

    ARSLAN_HANDS_APP=".../Arslan Hands.app" python3 scripts/hands_cua_probe.py [--ask]

Needs a development Hands built with HANDS_CUA_DRIVER=1, signed with an Apple
Development identity and HANDS_DEV_UNVERIFIED_PEER=1 (this script is not the
signed backend). With --ask, Hands asks macOS for Accessibility and Screen Recording
(the user allows them; macOS then wants Hands relaunched) and the script stops.
Otherwise it only reads: Calculator's window state (it opens Calculator in the
background if needed, and quits it again only if it opened it). Nothing is clicked
or typed. The disclaimed run may add a "cua-driver" entry to System Settings →
Privacy & Security lists; the script says so.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = Path.home() / "Library" / "Application Support" / "Arslan Hands"


def say(key: str, value) -> None:
    print(json.dumps({key: value}, ensure_ascii=False))


def hands_call(token: str, op: str, args: dict | None = None, timeout: float = 60) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(str(FOLDER / "s.sock"))
        s.sendall((json.dumps({"token": token, "id": f"probe-{uuid.uuid4().hex}", "op": op,
                               "args": args or {}}) + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(1 << 20)
            if not chunk:
                break
            data += chunk
    return json.loads(data)


def start_hands(app: Path) -> str:
    ready = FOLDER / "ready.json"
    if ready.exists():
        pid = json.loads(ready.read_text()).get("pid")
        exe = subprocess.run(["ps", "-o", "comm=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        if exe and str(app) not in exe:
            sys.exit(f"another Arslan Hands is running ({exe}); quit it first")
    subprocess.run(["/usr/bin/open", "-g", "-j", str(app)], check=True)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if ready.exists():
            return json.loads(ready.read_text())["token"]
        time.sleep(0.1)
    sys.exit("Arslan Hands did not start")


def worker_pids() -> list[int]:
    out = subprocess.run(["pgrep", "-f", "cua-driver __private-worker"], capture_output=True, text=True).stdout
    return [int(p) for p in out.split()]


def disclaimed_permissions(binary: Path) -> dict:
    """The same cua-driver, run on its own: responsibility disclaimed, so it is its own
    responsible process and only its own grants (none) apply."""
    work = Path(tempfile.mkdtemp(prefix="hands-cua-disclaim-"))
    subprocess.run(["clang", "-o", str(work / "disclaim"), str(ROOT / "scripts/hands_fixture/disclaim.c")],
                   check=True, capture_output=True)
    home = work / "home"
    home.mkdir()
    generation = uuid.uuid4().hex
    proc = subprocess.Popen([str(work / "disclaim"), str(binary), "__private-worker", "--generation", generation],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                            env={"HOME": str(home), "PATH": "/usr/bin:/bin", "DO_NOT_TRACK": "1"})

    def ask(request_id: int, operation: str, **extra) -> dict:
        proc.stdin.write(json.dumps({"protocol_version": 1, "request_id": request_id, "generation": generation,
                                     "operation": operation, **extra}) + "\n")
        proc.stdin.flush()
        return json.loads(proc.stdout.readline())

    init = {"configured_driver": {"claude_code_compatibility": False, "authorization": {
        "allowed_modes": ["standard"], "compatibility_mode": "standard",
        "compatibility_capability_manifest_path": None, "compatibility_bounded_manifest_path": None,
        "unrestricted_acknowledged": False, "max_session_ttl_seconds": 3600, "max_idle_ttl_seconds": 900}},
        "host_bundle_id": "probe.disclaimed"}
    try:
        ask(0, "initialize", arguments=init)
        answer = ask(1, "call", name="check_permissions", arguments={"prompt": False})
        ask(2, "shutdown")
    finally:
        proc.kill()
        proc.wait()
    s = (answer.get("result") or {}).get("structuredContent") or {}
    return {"accessibility": s.get("accessibility"), "screen_recording": s.get("screen_recording")}


def main() -> int:
    app = Path(os.environ.get("ARSLAN_HANDS_APP", "")).expanduser()
    if not (app / "Contents" / "Info.plist").is_file():
        sys.exit("set ARSLAN_HANDS_APP to the development Arslan Hands.app")
    binary = app.parent / "cua-driver"
    if not binary.is_file():
        sys.exit(f"no cua-driver beside the bundle ({binary}); build with HANDS_CUA_DRIVER=1")
    outside_before = {p: (Path.home() / p).exists() for p in (".cua-driver", ".cua", ".cua-driver-rs")}
    token = start_hands(app)
    status = hands_call(token, "status")
    say("status", {k: status.get(k) for k in ("version", "accessibility", "screen_recording", "peer_check",
                                               "cua_driver", "cua_driver_pinned")})
    if "--ask" in sys.argv:
        say("ask_accessibility", hands_call(token, "request_permission").get("accessibility"))
        say("ask_screen_recording", hands_call(token, "request_permission", {"kind": "screen"}).get("screen_recording"))
        hands_call(token, "quit")
        say("next", "allow both for “Arslan Hands (dev)” in System Settings, then run again without --ask")
        return 0

    perms = hands_call(token, "cua", {"tool": "check_permissions", "args": {"prompt": False}})
    s = ((perms.get("result") or {}).get("structuredContent")) or {}
    say("Q1_through_hands", {"ok": perms.get("ok"), "refused": perms.get("refused"),
                             "accessibility": s.get("accessibility"), "screen_recording": s.get("screen_recording"),
                             "attribution": (s.get("source") or {}).get("attribution"),
                             "host_bundle_id": (s.get("source") or {}).get("host_bundle_id"),
                             "executable": (s.get("source") or {}).get("executable")})

    calculator_was_running = bool(subprocess.run(["pgrep", "-x", "Calculator"], capture_output=True).stdout)
    if not calculator_was_running:
        subprocess.run(["/usr/bin/open", "-g", "-a", "Calculator"], check=True)
        time.sleep(1.5)
    apps = hands_call(token, "cua", {"tool": "list_apps"})
    listed = (apps.get("result") or {}).get("structuredContent", {}).get("apps", [])
    calc = next((a for a in listed if a.get("name") == "Calculator" and a.get("running")), None)
    look = {}
    if calc:
        windows = hands_call(token, "cua", {"tool": "list_windows", "args": {"pid": calc["pid"]}})
        wlist = ((windows.get("result") or {}).get("structuredContent") or {}).get("windows") or []
        if wlist:
            started = time.monotonic()
            state = hands_call(token, "cua", {"tool": "get_window_state", "args": {
                "pid": calc["pid"], "window_id": wlist[0].get("window_id"), "max_image_dimension": 800}})
            ms = round((time.monotonic() - started) * 1000)
            result = state.get("result") or {}
            content = result.get("content") or []
            look = {"ok": state.get("ok"), "refused": state.get("refused"), "ms": ms,
                    "elements": len((result.get("structuredContent") or {}).get("elements") or []),
                    "image": any(c.get("type") == "image" for c in content)}
    say("calculator_window_state_through_hands", look or {"listed": bool(calc)})

    pids = worker_pids()
    sockets = {pid: subprocess.run(["lsof", "-a", "-p", str(pid), "-i"], capture_output=True, text=True).stdout.strip()
               for pid in pids}
    home_files = sorted(str(p.relative_to(FOLDER / "cua-home")) for p in (FOLDER / "cua-home").rglob("*"))
    say("Q7", {"worker_pids": pids, "network_sockets": {str(k): v for k, v in sockets.items()},
               "cua_home_files": home_files,
               "outside_hands_folder_created": [p for p, was in outside_before.items()
                                                if not was and (Path.home() / p).exists()]})
    hands_call(token, "quit")
    if not calculator_was_running:
        subprocess.run(["/usr/bin/osascript", "-e", 'quit app "Calculator"'], capture_output=True)

    say("Q1_on_its_own_disclaimed", disclaimed_permissions(binary))
    say("note", "a 'cua-driver' entry may now be listed (switched off) under Privacy & Security; it can be removed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

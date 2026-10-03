#!/usr/bin/env python3
"""Arslan Hands on a real Mac (0.1.53; task book B4) — run for every release.

Drives the REAL desktop_* tool executors (no model, no cost) through a real
Arslan Hands and agent-desktop, inside a fake background job whose cards this
script answers "Allow" to (and records). It checks what tests cannot:

  1. the fixture app: look, type, click, wait — and nothing takes the focus
  2. refusals: a password field; a never-list app; acting outside a job
  3. a risky button ("Delete") asks every time
  4. Notes: a new note with a title, made in the background
  5. Finder: a file in a work folder is seen in its window (renaming it there is not possible headless)
  6. Stop: a Hands call in flight ends within 1 second
  7. the P3 sandbox: a sandboxed command can neither reach Hands' socket nor read its token
  8. agent-desktop (next to Hands.app), run on its own, holds no Accessibility

Needs: macOS; Accessibility allowed for "Arslan Hands" (D3: the user clicks Allow
once — the script asks macOS to show the prompt if it is missing); Xcode command
line tools. A development Hands is ad-hoc signed (no peer check), so this runs
against the in-process backend:

    ARSLAN_HANDS_APP=".../Arslan Hands.app" .venv/bin/python scripts/hands_smoke.py

Leaves behind one note titled "Arslan Hands smoke …" in Notes (delete it by hand).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ARSLAN_SECRET_KEY", "hands-smoke")
_DATA = tempfile.mkdtemp(prefix="hands-smoke-data-")
os.environ["ARSLAN_DATA_DIR"] = _DATA            # trace and settings stay out of real data

REF = re.compile(r"\[(@s[a-z0-9]+:e\d+)\]")
results: list[tuple[str, bool, str]] = []
cards: list[dict] = []
fronts: list[tuple] = []          # (op, app, {before, after}, focus_restored) for every action


def record(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""), flush=True)
    return ok


def front_app() -> str:
    asn = subprocess.run(["lsappinfo", "front"], capture_output=True, text=True).stdout.strip()
    info = subprocess.run(["lsappinfo", "info", "-only", "bundleid", asn], capture_output=True, text=True).stdout
    match = re.search(r'"([^"]+)"\s*$', info.strip())
    return match.group(1) if match else info.strip()


def refs_on(text: str, needle: str) -> list[str]:
    """Refs on outline lines that contain `needle`."""
    return [m.group(1) for line in text.splitlines() if needle in line for m in [REF.search(line)] if m]


async def find_in(look, app: str, window: str, seen: dict, needle: str, role: str = "") -> str | None:
    """The ref of the first line with `needle` (and `role`), opening folded lists the way the model
    would: a list's rows (Finder's column view) sit below the skeleton, so look with the list's ref."""
    def hit(text: str) -> str | None:
        return next((m.group(1) for line in text.splitlines()
                     if needle in line and line.strip().startswith(role) for m in [REF.search(line)] if m), None)

    text = seen.get("text", "")
    if found := hit(text):
        return found
    for line in text.splitlines():
        if "inside: look with ref" in line and line.strip().split(" ")[0] in ("list", "outline", "table"):
            ref = REF.search(line)
            if ref and (found := hit((await look.execute({"app": app, "window": window, "ref": ref.group(1)})).get("text", ""))):
                return found
    return None


async def main() -> int:
    from server.registry import hands_tools as tools
    from server.services import approvals, background_jobs, hands_client, hands_service
    from server.services import personal_context as pc
    from server.services import terminal_exec

    if sys.platform != "darwin" or not hands_client.available():
        print("macOS and ARSLAN_HANDS_APP pointing at Arslan Hands.app are required", file=sys.stderr)
        return 2

    real_call = hands_client.call

    async def recording_call(op, args=None, **kw):
        reply = await real_call(op, args, **kw)
        if op in ("click", "type", "set_value", "select", "press", "scroll") and isinstance(reply, dict):
            fronts.append((op, (args or {}).get("app"), reply.get("front") or {}, reply.get("focus_restored")))
        return reply
    hands_client.call = recording_call

    async def allow(conversation_id, frame):
        cards.append({"kind": frame.get("kind"), "target": frame.get("target")})
        return True
    approvals.ask = allow

    status = await hands_client.call("status", {})
    if not status.get("accessibility"):
        await hands_client.call("request_permission", {})
        print("Arslan Hands does not have Accessibility yet. macOS has shown its prompt: open System Settings →\n"
              "Privacy & Security → Accessibility, turn on “Arslan Hands”, then run this again.")
        return 3
    record("Arslan Hands runs and holds Accessibility", True, f"pid {status.get('pid')}, peer check {status.get('peer_check')}")

    look, click = tools.DesktopLookExecutor(), tools.DesktopClickExecutor()
    typ, press = tools.DesktopTypeExecutor(), tools.DesktopPressExecutor()
    front = front_app()

    # ── outside a job: acting is refused ──
    with pc.bind(pc.TaskMemoryContext(task_id="smoke", run_id="smoke", conversation_id="smoke")):
        outside = await click.execute({"app": "Finder", "element": "x", "ref": "@sx1y2z3:e1"})
        record("acting outside a background job is refused", outside.get("code") == "act_in_background", str(outside.get("code")))

    token = background_jobs._inside_job.set("smoke-job")
    try:
        with pc.bind(pc.TaskMemoryContext(task_id="smoke", run_id="smoke", conversation_id="smoke")):
            await fixture_checks(look, click, typ, front)
            denied = await look.execute({"app": "System Settings"})
            record("a never-list app is refused", denied.get("code") == "app_denied", str(denied.get("code")))
            await notes_check(look, typ, press, front)
            await finder_check(look, click, typ, press, front)
            await stop_check(look, hands_client, hands_service)
    finally:
        background_jobs._inside_job.reset(token)
        tools.forget_job("smoke-job")

    taken = [f for f in fronts if f[2].get("before") != f[2].get("after")]
    record("no action left another app in front (checked by Hands around each action)", not taken and bool(fronts),
           f"{len(fronts)} actions; {sum(1 for f in fronts if f[3])} times the front was given back; taken: {taken[:3]}")
    await sandbox_check(terminal_exec, hands_client)
    inner_binary_check(hands_client)

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed; cards asked: "
          + ", ".join(f"{c['kind']}:{c['target']}" for c in cards))
    return 1 if failed else 0


async def fixture_checks(look, click, typ, front) -> None:
    from scripts.hands_contract_check import Desk
    work = Path(tempfile.mkdtemp(prefix="hands-smoke-"))
    desk = Desk(Path("/usr/bin/true"), work)            # only builds and launches the fixture
    subprocess.run(["pkill", "-x", "HandsFixture"], capture_output=True)
    subprocess.run(["open", "-g", "-n", str(desk.app)], check=True)
    time.sleep(2)
    try:
        seen = await look.execute({"app": "Hands Fixture"})
        if not record("look at the fixture", seen.get("ok") is True, str(seen.get("error", ""))[:200]):
            return
        text = seen["text"]
        title = (refs_on(text, "“Title”") or [None])[0]
        password = (refs_on(text, "“Password”") or [None])[0]
        save = (refs_on(text, "“Save”") or [None])[0]
        delete = (refs_on(text, "“Delete”") or [None])[0]
        typed = await typ.execute({"app": "Hands Fixture", "element": "Title", "ref": title, "text": "Groceries"})
        record("type into a field (no focus taken)", typed.get("ok") is True, str(typed.get("error", ""))[:200])
        clicked = await click.execute({"app": "Hands Fixture", "element": "Save", "ref": save})
        record("click a button", clicked.get("ok") is True, str(clicked.get("error", ""))[:200])
        waited = await look.execute({"app": "Hands Fixture", "wait_for_text": "saved:Groceries"})
        record("the click had its effect (observed, not trusted)", "saved:Groceries" in waited.get("text", ""))
        pw = await typ.execute({"app": "Hands Fixture", "element": "Password", "ref": password, "text": "hunter2"})
        record("a password field is refused", pw.get("code") == "password_field", str(pw.get("code")))
        before = sum(c["kind"] == "desktop_risky" for c in cards)
        for _ in range(2):
            await click.execute({"app": "Hands Fixture", "element": "Tidy", "ref": delete})
        record("a Delete button asks every time", sum(c["kind"] == "desktop_risky" for c in cards) - before == 2)
        print(f"  info  front app after the fixture step: {front_app()} (was {front})")
    finally:
        subprocess.run(["pkill", "-x", "HandsFixture"], capture_output=True)


async def notes_check(look, typ, press, front) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    subprocess.run(["open", "-g", "-a", "Notes"], check=False)
    time.sleep(2)
    windows = subprocess.run(["osascript", "-e", 'tell application "System Events" to tell process "Notes" '
                              'to count windows'], capture_output=True, text=True).stdout.strip()
    if windows in ("", "0"):
        record("Notes: a Notes window is open on this desktop (precondition)", False,
               "open a Notes window on this desktop and run again")
        return
    made = await press.execute({"app": "Notes", "keys": "cmd+n"})
    if not record("Notes: New Note through the menu shortcut", made.get("ok") is True, str(made.get("error", ""))[:300]):
        return
    # The outline of the focused window (a whole-window find times out on Notes'
    # main window, measured); the new note's body is the focused, empty text field.
    found: dict = {}
    for _ in range(3):
        time.sleep(1)
        found = await look.execute({"app": "Notes"})
        if found.get("ok"):
            break
    lines = found.get("text", "").splitlines()
    fields = [line for line in lines if line.strip().startswith("textfield")]
    body = None
    for line in fields:
        m = REF.search(line)
        if m and "focused" in line and "=" not in line:
            body = m.group(1)
    if not record("Notes: the new note's body is found", body is not None,
                  f"{len(fields)} text fields; {found.get('error', '')}"[:300]):
        return
    note = f"Arslan Hands smoke {stamp}\nMade in the background, without taking focus."
    typed = await typ.execute({"app": "Notes", "element": "note body", "ref": body, "text": note})
    record("Notes: the note gets its title and text", typed.get("ok") is True, str(typed.get("error", ""))[:300])
    check = await look.execute({"app": "Notes"})
    record("Notes: the note is there (observed)",
           any(line.strip().startswith("textfield") and f"Arslan Hands smoke {stamp}" in line
               for line in check.get("text", "").splitlines()), check.get("error", "")[:200])
    print(f"  info  front app after the Notes step: {front_app()} (was {front})")


async def finder_check(look, click, typ, press, front) -> None:
    folder = Path(tempfile.mkdtemp(prefix="Hands smoke ", dir=Path.home() / "Documents"))
    (folder / "draft.txt").write_text("hello")
    subprocess.run(["open", "-g", str(folder)], check=False)
    time.sleep(2)
    seen = await look.execute({"app": "Finder", "window": folder.name})     # its outline (a find can time out)
    item = await find_in(look, "Finder", folder.name, seen, "draft.txt")
    if not record("Finder: the file is seen in its window", item is not None, seen.get("error", seen.get("text", ""))[:300]):
        close_finder_window(folder.name)
        (folder / "draft.txt").unlink(missing_ok=True)
        folder.rmdir()
        return
    # Renaming through Finder is not something Hands can do in the background (spec §7, measured): a click
    # on a file row is AXOpen, keys posted to a background Finder are ignored, and setting the name field's
    # value changes the accessibility value without committing. The model is told to use run_command (mv).
    print("  info  Finder rename in the background: not possible headless (spec §7) — the model uses mv")
    print(f"  info  front app after the Finder step: {front_app()} (was {front})")
    close_finder_window(folder.name)
    for item in folder.iterdir():
        item.unlink()
    folder.rmdir()


def close_finder_window(name: str) -> None:
    """Teardown only: close the Finder window this script opened."""
    subprocess.run(["osascript", "-e", f'tell application "Finder" to close (every Finder window whose name is "{name}")'],
                   capture_output=True)


async def stop_check(look, hands_client, hands_service) -> None:
    started = time.monotonic()
    task = asyncio.create_task(look.execute({"app": "Finder", "wait_for_text": "zz-this-text-never-appears"}))
    await asyncio.sleep(1.5)
    stop_at = time.monotonic()
    hands_service.stop_running_jobs()
    await hands_client.call("stop", {}, start=False)
    await task
    record("Stop ends a Hands call in flight within 1 s", time.monotonic() - stop_at < 1.0,
           f"{time.monotonic() - stop_at:.2f}s after Stop ({time.monotonic() - started:.1f}s in all)")


async def sandbox_check(terminal_exec, hands_client) -> None:
    folder = hands_client.folder()
    ws = Path(tempfile.mkdtemp(prefix="hands-smoke-ws-"))
    probe = (f"python3 -c \"import socket; s=socket.socket(socket.AF_UNIX); s.connect('{folder}/s.sock'); "
             "print('CONNECTED')\"")
    out = await terminal_exec.run(probe, cwd=ws, sandbox=True)
    record("a sandboxed command cannot reach Hands' socket", "CONNECTED" not in (out.get("stdout") or ""),
           (out.get("stderr") or "")[-120:])
    token = await terminal_exec.run(f"cat '{folder}/ready.json'", cwd=ws, sandbox=True)
    record("a sandboxed command cannot read Hands' token", "token" not in (token.get("stdout") or ""))


def inner_binary_check(hands_client) -> None:
    inner = hands_client.app_path().parent / "agent-desktop"
    work = Path(tempfile.mkdtemp(prefix="hands-smoke-disclaim-"))
    subprocess.run(["clang", "-o", str(work / "disclaim"), str(ROOT / "scripts/hands_fixture/disclaim.c")], check=True)
    env = {"HOME": str(work), "PATH": "/usr/bin:/bin", "AGENT_DESKTOP_HOME": str(work / "ad")}
    (work / "ad").mkdir(mode=0o700)
    out = subprocess.run([str(work / "disclaim"), str(inner), "permissions"], capture_output=True, text=True, env=env)
    try:
        state = json.loads(out.stdout)["data"]["accessibility"]["state"]
    except (ValueError, KeyError, TypeError):
        state = f"unreadable: {out.stdout[:120]}"
    record("agent-desktop, run on its own, holds no Accessibility", state == "denied",
           f"state {state} — if granted, macOS lends it a grant and anything could drive apps with it")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

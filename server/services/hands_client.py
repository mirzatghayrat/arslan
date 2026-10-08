"""Talking to Arslan Hands, the helper app that holds Accessibility (0.1.53).

Hands is a separate app, started through LaunchServices so that it is its own
responsible process: macOS checks Accessibility against the responsible process
and every child inherits it, so the grant must never sit on anything run_command
descends from (measured; docs/specs/2026-10-03-0153-hands-agent-desktop.md §0).

Hands takes no arguments and finds its folder itself, from the account's home
directory (getpwuid, never $HOME: `open --env` could point it elsewhere). This
module derives the same folder the same way. The folder is in the P3 sandbox's
protected paths, files and sockets alike, so a sandboxed command can neither
read the token nor connect.

Protocol: one JSON line `{token, id, op, args}` per connection, one JSON line
back. Hands' own refusals come as `{"ok": false, "refused": {code, message}}`;
otherwise `{"ok": true, "envelope": <agent-desktop's envelope>, ...}`. Every reply
carries Hands' pid. Requests are run at most once: Hands keeps the answer to each
id for ten minutes, answers a repeated id from memory, and `answer_of {id, wait_ms}`
returns `done` (with the answer), `running` or `unknown_id` (spec 2026-10-08-0157 §1).
"""
from __future__ import annotations

import asyncio
import json
import os
import pwd
import sys
import time
import uuid
from pathlib import Path

FOLDER_NAME = "Arslan Hands"
APP_NAME = "Arslan Hands.app"
START_TIMEOUT_S = 10.0
MAX_REPLY = 8 * 1024 * 1024


class HandsUnavailable(RuntimeError):
    """Hands is not installed here, or did not start."""


def folder() -> Path:
    """`~/Library/Application Support/Arslan Hands`, from the account database."""
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / "Library" / "Application Support" / FOLDER_NAME


def app_path() -> Path | None:
    """Arslan Hands.app: next to the packaged sidecar (Contents/Resources/hands),
    or `ARSLAN_HANDS_APP` in development. None when there is none."""
    if getattr(sys, "frozen", False):
        candidate = Path(sys.executable).resolve().parent.parent / "hands" / APP_NAME
    else:
        configured = os.environ.get("ARSLAN_HANDS_APP", "").strip()
        candidate = Path(configured).expanduser() if configured else None
    return candidate if candidate is not None and (candidate / "Contents" / "Info.plist").is_file() else None


def available() -> bool:
    return sys.platform == "darwin" and app_path() is not None


def _ready() -> dict | None:
    try:
        doc = json.loads((folder() / "ready.json").read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("token"), str) or not isinstance(doc.get("pid"), int):
        return None
    try:
        os.kill(doc["pid"], 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        pass
    return doc


async def _launch() -> dict:
    app = app_path()
    if app is None:
        raise HandsUnavailable("Arslan Hands is not installed with this copy of Arslan")
    # -g: do not bring it forward; -j: launch hidden. LaunchServices makes it its
    # own responsible process (spec §0, M5) — never spawn it as our child.
    process = await asyncio.create_subprocess_exec("/usr/bin/open", "-g", "-j", str(app),
                                                   stdout=asyncio.subprocess.DEVNULL,
                                                   stderr=asyncio.subprocess.PIPE)
    _, err = await process.communicate()
    if process.returncode != 0:
        raise HandsUnavailable(f"could not start Arslan Hands: {err.decode(errors='replace')[:200]}")
    deadline = time.monotonic() + START_TIMEOUT_S
    while time.monotonic() < deadline:
        doc = _ready()
        if doc is not None:
            return doc
        await asyncio.sleep(0.1)
    raise HandsUnavailable("Arslan Hands did not start in time")


class _NotSent(Exception):
    """The request never reached Hands (no socket, refused connection): resending is safe."""


class _Lost(Exception):
    """The request was written but no usable reply came back: it may have run."""


async def _exchange(doc: dict, request: dict, timeout: float) -> dict:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(str(folder() / "s.sock"),
                                                                             limit=MAX_REPLY), 5)
    except (OSError, asyncio.TimeoutError) as exc:
        raise _NotSent(str(exc)) from None
    try:
        writer.write((json.dumps({**request, "token": doc["token"]}) + "\n").encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout)
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, ValueError) as exc:
        raise _Lost(str(exc) or type(exc).__name__) from None
    finally:
        writer.close()
    if not line:
        raise _Lost("Arslan Hands closed the connection")
    try:
        reply = json.loads(line)
    except ValueError:
        raise _Lost("not a reply") from None
    if not isinstance(reply, dict):
        raise _Lost("not a reply")
    return reply


# P0 D1 (spec 2026-10-08-0157 §1): a request is sent at most once. Python ≥ 3.11's
# TimeoutError is an OSError, so the old "resend on any OSError" ran an action again
# whenever its reply was late (Hands serves one request at a time).
_RESEND = object()


def _unknown(why: str) -> dict:
    return {"ok": False, "refused": {"code": "unknown", "message": why}}


async def _recover(doc: dict, request: dict, timeout: float):
    """The reply to `request` was lost. Ask the same Hands for it by id; if that
    Hands is gone, nobody can say whether it ran."""
    now = _ready()
    if now is None or now.get("pid") != doc.get("pid"):
        return _unknown("Arslan Hands restarted while this was running")
    query = {"id": f"answer_of-{uuid.uuid4().hex}", "op": "answer_of",
             "args": {"id": request["id"], "wait_ms": int(max(timeout, 1.0) * 1000)}}
    try:
        reply = await _exchange(now, query, max(timeout, 1.0) + 10)
    except (_NotSent, _Lost):
        return _unknown("Arslan Hands stopped answering")
    if reply.get("pid") not in (None, doc.get("pid")):
        return _unknown("Arslan Hands restarted while this was running")
    state = reply.get("state")
    if state == "done" and isinstance(reply.get("answer"), dict):
        return reply["answer"]
    if state == "unknown_id":
        return _RESEND                    # this Hands never received it
    return _unknown("Arslan Hands is still busy with it")


async def call(op: str, args: dict | None = None, *, timeout: float = 60.0, start: bool = True) -> dict:
    """One request, run at most once. Starts Hands if needed (unless `start=False`);
    resends only what provably never ran: a connection that never opened, a stale
    token, or an id the same Hands says it never received. A lost reply is fetched
    by id; when that is impossible the answer is `unknown` ("look before anything")."""
    if sys.platform != "darwin":
        raise HandsUnavailable("Arslan Hands runs on macOS only")
    request = {"id": f"{op}-{uuid.uuid4().hex}", "op": op, "args": args or {}}
    doc = _ready()
    if doc is None:
        if not start:
            raise HandsUnavailable("Arslan Hands is not running")
        doc = await _launch()
    for attempt in range(2):
        try:
            reply = await _exchange(doc, request, timeout)
        except _NotSent:
            if attempt or not start:
                raise HandsUnavailable("could not reach Arslan Hands") from None
            doc = _ready() or await _launch()
            continue
        except _Lost:
            reply = await _recover(doc, request, timeout)
            if reply is _RESEND:
                if attempt:
                    return _unknown("Arslan Hands did not receive it twice")
                continue
            return reply
        if (reply.get("refused") or {}).get("code") == "bad_token" and not attempt:
            doc = _ready() or (await _launch() if start else doc)
            continue
        return reply
    raise HandsUnavailable("could not reach Arslan Hands")


def running() -> bool:
    return _ready() is not None

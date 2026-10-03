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
otherwise `{"ok": true, "envelope": <agent-desktop's envelope>, ...}`.
"""
from __future__ import annotations

import asyncio
import json
import os
import pwd
import sys
import time
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


async def _exchange(doc: dict, request: dict, timeout: float) -> dict:
    reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(str(folder() / "s.sock"),
                                                                         limit=MAX_REPLY), 5)
    try:
        writer.write((json.dumps({**request, "token": doc["token"]}) + "\n").encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout)
    finally:
        writer.close()
    if not line:
        raise ConnectionError("Arslan Hands closed the connection")
    reply = json.loads(line)
    if not isinstance(reply, dict):
        raise ValueError("not a reply")
    return reply


async def call(op: str, args: dict | None = None, *, timeout: float = 60.0, start: bool = True) -> dict:
    """One request. Starts Hands if needed (unless `start=False`); if Hands was
    restarted under us (new token, new socket), retries once with the new one."""
    if sys.platform != "darwin":
        raise HandsUnavailable("Arslan Hands runs on macOS only")
    request = {"id": f"{op}-{time.monotonic_ns()}", "op": op, "args": args or {}}
    doc = _ready()
    if doc is None:
        if not start:
            raise HandsUnavailable("Arslan Hands is not running")
        doc = await _launch()
    for attempt in range(2):
        try:
            reply = await _exchange(doc, request, timeout)
        except (OSError, ConnectionError, ValueError, asyncio.IncompleteReadError):
            if attempt or not start:
                raise HandsUnavailable("could not reach Arslan Hands") from None
            doc = _ready() or await _launch()
            continue
        if (reply.get("refused") or {}).get("code") == "bad_token" and not attempt:
            doc = _ready() or (await _launch() if start else doc)
            continue
        return reply
    raise HandsUnavailable("could not reach Arslan Hands")


def running() -> bool:
    return _ready() is not None

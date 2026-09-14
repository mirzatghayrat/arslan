"""Ephemeral user-controlled reading sessions, separate from static previews.

Bounded navigation, link following and scrolling only. No arbitrary clicks,
typing, logins, uploads, downloads, JS evaluation or credential-backed actions.
The trusted Chromium parent uses its renderer sandbox and a public-IP proxy;
this is not a kernel jail for the parent and not the W11 credential broker.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import signal
import tempfile
import time
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal

from server.mcp import spawn_env
from server.services import managed_browser
from server.services.browser_proxy import PublicTunnel, validate_url


class ReaderError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ReaderAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["navigate", "link", "scroll", "back", "forward", "refresh"]
    url: str | None = Field(default=None, max_length=4000)
    link_id: str | None = Field(default=None, pattern=r"^link-[0-9]{1,3}$")
    revision: int | None = Field(default=None, ge=1, strict=True)
    direction: Literal[-1, 1] | None = None

    @model_validator(mode="after")
    def scoped_arguments(self):
        required = {"navigate": {"url"}, "link": {"link_id", "revision"}, "scroll": {"direction"}}
        expected = required.get(self.action, set())
        present = {key for key in ("url", "link_id", "revision", "direction") if getattr(self, key) is not None}
        if present != expected:
            raise ValueError("browser.invalid_request")
        if self.direction is not None and type(self.direction) is not int:
            raise ValueError("browser.invalid_request")
        if self.url is not None:
            validate_url(self.url)
        return self


class ReaderSession:
    def __init__(self, conversation_id: str, task_id: str | None, *, owner_id="local"):
        self.id = str(uuid4())
        self.owner_id, self.conversation_id, self.task_id = owner_id, conversation_id, task_id
        self.created_at = time.monotonic()
        self.operations = 0
        self.lock = asyncio.Lock()
        self.close_lock = asyncio.Lock()
        self.process = None
        self.proxy = None
        self.temp = None
        self.closed = False
        self.in_flight: asyncio.Task | None = None
        self.expiry_task: asyncio.Task | None = None

    async def start(self):
        state = managed_browser.status()
        if not state["ready"]:
            raise ReaderError("browser." + state["reason"])
        root = managed_browser.runtime_root()
        executable = managed_browser._browser_executable(root)
        self.temp = tempfile.TemporaryDirectory(prefix="arslan-reader-", dir="/tmp")
        self.proxy = PublicTunnel(byte_limit=100 * 1024 * 1024, connection_limit=500)
        try:
            await self.proxy.__aenter__()
            runner = Path(__file__).resolve().parent.parent / "resources/browser_reader.cjs"
            self.process = await asyncio.create_subprocess_exec(
                spawn_env.resolve_command("node"), str(runner), str(root / "node_modules/playwright"), str(executable),
                f"http://127.0.0.1:{self.proxy.port}", cwd=self.temp.name,
                env={"PATH": "/usr/bin:/bin", "HOME": self.temp.name, "TMPDIR": self.temp.name},
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                limit=4_000_000, start_new_session=True)
            line = await asyncio.wait_for(self.process.stdout.readline(), 20)
            if json.loads(line) != {"ready": True}:
                raise ReaderError("browser.runtime_failed")
            async def expire():
                await asyncio.sleep(900)
                await self.close()
            self.expiry_task = asyncio.create_task(expire())
        except BaseException:
            await self.close()
            raise

    async def act(self, action: ReaderAction) -> dict:
        async with self.lock:
            if self.closed or self.process is None or self.process.returncode is not None:
                raise ReaderError("browser.session_closed")
            if self.operations >= 100 or time.monotonic() - self.created_at > 900:
                await self.close()
                raise ReaderError("browser.session_expired")
            self.operations += 1
            self.in_flight = asyncio.current_task()
            try:
                self.process.stdin.write(action.model_dump_json(exclude_none=True).encode() + b"\n")
                await self.process.stdin.drain()
                output = await asyncio.wait_for(self.process.stdout.readline(), 25)
                if not output or len(output) > 4_000_000:
                    raise ReaderError("browser.runtime_failed")
                result = json.loads(output)
                if not isinstance(result, dict):
                    raise ReaderError("browser.runtime_failed")
                if result.get("ok") is not True:
                    code = result.get("code")
                    raise ReaderError(code if code in {"browser.stale_view", "browser.invalid_url", "browser.history_unavailable",
                        "browser.frame_too_large", "browser.navigation_failed"} else "browser.runtime_failed")
                if self.closed or self.proxy is None:
                    raise ReaderError("browser.session_closed")
                return {**result, "session_id": self.id, "conversation_id": self.conversation_id,
                        "task_id": self.task_id, "blocked_connections": self.proxy.blocked}
            except (TimeoutError, OSError, ValueError, asyncio.CancelledError) as exc:
                # An out-of-sync protocol must never apply a later command to an old frame.
                if not isinstance(exc, ReaderError):
                    await self.close()
                    if isinstance(exc, asyncio.CancelledError):
                        raise
                    raise ReaderError("browser.runtime_failed") from None
                raise
            finally:
                self.in_flight = None

    async def close(self):
        async with self.close_lock:
            self.closed = True
            if self.expiry_task is not None and self.expiry_task is not asyncio.current_task():
                self.expiry_task.cancel()
            if self.process is not None and self.process.returncode is None:
                descendants = await _descendants(self.process.pid)
                try:
                    self.process.send_signal(signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(self.process.wait(), 3)
                except TimeoutError:
                    # Playwright launches Chromium in its own process group.
                    # Kill the captured descendants too, not merely Node's group.
                    for pid in reversed(descendants):
                        try:
                            os.kill(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    try:
                        os.killpg(self.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await self.process.wait()
            if self.proxy is not None:
                await self.proxy.__aexit__(None, None, None)
                self.proxy = None
            if self.temp is not None:
                self.temp.cleanup()
                self.temp = None


sessions: dict[str, ReaderSession] = {}
_creation_lock = asyncio.Lock()


async def _descendants(parent: int) -> list[int]:
    """PID/PPID only: no commands, arguments, environment or user content."""
    process = None
    try:
        process = await asyncio.create_subprocess_exec("/bin/ps", "-axo", "pid=,ppid=",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        output, _ = await asyncio.wait_for(process.communicate(), 2)
        pairs = [tuple(map(int, line.split())) for line in output.splitlines() if len(line.split()) == 2]
        found, frontier = [], {parent}
        for _ in range(20):
            children = {pid for pid, ppid in pairs if ppid in frontier and pid not in found and pid != parent}
            if not children:
                break
            found.extend(children)
            frontier = children
        return found
    except (OSError, ValueError, TimeoutError):
        return []
    finally:
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()


async def create(conversation_id: str, task_id: str | None) -> ReaderSession:
    async with _creation_lock:
        await prune()
        if len(sessions) >= 4:
            raise ReaderError("browser.busy")
        session = ReaderSession(conversation_id, task_id)
        await session.start()
        sessions[session.id] = session
        return session


async def prune():
    for identity, session in list(sessions.items()):
        if session.closed or time.monotonic() - session.created_at > 900:
            await session.close()
            sessions.pop(identity, None)


async def shutdown():
    for session in list(sessions.values()):
        await session.close()
    sessions.clear()


async def cancel_task(task_id: str):
    for identity, session in list(sessions.items()):
        if session.task_id == task_id:
            await session.close()
            sessions.pop(identity, None)

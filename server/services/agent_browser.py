"""0.1.45 Arslan's own browser: a visible Chromium the user can watch.

Built on the same managed runtime as previews (@playwright/mcp + a managed
Chromium, set up once in Settings > Advanced) and the same public-only proxy
(no localhost / LAN). Differences from the preview, on purpose:

- headed and persistent: the window is visible and keeps its own profile
  (`<data>/agent_browser/profile`), so the USER logs in once, themselves, and
  later work can use that session. Arslan never types a password.
- page scripts run (real sites need them); downloads stay off.
- only a fixed set of Playwright tools is ever called — no script evaluation,
  cookies/storage, network routing, uploads or tracing.

One dedicated task owns the MCP connection (the SDK's AnyIO scopes must be
entered and left in the same task); calls are queued to it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import tempfile
from pathlib import Path

from server import config
from server.mcp import spawn_env
from server.services import managed_browser
from server.services.browser_proxy import PublicTunnel, validate_url

logger = logging.getLogger(__name__)

# Our tool name -> the Playwright MCP tool it calls. Nothing else is reachable.
PLAYWRIGHT_TOOLS = {
    "open": "browser_navigate", "look": "browser_snapshot", "back": "browser_navigate_back",
    "click": "browser_click", "type": "browser_type", "select": "browser_select_option",
    "press": "browser_press_key",
}
TEXT_LIMIT = 16_000
_PAGE_URL = re.compile(r"Page URL:\s*(\S+)")


class BrowserUnavailable(RuntimeError):
    pass


def profile_dir() -> Path:
    return config.data_dir() / "agent_browser" / "profile"


class _Worker:
    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.task: asyncio.Task | None = None
        self.url: str | None = None

    async def call(self, tool: str, arguments: dict) -> str:
        if self.task is None or self.task.done():
            ready = asyncio.get_running_loop().create_future()
            self.task = asyncio.create_task(self._run(ready))
            await ready                               # raises if the browser cannot start
        future = asyncio.get_running_loop().create_future()
        await self.queue.put((tool, arguments, future))
        return await future

    async def _run(self, ready: asyncio.Future) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        try:
            state = managed_browser.status()
            if not state["ready"]:
                raise BrowserUnavailable(state["reason"] or "setup_required")
            root = managed_browser.runtime_root()
            chromium = json.loads((root / ".ready.json").read_text())["browser"]
            profile = profile_dir()
            profile.mkdir(parents=True, exist_ok=True)
            output = profile.parent / "output"
            output.mkdir(exist_ok=True)
            cfg = profile.parent / "browser.json"
            cfg.write_text(json.dumps({"browser": {"launchOptions": {"args": [
                "--disable-quic", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"]},
                "contextOptions": {"acceptDownloads": False, "ignoreHTTPSErrors": False}}}))
            async with PublicTunnel(byte_limit=2 * 1024 ** 3, connection_limit=100_000) as proxy:
                args = [spawn_env.resolve_command("node"), str(root / "node_modules/@playwright/mcp/cli.js"),
                        "--sandbox", "--executable-path", chromium, "--user-data-dir", str(profile),
                        "--config", str(cfg), "--proxy-server", f"http://127.0.0.1:{proxy.port}",
                        "--proxy-bypass", "<-loopback>", "--output-dir", str(output),
                        "--image-responses", "omit", "--viewport-size", "1280x860",
                        "--timeout-navigation", "30000", "--timeout-action", "8000"]
                # Unix socket paths are limited (~104 bytes on macOS); the data dir is
                # too deep, so sockets and temp files go to a short /tmp directory.
                short = tempfile.mkdtemp(prefix="arslan-ab-", dir="/tmp")
                params = StdioServerParameters(command=args[0], args=args[1:], cwd=str(profile.parent),
                    env={"PATH": "/usr/bin:/bin", "HOME": str(profile.parent), "TMPDIR": short,
                         "PWTEST_SOCKETS_DIR": short, "PLAYWRIGHT_BROWSERS_PATH": str(root / "browsers")})
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as client:
                        await client.initialize()
                        ready.set_result(True)
                        while True:
                            tool, arguments, future = await self.queue.get()
                            try:
                                result = await client.call_tool(tool, arguments)
                                text = " ".join(getattr(part, "text", "") for part in result.content)
                                if result.isError:
                                    future.set_exception(RuntimeError(text[:1500] or "browser action failed"))
                                else:
                                    found = _PAGE_URL.search(text)
                                    if found:
                                        self.url = found.group(1)
                                    future.set_result(text)
                            except Exception as exc:  # noqa: BLE001 — one failed call never kills the browser
                                if not future.done():
                                    future.set_exception(exc)
        except Exception as exc:  # noqa: BLE001
            if not ready.done():
                ready.set_exception(exc if isinstance(exc, BrowserUnavailable) else BrowserUnavailable(str(exc)))
            logger.warning("agent browser stopped: %s", type(exc).__name__)

    async def close(self) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self.task, self.url = None, None


_worker = _Worker()


def available() -> bool:
    """Offered when ready, and also when it only needs the one-time setup: the
    tool then says where to set it up, instead of Arslan silently lacking a browser."""
    state = managed_browser.status()
    return state["ready"] or state["reason"] == "setup_required"


def current_url() -> str | None:
    return _worker.url


async def run(action: str, arguments: dict) -> str:
    """Call one allowed Playwright tool, then return the page as the model needs
    it: an inline accessibility snapshot with element refs.

    Playwright MCP 0.0.80 (probed in the real runtime, 2026-09-30): navigation
    and actions reply with a LINK to a snapshot file, and element arguments are
    named `target`, not `ref`. A second `browser_snapshot` call (no filename)
    returns the snapshot inline."""
    tool = PLAYWRIGHT_TOOLS[action]
    args = dict(arguments)
    if action == "open":
        validate_url(args["url"])
    if "ref" in args:
        args["target"] = args.pop("ref")
    if action == "press":
        args = {"key": args.get("key", "")}
    reply = "" if action == "look" else await _worker.call(tool, args)
    snapshot = await _worker.call(PLAYWRIGHT_TOOLS["look"], {})
    note = ""
    if reply and "### Error" in reply:
        note = reply[:1500] + "\n"
    return (note + snapshot)[:TEXT_LIMIT]


async def shutdown() -> None:
    await _worker.close()

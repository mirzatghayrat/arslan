"""Explicitly provisioned, preview-only browser sessions with Run-owned output.

No logged-in profiles, extension attachment, clicks, form entry, uploads or arbitrary
JavaScript tools are exposed. Page scripts are disabled; static resources load.
Node/MCP remains trusted host code; this is not a general MCP filesystem sandbox.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import tempfile

from server import config
from server.mcp import spawn_env
from server.services import artifact_store, execution_context
from server.services.browser_proxy import PublicTunnel, validate_url

VERSION = "0.0.80"
_setup_lock = asyncio.Lock()


def manifests() -> Path:
    return Path(__file__).resolve().parent.parent / "resources" / "browser_runtime"


def runtime_root() -> Path:
    return config.data_dir() / "browser_runtime" / VERSION


def _digest() -> str:
    return hashlib.sha256((manifests() / "package-lock.json").read_bytes()).hexdigest()


def _browser_executable(root: Path) -> Path:
    metadata = json.loads((root / "node_modules/playwright-core/browsers.json").read_text())
    revision = next(item["revision"] for item in metadata["browsers"]
                    if item["name"] == "chromium-headless-shell")
    matches = list((root / "browsers" / f"chromium_headless_shell-{revision}").rglob("chrome-headless-shell"))
    if len(matches) != 1 or not matches[0].is_file():
        raise ValueError("Pinned headless browser is missing")
    return matches[0]


def status() -> dict:
    if sys.platform != "darwin":
        return {"ready": False, "reason": "macos_required", "version": VERSION}
    try:
        spawn_env.resolve_command("node")
        spawn_env.resolve_command("npm")
    except FileNotFoundError:
        return {"ready": False, "reason": "node_required", "version": VERSION}
    root = runtime_root()
    try:
        ready = json.loads((root / ".ready.json").read_text())
        good = (ready["lock_sha256"] == _digest() and Path(ready["browser"]).is_file()
                and Path(ready["browser"]) == _browser_executable(root)
                and (root / "node_modules/@playwright/mcp/cli.js").is_file())
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        good = False
    return {"ready": good, "reason": None if good else "setup_required", "version": VERSION}


async def _command(args: list[str], *, cwd: Path, env: dict, timeout: float) -> str:
    process = await asyncio.create_subprocess_exec(
        *args, cwd=cwd, env=env, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT, start_new_session=True)
    chunks = bytearray()

    async def drain():
        while block := await process.stdout.read(16384):
            chunks.extend(block)
            if len(chunks) > 20000:
                del chunks[:-20000]
        await process.wait()

    try:
        async with asyncio.timeout(timeout):
            await drain()
    finally:
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()
    text = chunks.decode("utf-8", errors="replace")
    if process.returncode:
        raise RuntimeError("Browser setup failed: " + text[-2000:])
    return text.strip()


async def setup() -> dict:
    """User-click-only public download, exact lockfile + pinned Chromium revision."""
    async with _setup_lock:
        state = status()
        if state["ready"]:
            return state
        if state["reason"] != "setup_required":
            raise ValueError(state["reason"])
        root = runtime_root()
        root.mkdir(parents=True, exist_ok=True)
        for name in ("package.json", "package-lock.json"):
            shutil.copyfile(manifests() / name, root / name)
        with tempfile.TemporaryDirectory(prefix="arslan-browser-setup-") as temp:
            env = {"PATH": spawn_env.merged_path(), "HOME": temp,
                   "PLAYWRIGHT_BROWSERS_PATH": str(root / "browsers"),
                   "npm_config_userconfig": str(Path(temp) / ".npmrc"),
                   "npm_config_cache": str(root / "npm-cache")}
            await _command([spawn_env.resolve_command("npm"), "ci", "--ignore-scripts",
                            "--no-audit", "--no-fund", "--registry=https://registry.npmjs.org"],
                           cwd=root, env=env, timeout=180)
            node = spawn_env.resolve_command("node")
            await _command([node, str(root / "node_modules/playwright/cli.js"),
                            "install", "chromium", "--only-shell"], cwd=root, env=env, timeout=240)
            # Headless Shell has no desktop profile-singleton IPC and needs no
            # exception for sockets in the user's shared macOS temp directory.
            browser = str(_browser_executable(root))
        if not Path(browser).is_file() or not Path(browser).is_relative_to(root):
            raise RuntimeError("Browser installation did not produce the pinned executable")
        (root / ".ready.json").write_text(json.dumps({"browser": browser, "lock_sha256": _digest()}))
        return status()


async def preview(url: str) -> dict:
    try:
        return await _preview(url)
    except ExceptionGroup as group:
        # AnyIO wraps MCP failures. Keep the actionable leaf on the Run.
        cause = group
        while isinstance(cause, BaseExceptionGroup):
            cause = cause.exceptions[0]
        raise RuntimeError(str(cause)[:1500]) from group


async def _preview(url: str) -> dict:
    validate_url(url)
    state = status()
    if not state["ready"]:
        raise ValueError(state["reason"])
    root = runtime_root()
    browser = json.loads((root / ".ready.json").read_text())["browser"]
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async with asyncio.timeout(45):
        # Unix-domain socket paths have a small platform limit; macOS's default
        # per-user temp prefix plus Chromium's singleton suffix can exceed it.
        with tempfile.TemporaryDirectory(prefix="arslan-b-", dir="/tmp") as temp:
            work = Path(temp)
            output = work / "output"
            output.mkdir()
            cfg = work / "browser.json"
            cfg.write_text(json.dumps({"browser": {"launchOptions": {"args": [
                "--disable-quic", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"
            ]}, "contextOptions": {
                "acceptDownloads": False, "ignoreHTTPSErrors": False,
                "javaScriptEnabled": False, "serviceWorkers": "block", "permissions": []}}}))
            async with PublicTunnel() as proxy:
                # macOS rejects Chromium's nested sandbox initialization under sandbox-exec.
                # Keep Chromium's renderer sandbox ON, do not fall back to --no-sandbox.
                # This proxy policy is not a kernel jail for the trusted browser parent.
                args = [spawn_env.resolve_command("node"),
                        str(root / "node_modules/@playwright/mcp/cli.js"),
                        "--isolated", "--sandbox", "--headless", "--block-service-workers",
                        "--executable-path", browser, "--config", str(cfg),
                        "--proxy-server", f"http://127.0.0.1:{proxy.port}",
                        "--proxy-bypass", "<-loopback>", "--output-dir", str(output),
                        "--output-max-size", "10000000", "--image-responses", "omit",
                        "--viewport-size", "1280x800",
                        "--timeout-navigation", "20000", "--timeout-action", "5000"]
                params = StdioServerParameters(command=args[0], args=args[1:], cwd=str(work),
                    env={"PATH": "/usr/bin:/bin", "HOME": temp, "TMPDIR": temp,
                         "PLAYWRIGHT_BROWSERS_PATH": str(root / "browsers")})
                # Enter/exit the SDK's AnyIO scopes in the SAME task, never a cached cross-task stack.
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as client:
                        await client.initialize()
                        for name, arguments in (
                            ("browser_navigate", {"url": url}),
                            ("browser_snapshot", {"filename": str(output / "snapshot.md"), "depth": 10}),
                            ("browser_take_screenshot", {"filename": str(output / "page.png"), "type": "png",
                                                         "fullPage": False, "scale": "css"}),
                        ):
                            result = await client.call_tool(name, arguments)
                            if result.isError:
                                raise RuntimeError("Page preview failed: " + " ".join(
                                    getattr(part, "text", "") for part in result.content)[:1500])
                # MCP never receives arbitrary output paths from the caller.
                snapshot = output / "snapshot.md"
                if snapshot.is_symlink() or not snapshot.is_file():
                    raise RuntimeError("Browser produced no page snapshot")
                with snapshot.open("rb") as stream:
                    text = stream.read(128000).decode("utf-8", errors="replace")[:32000]
                owner = execution_context.current_run_id()
                artifacts = []
                if owner is not None:
                    # Only the two requested deliverables, not MCP's automatic debug snapshots.
                    excluded = {p.name for p in output.iterdir() if p.name not in {"snapshot.md", "page.png"}}
                    artifacts, _ = artifact_store.export_workspace(owner, output, excluded=excluded)
                return {"url": url, "text": text, "artifacts": artifacts,
                        "blocked_connections": proxy.blocked, "transfer_bytes": proxy.bytes,
                        "profile": "isolated", "network": "public_https_proxy",
                        "scripts": "disabled", "version": VERSION}

"""Seatbelt-wrapped execution of a whitelisted command (spec §组件2).

Reuses code_sandbox's private building blocks (seatbelt wrapper, rlimits). CRITICAL
DIFFERENCE from run_python: a command is NEVER run without the seatbelt wrapper.
run_python degrades to no-network honestly because its payload is inert computation;
a *command* without network isolation is an unacceptable exfiltration surface, so we
refuse instead of degrading.

Assumes the caller already ran command_policy.validate() — this module does NOT
re-validate the whitelist; it only executes.

NOTE: the seatbelt profile denies NETWORK but not filesystem — a command may read/write
any path the server user can (that is the point: run local tools on the user's files).
This is why every command is confirmation-gated and ffmpeg/pandoc classify at least MEDIUM
(always carded under ask_risky). Do not treat the tmpdir cwd as a filesystem jail.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import signal
import tempfile
from pathlib import Path

from server.services.code_sandbox import (
    MAX_OUTPUT_CHARS,
    _child_limits,
    _seatbelt_wrapper,
    net_profile,
)

TIMEOUT_S = 30.0  # commands (ffmpeg/pandoc) can be heavier than a python snippet


def _trunc(s: str) -> str:
    if len(s) <= MAX_OUTPUT_CHARS:
        return s
    return s[:MAX_OUTPUT_CHARS] + f"\n…[truncated, {len(s)} chars total]"


async def run_command(command: str, argv: list[str], *, timeout_s: float = TIMEOUT_S,
                      proxy_port: int | None = None, cwd: str | None = None,
                      extra_env: dict | None = None) -> dict:
    """Execute [command, *argv] inside a seatbelt sandbox. Returns {ok, stdout, stderr, exit_code}
    — plus error when not ok.

    Local commands (default): ephemeral cwd, HOME/TMPDIR scrubbed, ALL network denied — unchanged.
    Network commands (git/gh): pass `proxy_port` → seatbelt allows ONLY localhost:proxy_port;
    `cwd` = the real repo (so git operates on it); `extra_env` = proxy/CA env. HOME/TMPDIR stay
    scrubbed to `tmp`, so the sandboxed git still cannot read ~/.ssh or ~/.gitconfig — auth is
    injected by the proxy, never by mounted credentials."""
    wrapper = _seatbelt_wrapper(net_profile(proxy_port) if proxy_port else None)
    if wrapper is None:
        return {"ok": False, "exit_code": None,
                "error": "command sandbox unavailable (macOS seatbelt required); refusing to run"}

    tmp = Path(tempfile.mkdtemp(prefix="arslan-cmd-"))
    try:
        env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
               "HOME": str(tmp), "TMPDIR": str(tmp), "LC_ALL": "en_US.UTF-8"}
        if extra_env:
            env.update(extra_env)
        cmd = [*wrapper, command, *argv]
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=(cwd or str(tmp)), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=True, preexec_fn=_child_limits,
        )
        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except TimeoutError:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            await proc.wait()
            return {"ok": False, "exit_code": None,
                    "error": f"command timed out after {int(timeout_s)}s"}

        stdout = _trunc((out_b or b"").decode("utf-8", errors="replace"))
        stderr = _trunc((err_b or b"").decode("utf-8", errors="replace"))
        ok = proc.returncode == 0
        result = {"ok": ok, "exit_code": proc.returncode, "stdout": stdout, "stderr": stderr}
        if not ok:
            result["error"] = f"exit {proc.returncode}: {stderr[-500:] or 'no stderr'}"
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

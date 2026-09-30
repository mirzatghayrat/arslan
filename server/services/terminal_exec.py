"""Run one shell command for Arslan (0.1.48).

A real shell (zsh -c) in the user's folder, with the user's PATH (Homebrew
included, which a Finder-launched app does not inherit) and only the ambient
basics in its environment: provider keys and Arslan's own secret never reach a
command. Whether a command may run at all is decided before this, by
terminal_policy and the confirmation card; this only runs it, bounded in time
and output.
"""
from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path

from server.mcp.spawn_env import child_environment, merged_path

DEFAULT_TIMEOUT_S = 120
MAX_TIMEOUT_S = 600
MAX_OUTPUT_CHARS = 30_000


def clip(text: str, limit: int = MAX_OUTPUT_CHARS) -> tuple[str, bool]:
    """Head and tail of long output: the end of a log is usually where the error is."""
    if len(text) <= limit:
        return text, False
    half = limit // 2
    return text[:half] + f"\n… [{len(text) - limit} characters omitted] …\n" + text[-half:], True


def timeout_of(value) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_S
    return max(5, min(seconds, MAX_TIMEOUT_S))


async def run(command: str, *, cwd: Path, timeout_s: int = DEFAULT_TIMEOUT_S) -> dict:
    env = child_environment({}, {"PATH": merged_path(), "TERM": "dumb", "NO_COLOR": "1",
                                 "HOMEBREW_NO_AUTO_UPDATE": "1"})
    proc = await asyncio.create_subprocess_exec(
        "/bin/zsh", "-c", command, cwd=str(cwd), env=env,
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=True)          # its own process group, so a timeout can stop children too
    timed_out = False
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        out, err = await proc.communicate()
    stdout, cut_out = clip(out.decode("utf-8", errors="replace"))
    stderr, cut_err = clip(err.decode("utf-8", errors="replace"))
    result = {"ok": proc.returncode == 0 and not timed_out, "exit_code": proc.returncode,
              "stdout": stdout, "stderr": stderr, "cwd": str(cwd)}
    if timed_out:
        result["error"] = f"stopped after {timeout_s} s"
    elif proc.returncode != 0:
        result["error"] = f"exit code {proc.returncode}"
    if cut_out or cut_err:
        result["truncated"] = True
    return result

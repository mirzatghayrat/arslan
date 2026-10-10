"""Run one shell command for Arslan (0.1.48).

A real shell (zsh -c) in the user's folder, with the user's PATH (Homebrew
included, which a Finder-launched app does not inherit) and only the ambient
basics in its environment: provider keys and Arslan's own secret never reach a
command. Whether a command may run at all is decided before this, by
terminal_policy and the confirmation card; this only runs it, bounded in time
and output — since 0.1.51 inside the workspace sandbox (command_sandbox) unless
the user clicked to let it out.
"""
from __future__ import annotations

import asyncio
import contextvars
import os
import signal
import tempfile
from pathlib import Path

from server.mcp.spawn_env import child_environment, merged_path

# 0.1.50: set by the tool loop (never by the model) while a run is wrapping up:
# commands still run — processing files already fetched is how a deliverable gets
# made — but without network, so wrap-up cannot become more research.
OFFLINE: contextvars.ContextVar[bool] = contextvars.ContextVar("terminal_offline", default=False)

# 0.1.51 P3: set by the tool loop (never by the model), and only after the user
# clicked: this command runs outside the workspace sandbox.
OUTSIDE_SANDBOX: contextvars.ContextVar[bool] = contextvars.ContextVar("terminal_outside_sandbox", default=False)

DEFAULT_TIMEOUT_S = 120
MAX_TIMEOUT_S = 600
MAX_OUTPUT_CHARS = 30_000


def clip(text: str, limit: int = MAX_OUTPUT_CHARS) -> tuple[str, bool]:
    """Head and tail of long output: the end of a log is usually where the error is."""
    if len(text) <= limit:
        return text, False
    half = limit // 2
    return text[:half] + f"\n… [{len(text) - limit} characters omitted] …\n" + text[-half:], True


def fold_repeats(text: str, min_run: int = 3) -> str:
    """0.1.52 S2 (borrowed from mu, which measured -51% characters on test logs): a run
    of identical consecutive lines shows once, with how many more there were. Only what
    the model sees; the full output, when long, still goes to disk untouched."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        j = i
        while j + 1 < len(lines) and lines[j + 1] == lines[i]:
            j += 1
        run = j - i + 1
        if run >= min_run and lines[i].strip():
            out.extend([lines[i], f"… (the line above repeated {run - 1} more times)"])
        else:
            out.extend(lines[i:j + 1])
        i = j + 1
    return "\n".join(out)


def timeout_of(value) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_S
    return max(5, min(seconds, MAX_TIMEOUT_S))


def _shell() -> str:
    """zsh, the macOS login shell, wherever it exists; /bin/sh elsewhere (CI runs on Linux)."""
    return "/bin/zsh" if os.path.exists("/bin/zsh") else "/bin/sh"


def offline_wrapper() -> list[str] | None:
    """Kernel-enforced no-network wrapper (macOS seatbelt, deny network*), or None
    where there is none — offline mode then refuses rather than runs unisolated."""
    from server.services.code_sandbox import _seatbelt_wrapper
    return _seatbelt_wrapper()


async def run(command: str, *, cwd: Path, timeout_s: int = DEFAULT_TIMEOUT_S,
              offline: bool = False, sandbox: bool = False, closed: list[Path] = (),
              readable: list[Path] = ()) -> dict:
    """`sandbox`: run inside the workspace sandbox. Where seatbelt is missing or
    cannot start, the command runs as before and the result says
    sandbox="unavailable" (offline mode still refuses without isolation)."""
    # zsh writes here-document temp files under $TMPPREFIX (default /tmp/zsh),
    # ignoring TMPDIR: where /tmp is not writable every `python3 - <<'PY'` save
    # failed (0.1.49 bench). Keep both inside the process temp dir.
    tmp = tempfile.gettempdir()
    env = child_environment({}, {"PATH": merged_path(), "TERM": "dumb", "NO_COLOR": "1",
                                 "HOMEBREW_NO_AUTO_UPDATE": "1", "TMPDIR": tmp,
                                 "TMPPREFIX": os.path.join(tmp, "zsh")})
    from server.services import command_sandbox
    prefix: list[str] = []
    mode = "off"
    if sandbox:
        prefix = command_sandbox.wrapper(cwd, offline=offline, closed=closed, readable=readable) or []
        mode = "workspace" if prefix else "unavailable"
    if offline and not prefix:
        prefix = offline_wrapper() or []
        if not prefix:
            return {"ok": False, "exit_code": None, "stdout": "", "stderr": "", "cwd": str(cwd),
                    "error": "wrapping up: commands run without network now, and this system cannot "
                             "isolate the network — save the deliverable with write_file instead"}
    proc = await asyncio.create_subprocess_exec(
        *prefix, _shell(), "-c", command, cwd=str(cwd), env=env,
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
    except asyncio.CancelledError:
        # The job or turn was stopped (from the phone or the window): the command stops with it,
        # children included, instead of running on where nobody sees it.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        raise
    full_out = out.decode("utf-8", errors="replace")
    full_err = err.decode("utf-8", errors="replace")
    stdout, cut_out = clip(fold_repeats(full_out))
    stderr, cut_err = clip(fold_repeats(full_err))
    result = {"ok": proc.returncode == 0 and not timed_out, "exit_code": proc.returncode,
              "stdout": stdout, "stderr": stderr, "cwd": str(cwd), "sandbox": mode}
    if offline:
        result["offline"] = True        # a network error here is the wrap-up rule, not the site
    if cut_out or cut_err:
        # 0.1.49 S9: the middle is not gone, it is on disk.
        from server.services import tool_outputs
        try:
            saved = tool_outputs.save(f"$ {command}\n--- stdout ---\n{full_out}\n--- stderr ---\n{full_err}",
                                      label="command")
            result["full_output_path"] = str(saved)
        except OSError:
            pass
    if timed_out:
        result["error"] = f"stopped after {timeout_s} s"
    elif proc.returncode != 0:
        result["error"] = f"exit code {proc.returncode}"
    if cut_out or cut_err:
        result["truncated"] = True
    if command_sandbox.stopped_by_sandbox(result):
        result["sandbox_denied"] = True
        result["note"] = command_sandbox.note(cwd, closed)
    elif mode == "unavailable":
        result["sandbox_note"] = "ran without the sandbox: it is not available on this system"
    return result

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
import collections
import contextvars
import os
import signal
from pathlib import Path

from server.mcp.spawn_env import child_environment, merged_path

# 0.1.50: set by the tool loop (never by the model) while a run is wrapping up:
# commands still run — processing files already fetched is how a deliverable gets
# made — but without network, so wrap-up cannot become more research.
OFFLINE: contextvars.ContextVar[bool] = contextvars.ContextVar("terminal_offline", default=False)

# 0.1.51 P3: set by the tool loop (never by the model), and only after the user
# clicked: this command runs outside the workspace sandbox.
OUTSIDE_SANDBOX: contextvars.ContextVar[bool] = contextvars.ContextVar("terminal_outside_sandbox", default=False)

# S2a-1 piece 4 (U11): set by the tool loop only, for one call whose Apple Events or Shortcuts card
# the user approved and whose command is one plain call (task_service.unwrapped_once): no wrapper.
UNWRAPPED: contextvars.ContextVar[bool] = contextvars.ContextVar("terminal_unwrapped", default=False)

DEFAULT_TIMEOUT_S = 120
MIN_TIMEOUT_S = 5
MAX_TIMEOUT_S = 600
MAX_OUTPUT_CHARS = 30_000
# 0.1.62 F1: what one stream (stdout or stderr) may hold in memory while a command runs. Output
# used to be read whole at the end, so a command that floods its output could take all the
# memory. 8 MB keeps a long build or test log whole (the model sees 30,000 characters of it; the
# rest goes to disk) and bounds a runaway; past it the head and the tail are kept.
MAX_BUFFER_BYTES = 8 * 1024 * 1024
# After a time limit kills the process group, how long to wait for the output still in the
# pipes. A child that left the group can hold a pipe open forever; never wait on it unbounded.
DRAIN_AFTER_KILL_S = 5.0


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
    return max(MIN_TIMEOUT_S, min(seconds, MAX_TIMEOUT_S))


class _Capped:
    """One stream's output, read as it comes, at most MAX_BUFFER_BYTES in memory: the head
    and the tail, and how many bytes in between were dropped."""

    def __init__(self, limit: int = MAX_BUFFER_BYTES):
        self.half = limit // 2
        self.head = bytearray()
        self.tail: collections.deque[bytes] = collections.deque()
        self.tail_len = 0
        self.dropped = 0

    def add(self, chunk: bytes) -> None:
        room = self.half - len(self.head)
        if room > 0:
            self.head += chunk[:room]
            chunk = chunk[room:]
        if not chunk:
            return
        self.tail.append(chunk)
        self.tail_len += len(chunk)
        while self.tail_len > self.half:
            excess, first = self.tail_len - self.half, self.tail[0]
            if len(first) <= excess:
                self.tail.popleft()
                cut = len(first)
            else:
                self.tail[0] = first[excess:]
                cut = excess
            self.tail_len -= cut
            self.dropped += cut

    def data(self) -> bytes:
        gap = f"\n… [{self.dropped} bytes dropped while running] …\n".encode() if self.dropped else b""
        return bytes(self.head) + gap + b"".join(self.tail)


async def _pump(stream: asyncio.StreamReader, into: _Capped) -> None:
    while chunk := await stream.read(65536):
        into.add(chunk)


def _kill_group(proc) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


async def _cancel(tasks) -> None:
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def _shell() -> str:
    """zsh, the macOS login shell, wherever it exists; /bin/sh elsewhere (CI runs on Linux)."""
    return "/bin/zsh" if os.path.exists("/bin/zsh") else "/bin/sh"


def _reads_a_saved_output(result: dict) -> bool:
    from server.services import tool_outputs
    folder = str(tool_outputs.outputs_dir())
    return folder in f"{result.get('stderr') or ''}\n{result.get('stdout') or ''}"


async def run(command: str, *, cwd: Path, timeout_s: int = DEFAULT_TIMEOUT_S,
              offline: bool = False, sandbox: bool = False, closed: list[Path] = (),
              readable: list[Path] = (), copies: list[Path] = (), unwrapped: bool = False) -> dict:
    """`sandbox`: run inside the workspace sandbox. Where seatbelt is missing or
    cannot start, the command runs as before and the result says
    sandbox="unavailable" (offline mode still refuses without isolation).

    S2a-1 piece 4 (U11): outside the sandbox the command runs under the minimal profile
    (sandbox="outside"), except an approved plain osascript or `shortcuts run` (`unwrapped`, set by
    the tool loop for that one call), which runs with no wrapper (sandbox="off"), as does any
    command where seatbelt cannot start.

    SBX-3 §1a: TMPDIR is the run's own folder (`run_temp`), shared by the run's commands; a command
    outside any run gets one of its own that goes with it."""
    from server.services import execution_context, run_temp
    with run_temp.for_command(execution_context.current_run_id()) as (temp_key, tmp):
        return await _run(command, cwd=cwd, timeout_s=timeout_s, offline=offline, sandbox=sandbox, closed=closed,
                          readable=readable, copies=copies, unwrapped=unwrapped, tmp=tmp, temp_key=temp_key)


async def _run(command: str, *, cwd: Path, timeout_s: int, offline: bool, sandbox: bool, closed: list[Path],
               readable: list[Path], copies: list[Path], unwrapped: bool, tmp: Path, temp_key: int) -> dict:
    # zsh writes here-document temp files under $TMPPREFIX (default /tmp/zsh),
    # ignoring TMPDIR: where /tmp is not writable every `python3 - <<'PY'` save
    # failed (0.1.49 bench). Keep both inside the run's own folder.
    env = child_environment({}, {"PATH": merged_path(), "TERM": "dumb", "NO_COLOR": "1",
                                 "HOMEBREW_NO_AUTO_UPDATE": "1", "TMPDIR": str(tmp),
                                 "TMPPREFIX": os.path.join(tmp, "zsh")})
    from server.services import command_sandbox, run_temp
    prefix: list[str] = []
    mode = "off"
    if sandbox:
        prefix = command_sandbox.wrapper(cwd, temp=tmp, offline=offline, closed=closed, readable=readable,
                                         copies=copies) or []
        mode = "workspace" if prefix else "unavailable"
    elif not unwrapped:
        prefix = command_sandbox.outside_wrapper(offline=offline, copies=copies) or []
        mode = "outside" if prefix else "off"
    if offline and not prefix:
        return {"ok": False, "exit_code": None, "stdout": "", "stderr": "", "cwd": str(cwd),
                "error": "commands run without network now, and this run cannot isolate the network — "
                         "save the deliverable with write_file instead"}
    proc = await asyncio.create_subprocess_exec(
        *prefix, _shell(), "-c", command, cwd=str(cwd), env=env,
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=True)          # its own process group, so a timeout can stop children too
    run_temp.started(temp_key, proc.pid)  # §1a: the run's folder stays while this group has a process left
    # 0.1.62 F1: output is read while the command runs (it used to be read in one go at the
    # end), so a time limit keeps what was already printed instead of losing it with the read.
    out_buf, err_buf = _Capped(), _Capped()
    tasks = [asyncio.ensure_future(proc.wait()), asyncio.ensure_future(_pump(proc.stdout, out_buf)),
             asyncio.ensure_future(_pump(proc.stderr, err_buf))]
    timed_out = False
    try:
        _, pending = await asyncio.wait(tasks, timeout=timeout_s)
    except asyncio.CancelledError:
        # The job or turn was stopped (from the phone or the window): the command stops with it,
        # children included, instead of running on where nobody sees it.
        _kill_group(proc)
        await asyncio.shield(_cancel(tasks))
        raise
    if pending:
        timed_out = True
        _kill_group(proc)
        _, pending = await asyncio.wait(pending, timeout=DRAIN_AFTER_KILL_S)
        await _cancel(pending)
    full_out = out_buf.data().decode("utf-8", errors="replace")
    full_err = err_buf.data().decode("utf-8", errors="replace")
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
    if out_buf.dropped or err_buf.dropped:
        result["dropped_bytes"] = out_buf.dropped + err_buf.dropped
    if timed_out:
        result["error"] = f"stopped after {timeout_s} s"     # M2 counts this exact text: keep it
        result["code"] = "time_limit"
    elif proc.returncode != 0:
        result["error"] = f"exit code {proc.returncode}"
    if cut_out or cut_err:
        result["truncated"] = True
    if command_sandbox.stopped_by_sandbox(result) and _reads_a_saved_output(result):
        # S2a-1 piece 5: a saved tool output this conversation was not given. read_file reads it;
        # running the command outside the sandbox would open far more than one copy, so no card.
        result["note"] = ("Saved tool outputs are read with read_file (path, offset, limit), not from a "
                          "command. A command may read only the copies saved in this conversation.")
    elif command_sandbox.stopped_by_sandbox(result):
        result["sandbox_denied"] = True
        # SBX-7: the denial's code (EPERM, the one SBX-3 detects so far). The run step keeps it on its `ref`
        # (run_trace, run_recorder), out of reach of result_raw's cut, and only the weekly report counts it.
        result["sandbox_denial"] = "eperm"
        result["note"] = command_sandbox.note(cwd, closed)
    elif mode == "outside" and not result["ok"] and command_sandbox.refused_outside(result):
        result["note"] = ("Even outside the sandbox a command cannot read or write Arslan's own data, keys or "
                          "Arslan Hands' folder. Tell the user what you needed.")
    elif mode == "unavailable":
        result["sandbox_note"] = "ran without the sandbox: it is not available on this system"
    return result

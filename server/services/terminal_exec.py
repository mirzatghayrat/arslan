"""Run one shell command for Arslan (0.1.48).

A real shell (`bash -p -c`) in the user's folder, with the user's PATH (Homebrew
included, which a Finder-launched app does not inherit) and only the ambient
basics in its environment: provider keys and Arslan's own secret never reach a
command. S2a-3: bash because it's the one grammar shell_grammar reads, and
privileged mode because it skips $ENV and $BASH_ENV, imports no functions and
ignores SHELLOPTS, so nothing outside the command's text changes how it is read.
It was `zsh -c`, which read ~/.zshenv first. Whether a command may run at all is decided before this, by
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

# HR-1: set by the tool loop only, for one call let out of the sandbox by this conversation's grant with no click on
# its own card: the outside floor keeps the files that make something run later unwritable (ruling 2).
HOLD_RUN_LATER: contextvars.ContextVar[bool] = contextvars.ContextVar("terminal_hold_run_later", default=False)

# HR-1b: set by the tool loop only, for one call in the sandbox under this conversation's git_config grant.
GIT_CONFIG: contextvars.ContextVar[bool] = contextvars.ContextVar("terminal_git_config", default=False)
#: HR-1b: what a command under that grant gets in its environment (`_run`): no template folder for clone and init.
GIT_CONFIG_ENV = {"GIT_TEMPLATE_DIR": ""}

SHELL = ("/bin/bash", "-p")
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


async def _reap_then_cancel(tasks) -> None:
    """After the kill on a cancel: wait for the process to be reaped (`tasks[0]` is `proc.wait()`), at most
    DRAIN_AFTER_KILL_S as after a time limit, then stop the reads. Until the kernel has reaped it a killed process
    still counts as alive, so `run_temp.finish` would keep the run's temp folder (SBX-3 §1a), and a command outside
    any run has no later finish: its folder stayed until the next start's sweep (#813 review 12)."""
    await asyncio.wait(tasks[:1], timeout=DRAIN_AFTER_KILL_S)
    await _cancel(tasks)


def _group_alive(pgid: int) -> bool:
    """A process of the group is left that can still run (EPERM on macOS: only zombies are left)."""
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


async def _end_group(proc) -> bool:
    """HR-1b: kills what is left of the group, waits until none can run (at most DRAIN_AFTER_KILL_S); was one left?"""
    left = _group_alive(proc.pid)
    _kill_group(proc)
    deadline = asyncio.get_running_loop().time() + DRAIN_AFTER_KILL_S
    while _group_alive(proc.pid) and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.01)
    return left


def _reads_a_saved_output(result: dict) -> bool:
    from server.services import tool_outputs
    folder = str(tool_outputs.outputs_dir())
    return folder in f"{result.get('stderr') or ''}\n{result.get('stdout') or ''}"


async def run(command: str, *, cwd: Path, timeout_s: int = DEFAULT_TIMEOUT_S,
              offline: bool = False, sandbox: bool = False, closed: list[Path] = (),
              readable: list[Path] = (), copies: list[Path] = (), unwrapped: bool = False,
              hold_run_later: bool = False, git_config: bool = False, walk_root: Path | None = None) -> dict:
    """`sandbox`: run inside the workspace sandbox. Where seatbelt is missing or
    cannot start, the command runs as before and the result says
    sandbox="unavailable" (offline mode still refuses without isolation).

    S2a-1 piece 4 (U11): outside the sandbox the command runs under the minimal profile
    (sandbox="outside"), except an approved plain osascript or `shortcuts run` (`unwrapped`, set by
    the tool loop for that one call), which runs with no wrapper (sandbox="off"), as does any
    command where seatbelt cannot start.

    SBX-3 §1a: TMPDIR is the run's own folder (`run_temp`), shared by the run's commands; a command
    outside any run gets one of its own that goes with it.

    HR-1b: `git_config`, the grant, lifts the configs in the sandbox (`_guarded`). Review deltas 3 and 4: once any
    folder had it, every command is checked first (`git_config_guard.recheck`), and not started if that fails.

    SBX-10: `walk_root`, a sub-session's commander's workspace, is walked for run-later files in the sandbox's
    profile (`command_sandbox.wrapper`); writes stay in `cwd`."""
    from server.services import execution_context, git_config_guard, run_temp, tool_outputs
    note = ""
    if git_config_guard.WATCHED:
        try:
            note = await asyncio.to_thread(git_config_guard.recheck)
        except Exception as exc:  # noqa: BLE001 — fails closed: the command doesn't start, and the grant ends
            git_config_guard.ENDED.add(tool_outputs.conversation.get() or "")
            return {"ok": False, "exit_code": None, "stdout": "", "stderr": "", "cwd": str(cwd),
                    "sandbox": "workspace" if sandbox else "outside", "git_config_held": True,
                    "error": "not started: git settings couldn't be checked", "git_config_note": str(exc)
                    if isinstance(exc, git_config_guard.Refused) else git_config_guard.REFUSED}
    with run_temp.for_command(execution_context.current_run_id()) as (temp_key, tmp):
        kw = dict(command=command, cwd=cwd, timeout_s=timeout_s, offline=offline, sandbox=sandbox, closed=closed,
                  readable=readable, copies=copies, unwrapped=unwrapped, tmp=tmp, temp_key=temp_key,
                  hold_run_later=hold_run_later, walk_root=walk_root)
        result = await (_guarded(cwd, kw) if git_config and sandbox else _run(**kw))
    if note:
        result["git_config_note"] = f"{note} {result.get('git_config_note', '')}".strip()
    return result


async def _guarded(cwd: Path, kw: dict) -> dict:
    """HR-1b: under the grant, the configs saved (else it runs held, and says so), then put back however it ended."""
    from server.services import git_config_guard
    try:
        saved = await asyncio.to_thread(git_config_guard.snapshot, cwd, kw["closed"])
    except (git_config_guard.GuardError, OSError) as exc:
        result = await _run(**kw)
        result["git_config_note"] = ((
            "A git config file in the working folder has a second name (a hard link) or is a link"
            if isinstance(exc, git_config_guard.Linked) else "Arslan couldn't look through the working folder's git "
            "settings before this command (too many folders, or one it can't read)")
            + ", so git couldn't update them this time, as without the git_config permission.")
        return result
    git_config_guard.watch(cwd, kw["closed"])          # review delta 3: checked before every later command
    try:
        result = await _run(**kw, git_config_ok=True)
    except BaseException:
        _put_back(saved)                 # stopped or failed: still checked, here on the loop (it is quick)
        raise
    message, held = await asyncio.to_thread(_put_back, saved)
    if result.pop("git_config_stopped", False):
        message = ("Arslan stopped what this command left running: under the git_config permission nothing may run on "
                   "past the check of the git settings. " + message).strip()
    if message:
        result["git_config_note"] = message
    if held:
        result["git_config_held"] = True    # the tool loop deletes the stored grant (command_gate.end_git_config)
    return result


def _put_back(saved) -> tuple[str, bool]:
    """git_config_guard.restore, never raising: the step's note, and whether a put-back failed (the grant ends)."""
    from server.services import git_config_guard, tool_outputs
    try:
        outcome = git_config_guard.restore(saved)
        message, held = outcome.message(), bool(outcome.held)
    except Exception:  # noqa: BLE001 — reported to the model and on the step instead
        import logging
        logging.getLogger(__name__).warning("git config restore failed", exc_info=True)
        message, held = git_config_guard.HELD_NOTE, True
    if held:
        git_config_guard.ENDED.add(tool_outputs.conversation.get() or "")
    return message, held


async def trust_service_allowed() -> bool:
    """SBX-6a: the user's "Allow system certificate checks in the sandbox" (default off), for commands and
    installed MCP servers online. Off when unreadable."""
    try:
        from server.db import session as db_session
        from server.services import settings_service
        async with db_session.AsyncSessionLocal() as db:
            return await settings_service.sandbox_system_certificates(db)
    except Exception:  # noqa: BLE001 — a setting that can't be read is the default: off
        return False


async def _run(command: str, *, cwd: Path, timeout_s: int, offline: bool, sandbox: bool, closed: list[Path],
               readable: list[Path], copies: list[Path], unwrapped: bool, tmp: Path, temp_key: int,
               hold_run_later: bool = False, git_config_ok: bool = False, walk_root: Path | None = None) -> dict:
    # bash writes here-document temp files under TMPDIR and a nested zsh (`zsh -c`, a `#!/bin/zsh` script) under
    # TMPPREFIX: where /tmp is not writable a `python3 - <<'PY'` save would fail (0.1.49 bench). Both stay in the run's folder.
    # Off the event loop: before the supervisor's prewarm, the first call reads the login shell (#674 review).
    env = child_environment({}, {"PATH": await asyncio.to_thread(merged_path), "TERM": "dumb", "NO_COLOR": "1",
                                 "HOMEBREW_NO_AUTO_UPDATE": "1", "TMPDIR": str(tmp),
                                 "TMPPREFIX": os.path.join(tmp, "zsh")})
    from server.services import command_sandbox, root_pin, run_later, run_temp, sandbox_proxy
    if git_config_ok:       # HR-1b: no template, so clone and init make no `.git/hooks` folder (it stays held)
        env.update(GIT_CONFIG_ENV)
    prefix: list[str] = []
    mode = "off"
    if sandbox:
        env.update(command_sandbox.cache_environment(run_temp.cache("commands")))   # SBX-5 §1c: its own cache
        # SBX-6: online, the sandbox lets TCP out only to Arslan's local proxy, and the child is told to use
        # it; dev servers on loopback are reached directly. No proxy means the profile is offline.
        proxy_port = None if offline else await sandbox_proxy.port()
        trust = proxy_port is not None and await trust_service_allowed()
        if proxy_port is not None:
            via = f"http://127.0.0.1:{proxy_port}"
            env.update({name: via for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                                               "http_proxy", "https_proxy", "all_proxy")})
            env["NO_PROXY"] = env["no_proxy"] = "localhost,127.0.0.1,::1"
        # Off the event loop: a large work folder's walk takes a while (#813 review 11: about a second for 1,000 links
        # at held names). Past the link cap no profile is built and the command doesn't start.
        try:
            prefix = await command_sandbox.in_thread(
                command_sandbox.wrapper, cwd, temp=tmp, offline=offline, closed=closed, readable=readable,
                copies=copies, proxy_port=proxy_port, trust_service=trust, git_config_ok=git_config_ok,
                walk_root=walk_root) or []
        except run_later.TooManyLinks:
            return _not_started(cwd, "workspace", command_sandbox.links_note(cwd))
        except root_pin.Swapped as exc:                 # SBX-9: a root swapped while it was pinned
            return _swapped(cwd, "workspace", exc)
        mode = "workspace" if prefix else "unavailable"
    elif not unwrapped:
        try:
            prefix = await command_sandbox.in_thread(
                command_sandbox.outside_wrapper, offline=offline, copies=copies,
                run_later_in=cwd if hold_run_later else None, closed=closed) or []
        except run_later.TooManyLinks:
            return _not_started(cwd, "outside", command_sandbox.links_note(cwd))
        except root_pin.Swapped as exc:
            return _swapped(cwd, "outside", exc)
        mode = "outside" if prefix else "off"
    # #813 review 11: sandbox-exec has read its profile file once the command is running; it goes when the process has
    # exited, on every path (success, failure, a time limit, a cancel, a start that failed).
    profile = command_sandbox.profile_path(prefix)
    try:
        return await _execute(command, prefix=prefix, cwd=cwd, env=env, temp_key=temp_key, timeout_s=timeout_s,
                              offline=offline, closed=closed, mode=mode, hold_run_later=hold_run_later,
                              git_config_ok=git_config_ok)
    finally:
        command_sandbox.remove_profile(profile)


def _not_started(cwd: Path, mode: str, note: str) -> dict:
    """#813 review 11: a command the sandbox didn't start (past the link cap), with the note that says why."""
    return {"ok": False, "exit_code": None, "stdout": "", "stderr": "", "cwd": str(cwd), "sandbox": mode,
            "code": "too_many_links", "error": "not started: too many links at protected names", "note": note}


def _swapped(cwd: Path, mode: str, exc) -> dict:
    """SBX-9: a command not started because a root it writes was swapped while the sandbox was starting."""
    from server.services import root_pin
    return {**_not_started(cwd, mode, root_pin.note(exc)), "code": "root_swapped",
            "error": "not started: a folder it may write was replaced while the sandbox was starting"}


async def _execute(command: str, *, prefix: list[str], cwd: Path, env: dict, temp_key: int, timeout_s: int,
                   offline: bool, closed: list[Path], mode: str, hold_run_later: bool,
                   git_config_ok: bool = False) -> dict:
    from server.services import command_sandbox, root_pin, run_temp
    if offline and not prefix:
        return {"ok": False, "exit_code": None, "stdout": "", "stderr": "", "cwd": str(cwd),
                "error": "commands run without network now, and this run cannot isolate the network — "
                         "save the deliverable with write_file instead"}
    profile = command_sandbox.profile_path(prefix)
    try:
        command_sandbox.check_pins(profile)        # SBX-9: the roots are still the folders the profile names
    except root_pin.Swapped as exc:
        return _swapped(cwd, mode, exc)
    proc = await asyncio.create_subprocess_exec(
        *prefix, *SHELL, "-c", command, cwd=str(cwd), env=env,
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=True)          # its own process group, so a timeout can stop children too
    command_sandbox.release_pins(profile)
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
        await asyncio.shield(_reap_then_cancel(tasks))
        if git_config_ok:
            await asyncio.shield(_end_group(proc))       # HR-1b: before the put-back (`_guarded`)
        raise
    if pending:
        timed_out = True
        _kill_group(proc)
        _, pending = await asyncio.wait(pending, timeout=DRAIN_AFTER_KILL_S)
        await _cancel(pending)
    left_running = await _end_group(proc) if git_config_ok else False      # HR-1b: before the put-back
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
    if left_running and not timed_out:
        result["git_config_stopped"] = True
    return explain(result, cwd=cwd, closed=closed, mode=mode, timed_out=timed_out, command=command,
                   hold=hold_run_later, git_config=git_config_ok)


def explain(result: dict, *, cwd: Path, closed: list[Path], mode: str, timed_out: bool, command: str,
            hold: bool = False, git_config: bool = False) -> dict:
    """What the model reads beside a finished command's output: why the sandbox stopped it, if it did. Records the
    SBX-7 denial code through run_trace, never on the result, once per run. `hold`: the outside floor held the files
    that make something run later (HR-1). `git_config`: it ran under the git_config grant (HR-1b), so a refusal on the
    repository's config doesn't offer the grant again."""
    from server.services import command_sandbox
    # HR-1 (#813 reviews 4 and 5): git's refusal lines name a held file (in the sandbox, or under a floor that holds
    # them). A step that failed outright on the repository's own config or hooks (clone, init, remote add, a config
    # write) gets the stop note or the floor's instead: the git note is for a tree that may be partly updated, or a
    # step that exited 0 with its upstream or setting unsaved.
    held = command_sandbox.git_refused_paths(result, command=command, cwd=cwd, hold=hold)
    git = bool(held) and not command_sandbox.git_setup_failed(result, held)
    # HR-1b: refused on the repository's config only, in the sandbox, without the grant: the note offers it.
    offer = (result.get("sandbox") == "workspace" and not git_config
             and command_sandbox.git_config_only(held, cwd))
    if command_sandbox.stopped_by_sandbox(result) and _reads_a_saved_output(result):
        # S2a-1 piece 5: a saved tool output this conversation was not given. read_file reads it;
        # running the command outside the sandbox would open far more than one copy, so no card.
        result["note"] = ("Saved tool outputs are read with read_file (path, offset, limit), not from a "
                          "command. A command may read only the copies saved in this conversation.")
    elif command_sandbox.stopped_by_sandbox(result):
        result["sandbox_denied"] = True
        # What a failed step shows the user, with no card now (the calibration of 2026-11-07), and what the model reads.
        # A time limit keeps its own text (M2 counts it).
        if not timed_out:
            result["error"] = f"the sandbox stopped this command ({result.get('error')})"
        # SBX-7: the denial's code (`eperm`, or `proxy` for the local proxy's refusal with no EPERM beside it) goes to
        # the run step's `ref` through run_trace, never onto this result: the model and every other payload read the
        # result. A failed certificate check is neither, so it alone records no code.
        trust = command_sandbox.trust_check_failed(result)
        proxy = (not git and command_sandbox.proxy_refused(result)
                 and not command_sandbox.refused_outside(result))                                     # EPERM text
        if git or proxy or not trust:
            from server.orchestrator import run_trace
            run_trace.note_denial("proxy" if proxy else "eperm")
        result["note"] = (command_sandbox.git_note(git_config=offer) if git
                          else command_sandbox.note(cwd, closed, trust=trust, proxy=proxy, git_config=offer))
    elif result["ok"] and command_sandbox.proxy_refused(result):
        # A client that printed the proxy's refusal and exited 0 (curl without -f on plain http): still a denial,
        # but not a failed step.
        from server.orchestrator import run_trace
        run_trace.note_denial("proxy")
        result["note"] = command_sandbox.note(cwd, closed, proxy=True)
    elif git:
        # HR-1 (#813 review 4): git exits 0 when the kernel refused a held file it had to change (checkout and switch:
        # HEAD moved, that file left as it was) or its config (a tracking checkout, push -u, --set-upstream-to: no
        # upstream saved); and under the outside floor at any exit code. The same note as in the stop above. In the
        # sandbox, not a failed step but one denial. Under the floor no denial (#813 review 5): SBX-7 counts the
        # workspace sandbox's denials, and the floor's other refusals record none either.
        if result.get("sandbox") == "workspace":
            from server.orchestrator import run_trace
            run_trace.note_denial("eperm")
        result["note"] = command_sandbox.git_note(git_config=offer)
    elif mode == "outside" and not result["ok"] and command_sandbox.refused_outside(result):
        result["note"] = ("Even outside the sandbox a command cannot read or write Arslan's own data, keys or "
                          "Arslan Hands' folder"
                          + (", nor, without the user's click on its own card, change files that make something run "
                             "later (git hooks and config, editor tasks, agent and package settings)" if hold else "")
                          + ". Tell the user what you needed.")
    elif mode == "unavailable":
        result["sandbox_note"] = "ran without the sandbox: it is not available on this system"
    return result

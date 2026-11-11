"""HOOK-2 (docs/plans/0164/HOOK-plugin-hooks.md): run one plugin hook of the `command` type, for one of the five
events, and read its answer. Nothing calls this yet: HOOK-3 wires it into the tool call and the turn, with the shared
breaker, the unattended skip and the ledger rows.

- **Rule 1, in the sandbox with a time limit.** The commands preset, offline, with the run's own private temp folder
  as the only writable place; the conversation's work folder is readable (reopened read-only when it lies in a closed
  folder) and is the hook's cwd; the plugin's own folder is readable through `commands_profile(plugin_read=...)` and
  is `${CLAUDE_PLUGIN_ROOT}`. The limit is `plugin_hooks.MAX_TIMEOUT_S`, which a hook's own `timeout` can only lower;
  the process group is killed when it runs out.
- **Rule 2, an error lets nothing through.** For PreToolUse and UserPromptSubmit a timeout, a crash, an exit code
  other than 0 or 2, unreadable JSON, a refused write or connection, or a sandbox that can't start is "ask", with
  `DIDNT_ANSWER`. For PostToolUse, SessionStart and Stop it adds nothing and is only recorded (`HookResult.error`).
- **Rule 3, it can only tighten.** "allow" (and the older "approve") is no answer, never an approval: there is no
  result that approves. `updatedInput` and `updatedToolOutput` are ignored.

Claude Code's input and output: https://code.claude.com/docs/en/hooks (read 2026-11-10).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

from server.mcp.spawn_env import child_environment, merged_path
from server.services import command_sandbox, plugin_hooks, run_later, run_temp, terminal_exec

_log = logging.getLogger(__name__)

EVENTS = ("PreToolUse", "PostToolUse", "SessionStart", "UserPromptSubmit", "Stop")
#: The events whose error is "ask" (rule 2).
GUARDS = ("PreToolUse", "UserPromptSubmit")
NONE, DENY, ASK, BLOCK, CONTINUE = "none", "deny", "ask", "block", "continue"
DIDNT_ANSWER = "the plugin's check didn't answer"
TRIED_WRITE, TRIED_NETWORK = "tried to write files", "tried to reach the network"
#: What is kept of each of stdout and stderr (head and tail), and of a reason or context handed on.
OUTPUT_CAP = 64 * 1024
TEXT_CAP = 10_000
_REVERSE = {key: name for name, key in plugin_hooks.TOOL_MAP.items()}
#: Next to the denial text (on its line or the one before, as in a Python traceback): a connection was refused.
_NETWORK = re.compile(r"connect|socket|network|urlopen|getaddrinfo", re.I)
#: Without it: how a name lookup or a connection fails offline (no DNS, `deny network*`) in curl, Python and git.
_OFFLINE = re.compile(r"nodename nor servname|resolve host|failed to connect|couldn't connect", re.I)


@dataclass(frozen=True)
class HookResult:
    """One run's answer. `decision`: PreToolUse DENY or ASK; UserPromptSubmit BLOCK (or ASK on an error); Stop
    CONTINUE; NONE otherwise. `context` is outside content for the model. `error` (why the run counts as an error)
    and `tried` (refused writes or connections) are for the ledger."""
    decision: str = NONE
    reason: str = ""
    context: str = ""
    error: str | None = None
    tried: tuple[str, ...] = ()


def hook_input(event: str, *, workspace: Path, session_id: str, tool: str | None = None, args: dict | None = None,
               response=None, prompt: str | None = None, stop_active: bool = False) -> dict:
    """Claude Code's JSON input for `event`. `tool` is Arslan's tool key (a `TOOL_MAP` value, or "mcp:<server>:<tool>"
    as HOOK-1 reads matchers), turned back into Claude Code's name, and `args` into its input's shape."""
    data = {"session_id": session_id, "cwd": str(workspace), "hook_event_name": event, "permission_mode": "default"}
    if event in ("PreToolUse", "PostToolUse"):
        args = args or {}
        if tool.startswith("mcp:"):
            _, server, name = tool.split(":", 2)
            data.update(tool_name=f"mcp__{server}__{name}", tool_input=dict(args))
        elif tool == "run_command":
            data.update(tool_name="Bash", tool_input={"command": args.get("command", ""),
                                                      **({"description": args["why"]} if args.get("why") else {}),
                                                      **({"timeout": args["timeout_s"] * 1000}
                                                         if "timeout_s" in args else {})})
        else:
            data.update(tool_name=_REVERSE[tool], tool_input={
                "file_path": os.path.normpath(os.path.join(workspace, args.get("path", ""))),
                **{k: v for k, v in args.items() if k in ("content", "old_string", "new_string", "offset", "limit")}})
        if event == "PostToolUse":
            data["tool_response"] = response
    elif event == "UserPromptSubmit":
        data["prompt"] = prompt or ""
    elif event == "SessionStart":
        data["source"] = "startup"
    elif event == "Stop":
        data["stop_hook_active"] = stop_active
    return data


def limit_of(row: dict) -> float:
    """The run's time limit: the hook's own `timeout`, only ever lower than MAX_TIMEOUT_S."""
    return plugin_hooks._timeout(row.get("timeout"))


def _tried(stdout: str, stderr: str) -> tuple[str, ...]:
    """What the sandbox refused, by `command_sandbox`'s denial text (EPERM) and offline seatbelt's failed name
    lookups. Heuristic as `stopped_by_sandbox` is: reads are open outside the closed folders, so an EPERM that isn't a
    connection is counted as a write."""
    found = set()
    lines = f"{stderr}\n{stdout}".splitlines()
    for before, line in zip(["", *lines], lines):
        denied = command_sandbox._DENIED.search(line)
        if _OFFLINE.search(line) or (denied and _NETWORK.search(f"{before}\n{line}")):
            found.add(TRIED_NETWORK)
        elif denied:
            found.add(TRIED_WRITE)
    return tuple(sorted(found))


def _failed(event: str, error: str, tried: tuple[str, ...] = ()) -> HookResult:
    _log.info("HOOK-2: a %s hook didn't answer: %s", event, error)
    if event in GUARDS:
        return HookResult(ASK, DIDNT_ANSWER, error=error, tried=tried)
    return HookResult(error=error, tried=tried)


def parse(event: str, code: int | None, stdout: str, stderr: str, *, timed_out: bool = False) -> HookResult:
    """A finished run's answer (Claude Code's exit codes and JSON fields), errors mapped by rule 2."""
    tried = _tried(stdout, stderr)
    if timed_out:
        return _failed(event, "timed out", tried)
    if code not in (0, 2):
        return _failed(event, f"exit code {code}", tried)
    said = stderr.strip()[:TEXT_CAP]
    if code == 2:
        result = {"PreToolUse": HookResult(DENY, said), "UserPromptSubmit": HookResult(BLOCK, said),
                  "Stop": HookResult(CONTINUE, said), "PostToolUse": HookResult(context=said)}.get(event, HookResult())
    elif stdout.lstrip().startswith(("{", "[")):
        try:
            data = json.loads(stdout)
            result = _answer(event, data if isinstance(data, dict) else None)
        except (ValueError, TypeError, AttributeError, RecursionError):     # nested past the limit too
            return _failed(event, "unreadable JSON", tried)
    else:   # plain text: context for these two, as in Claude Code; no answer elsewhere
        result = HookResult(context=stdout.strip()[:TEXT_CAP] if event in ("UserPromptSubmit", "SessionStart") else "")
    if tried and (event not in GUARDS or result.decision == NONE):
        return _failed(event, tried[0], tried)     # rule 1: a refused write or connection is an error
    return HookResult(result.decision, result.reason, result.context, tried=tried)


def _text(value) -> str:
    if not isinstance(value, str):
        raise TypeError("not text")
    return value[:TEXT_CAP]


def _answer(event: str, data: dict) -> HookResult:
    """Claude Code's JSON output on exit 0. Raises on a shape it wouldn't read (unreadable JSON)."""
    special = data.get("hookSpecificOutput") or {}
    decision = data.get("decision")
    context = _text(special.get("additionalContext", ""))
    stop = data.get("continue") is False
    stop_reason = _text(data.get("stopReason", ""))
    if event == "PreToolUse":
        said = special.get("permissionDecision")
        reason = _text(special.get("permissionDecisionReason", data.get("reason", "")))
        if said not in (None, "allow", "deny", "ask") or decision not in (None, "approve", "block"):
            raise ValueError("unknown decision")
        if said == "deny" or (said is None and decision == "block") or stop:
            return HookResult(DENY, reason or stop_reason)
        return HookResult(ASK, reason) if said == "ask" else HookResult()     # "allow" is no answer (rule 3)
    if event == "UserPromptSubmit":
        if decision not in (None, "block"):
            raise ValueError("unknown decision")
        if decision == "block" or stop:
            return HookResult(BLOCK, _text(data.get("reason", "")) or stop_reason)
        return HookResult(context=context)
    if event == "Stop":
        if decision == "block" and not stop:
            return HookResult(CONTINUE, _text(data.get("reason", "")))
        return HookResult()
    if event == "PostToolUse" and decision == "block":
        context = "\n".join(filter(None, (_text(data.get("reason", "")), context)))
    return HookResult(context=context)                  # PostToolUse, SessionStart: `updatedToolOutput` ignored


def _prefix(temp: Path, workspace: Path, plugin_dir: Path, closed) -> list[str]:
    """sandbox-exec with the hook's profile: offline, `temp` the only place written (its cache inside it), the work
    folder readable, the plugin's own folder readable. Raises ValueError for a folder that isn't a plugin's own."""
    text = command_sandbox.commands_profile(temp, cache=temp, offline=True, closed=list(closed), readable=[workspace],
                                            plugin_read=plugin_dir)
    return [command_sandbox._SANDBOX_EXEC, "-f", str(command_sandbox.write_profile(text))]


async def run(row: dict, payload: dict, *, plugin_dir: Path, workspace: Path, closed=()) -> HookResult:
    """Run hook `row` (a HOOK-1 row: `event`, `type` "command", `command`, `args`, `timeout`) with `payload`
    (`hook_input`) on its stdin. `plugin_dir`: the plugin's own folder, a resolved path inside the plugin root.
    `closed`: the user's closed folders."""
    event = row["event"]
    if event not in EVENTS or row.get("type") != "command" or not isinstance(row.get("command"), str):
        raise ValueError(f"not a hook this version runs: {event} {row.get('type')}")
    if not command_sandbox.available():
        return _failed(event, "the sandbox can't start here")
    if isinstance(row.get("args"), list):   # the exec form: no shell, the folder written into each word
        argv = [word.replace("${CLAUDE_PLUGIN_ROOT}", str(plugin_dir)) for word in (row["command"], *row["args"])]
    else:                                   # a shell line: bash expands $CLAUDE_PLUGIN_ROOT from the environment
        argv = [*terminal_exec.SHELL, "-c", row["command"]]
    with run_temp.for_command(None) as (key, temp):
        try:
            env = {**child_environment({}, {
                "PATH": await asyncio.to_thread(merged_path), "TERM": "dumb", "NO_COLOR": "1",
                "TMPDIR": str(temp), "CLAUDE_PLUGIN_ROOT": str(plugin_dir), "CLAUDE_PROJECT_DIR": str(workspace)}),
                **command_sandbox.cache_environment(temp / "cache")}
            prefix = await command_sandbox.in_thread(_prefix, temp, workspace, plugin_dir, closed)
        except (ValueError, OSError, run_later.TooManyLinks) as exc:
            return _failed(event, f"the sandbox didn't start: {exc}")
        try:
            # `--`: a dash-led exec-form command can't pass options to sandbox-exec.
            return await _execute(event, [*prefix, "--", *argv], payload, cwd=workspace, env=env, key=key,
                                  limit=limit_of(row))
        finally:
            command_sandbox.remove_profile(command_sandbox.profile_path(prefix))


async def _feed(stdin: asyncio.StreamWriter, data: bytes) -> None:
    try:
        stdin.write(data)
        await stdin.drain()
        stdin.close()
    except (BrokenPipeError, ConnectionResetError):
        pass                                # a hook that doesn't read its input exited before taking it all


async def _execute(event: str, argv: list[str], payload: dict, *, cwd: Path, env: dict, key: int,
                   limit: float) -> HookResult:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(cwd), env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, start_new_session=True)     # its own group, killed whole at the limit
    except OSError as exc:
        return _failed(event, f"didn't start: {exc}")
    run_temp.started(key, proc.pid)
    out, err = terminal_exec._Capped(OUTPUT_CAP), terminal_exec._Capped(OUTPUT_CAP)
    tasks = [asyncio.ensure_future(proc.wait()), asyncio.ensure_future(terminal_exec._pump(proc.stdout, out)),
             asyncio.ensure_future(terminal_exec._pump(proc.stderr, err)),
             asyncio.ensure_future(_feed(proc.stdin, json.dumps(payload).encode()))]
    try:
        await asyncio.wait(tasks[:1], timeout=limit)
    except asyncio.CancelledError:
        terminal_exec._kill_group(proc)
        await asyncio.shield(terminal_exec._reap_then_cancel(tasks))
        raise
    timed_out = not tasks[0].done()
    terminal_exec._kill_group(proc)         # at the limit, and anything the hook left running when it exited
    _, pending = await asyncio.wait(tasks, timeout=terminal_exec.DRAIN_AFTER_KILL_S)
    await terminal_exec._cancel(pending)
    try:
        return parse(event, proc.returncode, out.data().decode("utf-8", errors="replace"),
                     err.data().decode("utf-8", errors="replace"), timed_out=timed_out)
    except Exception:  # noqa: BLE001 — output parse can't read fails closed: ask for the guards, nothing else
        return _failed(event, "unreadable output")

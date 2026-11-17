"""L7-5: a goal's `check:` lines, run by the host at each verdict (docs/plans/0164/L7-goal-mode.md, "Check files are
protected from Start: verify, then run in place"; "Fit with LOOP1").

Each line runs as a host call through `_run_tool`, as `_presearch` does, with the arguments the model would send for
the same command (`{"command": ...}`): the same admission and budget, plan mode, command gate (`_never_runs`,
`_where_it_runs`, `_card`, `_network`, `_own_folder_holds`), sandbox and cards. Nothing is pre-approved, and no
subprocess is started here. It runs in place, in the working folder, only after the protected set verifies, and the set
is hashed again right after. Its records go to a copy of the turn's (as a parallel read's do), so the worker's trace
never holds the host's run: only the verdict reads it (`host_runs`), and the next round gets what it printed."""
from __future__ import annotations

import asyncio
import json
import shlex
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class HostChecks:
    runs: tuple[dict, ...] = ()
    changed: tuple[str, ...] = ()    # protected files that changed: the goal stops at review, never complete
    accepted: tuple = ()             # every declared output accepted so far (`GoalProgress.accepted`)
    printed: str = ""                # what the runs printed, framed as tool output, for the next round
    unprotected: bool = False        # nothing protects the check: lines: never complete on them, review instead


async def _working_folder():
    from server.db import session as db_session
    from server.services import settings_service
    async with db_session.AsyncSessionLocal() as db:
        return await settings_service.workspace_dir_for_run(db)


_TIME_RESERVE_S = 30.0       # a line runs only with this much of the hard wall limit left (the command's own is less)


def room(request) -> bool:
    """L7-5g: one more host run fits: a tool call under the hard limit and the caller's tool cap (`max_tool_calls`),
    and time under the hard wall limit. Each run is admitted and charged as the model's are (`_admit`), and its
    timeout is the command's own, cut to what the budget has left (`tool_execute`); this keeps the hard limit from
    being what stops it."""
    from arslan.execution_budget import current
    budget, cap = current(), getattr(request, "max_tool_calls", None)     # the budget `_admit` charges
    return budget is None or (budget.stop_reason is None and budget.tool_calls < budget.limits.tool_calls
            and (cap is None or budget.tool_calls < cap) and budget.remaining_seconds() > _TIME_RESERVE_S)


def _is_check(item: dict, argv, root) -> bool:
    """L7-5g (b): this run_command ran exactly the check line in the working folder: its command is the line as the
    host joins it, optionally after one plain `cd <working folder> && `, with no other argument but a timeout, and it
    started (an exit code)."""
    import os
    args, result = item.get("args") or {}, item.get("result") or {}
    command = args.get("command")
    if not isinstance(command, str) or set(args) - {"command", "timeout_s"} or type(result.get("exit_code")) is not int:
        return False
    head, sep, rest = command.strip().partition(" && ")
    if sep and head.startswith("cd "):
        try:
            words = shlex.split(head)
        except ValueError:
            return False
        if len(words) != 2 or os.path.realpath(os.path.join(root, words[1])) != os.path.realpath(root):
            return False
        command = rest.strip()
    return command == shlex.join(argv)


def _ran_last(trace, argv, root) -> bool:
    """L7-5g (b): the worker's last run_command is exactly this check line, and nothing but reads came after it (any
    other command or write could have written its outputs)."""
    from server.registry import tool_defs
    reads = tool_defs.named(lambda traits: traits.effect == "read")
    for item in reversed(trace or ()):
        if not isinstance(item, dict):
            return False
        if item.get("tool") == "run_command":
            return _is_check(item, argv, root)
        if item.get("tool") not in reads:
            return False
    return False


def _stamps(root, rels) -> dict:
    import os
    out = {}
    for rel in rels:
        try:
            st = os.stat(os.path.join(root, rel), follow_symlinks=False)
            out[rel] = (st.st_ino, st.st_mtime_ns, st.st_ctime_ns)
        except OSError:
            out[rel] = None
    return out


async def run(request, state) -> HostChecks:
    """Verify, run, verify again, for each `check:` line; on a change nothing more runs."""
    from server.orchestrator.tool_loop import _run_tool, _tool_turn
    from server.orchestrator.untrusted import wrap_tool_output
    from server.services import goal_mode
    goal, runtime = request.goal, state.acceptance_runtime
    lines = [check for check in goal.checks if check.kind == "check" and not check.user_confirmed]
    accepted = runtime.progress.goal.accepted if runtime.progress.goal is not None else ()
    if not lines:
        return HostChecks(accepted=accepted)
    root = await _working_folder()
    if goal.protected is None or root is None:      # closed: a check is never run unprotected
        return HostChecks(changed=("(no protected set recorded at Start)" if root else "(no working folder)",),
                          accepted=accepted)

    async def changes(outputs=(), exempt=()):
        try:
            return await asyncio.to_thread(goal_mode.protected_changes, goal.protected, root, outputs=outputs,
                                           accepted=accepted, exempt=exempt)
        except ValueError as exc:
            return (f"({exc})",), ()
    runs, printed = [], []
    for check in lines:
        if not room(request):                       # L7-5g: a line that doesn't fit stays not run, never half run
            break
        changed, _ = await changes()
        before = {}
        if changed and check.outputs and _ran_last(getattr(state, "tool_trace", None), check.argv, root):
            # L7-5g (b): the worker's own exact run of this line wrote its declared outputs; those alone may differ,
            # and the host's run below must rewrite each one (the worker's files are never accepted as they are).
            left, _ = await changes(exempt=check.outputs)
            if not left:
                before = await asyncio.to_thread(_stamps, root, set(changed))
                changed = ()
        if not changed:
            args = {"command": shlex.join(check.argv)}
            result = await _run_tool("run_command", args, json.dumps({"tool": "run_command", "args": args}),
                                     replace(_tool_turn(request, state), tool_trace=[], convo=[], host_check=True))
            changed, new = await changes(check.outputs)
            after = await asyncio.to_thread(_stamps, root, before)
            changed = (*changed, *sorted(rel for rel, stamp in before.items()
                                         if stamp is not None and after[rel] == stamp and rel not in changed))
        if changed:
            return HostChecks(runs=tuple(runs), changed=changed, accepted=accepted)
        accepted = (*accepted, *new)
        runs.append({"tool": "run_command", "args": {**args, "argv": list(check.argv)}, "result": result})
        printed.append(f"{check.id} ({args['command'][:200]}): " + wrap_tool_output(json.dumps(
            {key: str(result.get(key))[-2000:] for key in ("exit_code", "stdout", "stderr", "error")
             if result.get(key) not in (None, "")}, ensure_ascii=False)))
    return HostChecks(runs=tuple(runs), accepted=accepted, printed="\n".join(printed),
                      unprotected=goal_mode.unprotected(goal.protected))

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
# L7-5i (the user, 11-17): a line with declared outputs runs until it settles, at most this many runs (each one admitted
# and charged, each with its own timeout, all inside `room`). A check that reveals its tests in stages writes one more
# output per run; one host run could never re-create what the worker's runs revealed (L7-7 r3, T19).
STABLE_RUNS = 10


def room(request) -> bool:
    """L7-5g: one more host run fits: a tool call under the hard limit and the caller's tool cap (`max_tool_calls`),
    and time under the hard wall limit. Each run is admitted and charged as the model's are (`_admit`), and its
    timeout is the command's own, cut to what the budget has left (`tool_execute`); this keeps the hard limit from
    being what stops it."""
    from arslan.execution_budget import current
    budget, cap = current(), getattr(request, "max_tool_calls", None)     # the budget `_admit` charges
    return budget is None or (budget.stop_reason is None and budget.tool_calls < budget.limits.tool_calls
            and (cap is None or budget.tool_calls < cap) and budget.remaining_seconds() > _TIME_RESERVE_S)


def _parent_fd(root, rel: str) -> tuple[int, str]:
    """An fd on `rel`'s folder, opened one component at a time from the working folder with O_NOFOLLOW (a symlinked
    folder on the way raises), and the file's own name."""
    import os
    *folders, name = rel.split("/")
    if not name or any(part in ("", ".", "..") for part in folders) or name in (".", ".."):
        raise OSError(f"not a plain path: {rel}")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in folders:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
    except BaseException:
        os.close(fd)
        raise
    return fd, name


def _regular(root, rel: str) -> bool:
    import os
    import stat
    try:
        fd, name = _parent_fd(root, rel)
    except OSError:
        return False
    try:
        return stat.S_ISREG(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode)
    except OSError:
        return False
    finally:
        os.close(fd)


def _clear(root, rels) -> tuple[str, ...]:
    """L7-5g (b): the host removes each of the worker's new outputs before its own runs, so none of the worker's
    bytes can be accepted (an append, a chmod or a touch by the check would otherwise keep them). Only regular files
    are removed; any other path (a symlink, a folder, a fifo) is returned, and it stops the goal as a change."""
    import os
    import stat
    refused = []
    for rel in sorted(rels):
        try:
            fd, name = _parent_fd(root, rel)
        except OSError:
            refused.append(rel)
            continue
        try:
            if not stat.S_ISREG(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode):
                refused.append(rel)
            else:
                os.unlink(name, dir_fd=fd)
        except FileNotFoundError:
            pass
        except OSError:
            refused.append(rel)
        finally:
            os.close(fd)
    return tuple(refused)


async def run(request, state) -> HostChecks:
    """Verify, run, verify again, for each `check:` line; on a change nothing more runs. L7-5i: a line with declared
    outputs runs until it settles (`STABLE_RUNS`), each run verified, and only the outputs its settled runs wrote are
    accepted."""
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
        cleared = ()
        if changed and check.outputs:
            # L7-5g (b), L7-5i: new files matching the line's declared outputs are the only change allowed. The host
            # removes them, and its own runs must write each one again: the worker's bytes are never accepted, a
            # check that needs the old file fails honestly. Whatever the worker ran or wrote (L7-5i drops (b)'s "its
            # last command was exactly the check": clearing plus host-only bytes already keep every byte the host's,
            # and an honest `; echo EXIT=$?` after the check failed 4 of 6 T19 runs in L7-7 r3).
            left, _ = await changes(exempt=check.outputs)
            if not left:
                cleared, changed = tuple(sorted(changed)), await asyncio.to_thread(_clear, root, changed)
        if changed:
            return HostChecks(runs=tuple(runs), changed=changed, accepted=accepted)
        args = {"command": shlex.join(check.argv)}
        settled, last = None, None
        for _ in range(STABLE_RUNS if check.outputs else 1):
            if last is not None and not room(request):
                return HostChecks(runs=tuple(runs), accepted=accepted, changed=(
                    f"{check.id} (its check didn't settle before the budget ran out)",))
            result = await _run_tool("run_command", args, json.dumps({"tool": "run_command", "args": args}),
                                     replace(_tool_turn(request, state), tool_trace=[], convo=[], host_check=True))
            changed, new = await changes(check.outputs)
            if changed:
                return HostChecks(runs=tuple(runs), changed=changed, accepted=accepted)
            # L7-5i: settled once two runs in a row exit the same and leave the same declared outputs, byte for byte.
            state_now = (result.get("exit_code"), tuple((item.path, item.sha256) for item in new))
            if not check.outputs or state_now == last:
                settled = new
                break
            last = state_now
        if settled is None:
            return HostChecks(runs=tuple(runs), accepted=accepted, changed=(
                f"{check.id} (its check didn't settle in {STABLE_RUNS} runs)",))
        missing = [rel for rel in cleared if not await asyncio.to_thread(_regular, root, rel)]
        if missing:
            return HostChecks(runs=tuple(runs), accepted=accepted, changed=tuple(
                f"{rel} (the check's run didn't write it again)" for rel in missing))
        accepted = (*accepted, *settled)
        runs.append({"tool": "run_command", "args": {**args, "argv": list(check.argv)}, "result": result})
        printed.append(f"{check.id} ({args['command'][:200]}): " + wrap_tool_output(json.dumps(
            {key: str(result.get(key))[-2000:] for key in ("exit_code", "stdout", "stderr", "error")
             if result.get(key) not in (None, "")}, ensure_ascii=False)))
    return HostChecks(runs=tuple(runs), accepted=accepted, printed="\n".join(printed),
                      unprotected=goal_mode.unprotected(goal.protected))

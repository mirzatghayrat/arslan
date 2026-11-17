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
STABLE_RUNS = 12             # the user, 11-17 (#991 max review r2): 10 -> 12


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


def _keep_folder(task_id: str, root):
    """L7-5i (the user, 11-17): where the outputs the host removes before its runs are kept, never deleted: a folder per
    verdict under Arslan's own data folder, which no command of the work may write. When that folder is inside the
    working folder (a working folder that holds Arslan's data), beside the runs' temp root instead, so the kept files
    are never part of the folder the check verifies."""
    import datetime
    from pathlib import Path
    from server import config
    from server.services import run_temp
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(task_id))[:120] or "goal"
    base = Path(config.data_dir()).resolve() / "goal-outputs"
    if base.is_relative_to(Path(root).resolve()):
        runs = run_temp.root()
        base = runs.parent / runs.name.replace("arslan-runs-", "arslan-goal-outputs-")
    return base / safe / stamp


KEEP_MAX = 64 * 1024 * 1024      # #991 max review r2: what one verdict keeps at most (a sparse file costs the worker 0)


def _clone(src: int, folder: int, name: str) -> bool:
    """An APFS clone of the open file `src` as `name` in the open folder `folder` (fclonefileat: instant, holes kept, no
    space); False where it isn't available (another volume, another file system, Linux)."""
    import sys
    if not sys.platform.startswith("darwin"):
        return False
    import ctypes
    import ctypes.util
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    clone = getattr(libc, "fclonefileat", None)
    return clone is not None and clone(src, folder, name.encode(), 0) == 0


def _copy(src: int, target) -> None:
    """The bytes of the open file `src` into a new `target` (never over an existing one)."""
    import os
    with os.fdopen(os.dup(src), "rb") as data, open(target, "xb") as out:
        data.seek(0)
        while chunk := data.read(1 << 20):
            out.write(chunk)


def _clear(root, rels, keep) -> tuple[tuple[str, ...], str | None]:
    """L7-5g (b): the host removes each of the worker's new outputs before its own runs, so none of the worker's
    bytes can be accepted (an append, a chmod or a touch by the check would otherwise keep them). L7-5i: removed by
    moving it into `keep` (cloned, else copied, through the fd it was opened by; then unlinked), never deleted.
    Returns (the paths not moved, a note). Only regular files are moved (opened O_NONBLOCK, so a fifo never hangs it);
    any other path, or one that can't be kept, is returned and stops the goal as a change. Over `KEEP_MAX` in all,
    nothing is moved: every path is returned, and the note says why. A failed copy leaves no partial file."""
    import os
    import stat
    opened, refused = [], []
    try:
        for rel in sorted(rels):
            try:
                fd, name = _parent_fd(root, rel)
            except OSError:
                refused.append(rel)
                continue
            try:
                src = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            except FileNotFoundError:
                os.close(fd)
                continue
            except OSError:
                os.close(fd)
                refused.append(rel)
                continue
            info = os.fstat(src)
            if not stat.S_ISREG(info.st_mode):
                os.close(src)
                os.close(fd)
                refused.append(rel)
                continue
            opened.append((rel, fd, name, src, info.st_size))
        total = sum(size for *_, size in opened)
        if total > KEEP_MAX:
            return tuple(sorted({*refused, *(rel for rel, *_ in opened)})), (
                f"(the outputs to remove come to {total} bytes, over the {KEEP_MAX} bytes kept per verdict; "
                f"nothing was moved)")
        for rel, fd, name, src, _size in opened:
            target = keep / rel
            made = False
            try:
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                if target.exists() or target.is_symlink():
                    raise FileExistsError(str(target))
                folder = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    made = _clone(src, folder, target.name)
                finally:
                    os.close(folder)
                if not made:
                    made = True                     # from here on a partial copy is ours to remove
                    _copy(src, target)
                os.unlink(name, dir_fd=fd)
            except OSError as exc:
                if made and not isinstance(exc, FileExistsError):
                    try:
                        target.unlink()
                    except OSError:
                        pass
                refused.append(rel)
        return tuple(sorted(refused)), None
    finally:
        for _rel, fd, _name, src, _size in opened:
            os.close(src)
            os.close(fd)


async def _leftovers(state) -> tuple[str, ...]:
    """L7-5i (#991 max review L1): before a line with declared outputs runs, a process the goal's commands left
    running, in any attempt of it (r2 MF1: a Resume is the same goal), could put the outputs back after the host
    removed them. Detect-only (the user, 11-18): while one is there the goal stops for review, naming it; nothing is
    signalled. Returns why nothing may run (empty: nothing is left). Fails closed: no run of the goal bound, or a
    process table it can't read, stops the goal for review."""
    from server.services import execution_context, leftover_processes, run_temp
    runtime = getattr(state, "acceptance_runtime", None)
    keys = {key for key in (execution_context.current_run_id(), *(getattr(runtime, "run_ids", None) or ()))
            if key is not None}
    try:
        keys |= await _attempt_runs(getattr(runtime, "task_id", None))
    except Exception:  # noqa: BLE001 — #991 fix-check Later 2: fail closed, as an unreadable process table does
        return ("(this goal's earlier attempts couldn't be read, so their leftover processes can't be checked)",)
    if not keys:
        return ("(no run of this goal is known, so its leftover processes can't be checked)",)
    groups, folders = run_temp.recorded(keys)
    try:
        left, unknown = await asyncio.to_thread(leftover_processes.find, groups, folders, root=run_temp.root(),
                                                keys=tuple(sorted(keys)))
    except leftover_processes.Unreadable:
        return ("(the running processes couldn't be listed, so the goal's leftover ones can't be checked)",)
    return (*_left_running(left, groups), *_unattributed(unknown, groups))


async def _attempt_runs(task_id) -> set[int]:
    """Every run of every attempt of the goal's task (`task_attempts.run_ids`). Raises when they can't be read: the
    caller fails closed."""
    if not task_id:
        return set()
    from sqlalchemy import select
    from server.db.task_models import TaskAttempt
    from server.services.task_repository import repository
    async with repository() as repo:
        rows = (await repo.db.execute(select(TaskAttempt.run_ids).where(TaskAttempt.task_id == task_id))).all()
    return {run for (runs,) in rows for run in (runs or ()) if isinstance(run, int)}


def _started_by(p, groups) -> str:
    return ((groups.get(p.pgid) or (None, None))[1] or "a command of this goal")[:160]


def _left_running(procs, groups) -> tuple[str, ...]:
    return tuple(f"(a process the work left running is still there, so its check's outputs weren't touched: pid "
                 f"{p.pid}, `{p.command[:160]}`, started by `{_started_by(p, groups)}`; end it, then resume)"
                 for p in procs)


def _unattributed(procs, groups) -> tuple[str, ...]:
    """#991 max review r2 MF2: a process in a group a command of this goal once had that can't be told apart from
    another program's (its group id may have been reused): named, never signalled."""
    return tuple(f"(a process in a group this goal's command `{_started_by(p, groups)}` had can't be told apart from "
                 f"another program's: pid {p.pid}, `{p.command[:160]}`)" for p in procs)


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
    checked = False
    keep = None
    # L7-5i: leftover processes are looked for only before the first line with declared outputs. A goal whose lines
    # declare none ("the service answers its health check") keeps the service the work started and never stops for it;
    # in a goal with both kinds, a service still running at the outputs line stops the goal for review, named.
    for check in lines:
        if not room(request):                       # L7-5g: a line that doesn't fit stays not run, never half run
            break
        if check.outputs and not checked:
            left = await _leftovers(state)
            if left:
                return HostChecks(runs=tuple(runs), changed=left, accepted=accepted)
            checked = True
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
                keep = keep or _keep_folder(getattr(runtime, "task_id", None) or "goal", root)
                cleared = tuple(sorted(changed))
                changed, note = await asyncio.to_thread(_clear, root, changed, keep)
                changed = (*changed, *((note,) if note else ()))
        moved = set(cleared) - set(changed)
        kept = (f"(the outputs it removed before its runs are kept in {keep})",) if moved else ()
        if changed:
            return HostChecks(runs=tuple(runs), changed=(*changed, *kept), accepted=accepted)
        args = {"command": shlex.join(check.argv)}
        settled, last = None, None
        for _ in range(STABLE_RUNS if check.outputs else 1):
            if last is not None and not room(request):
                return HostChecks(runs=tuple(runs), accepted=accepted, changed=(
                    f"{check.id} (its check didn't settle before the budget ran out)", *kept))
            result = await _run_tool("run_command", args, json.dumps({"tool": "run_command", "args": args}),
                                     replace(_tool_turn(request, state), tool_trace=[], convo=[], host_check=True))
            changed, new = await changes(check.outputs)
            if changed:
                return HostChecks(runs=tuple(runs), changed=(*changed, *kept), accepted=accepted)
            # L7-5i: settled once two runs in a row exit the same and leave the same declared outputs, byte for byte.
            state_now = (result.get("exit_code"), tuple((item.path, item.sha256) for item in new))
            if not check.outputs or state_now == last:
                settled = new
                break
            last = state_now
        if settled is None:
            return HostChecks(runs=tuple(runs), accepted=accepted, changed=(
                f"{check.id} (its check didn't settle in {STABLE_RUNS} runs)", *kept))
        missing = [rel for rel in cleared if not await asyncio.to_thread(_regular, root, rel)]
        if missing:
            return HostChecks(runs=tuple(runs), accepted=accepted, changed=(*(
                f"{rel} (the check's run didn't write it again)" for rel in missing), *kept))
        accepted = (*accepted, *settled)
        runs.append({"tool": "run_command", "args": {**args, "argv": list(check.argv)}, "result": result})
        printed.append(f"{check.id} ({args['command'][:200]}): " + wrap_tool_output(json.dumps(
            {key: str(result.get(key))[-2000:] for key in ("exit_code", "stdout", "stderr", "error")
             if result.get(key) not in (None, "")}, ensure_ascii=False)))
    return HostChecks(runs=tuple(runs), accepted=accepted, printed="\n".join(printed),
                      unprotected=goal_mode.unprotected(goal.protected))

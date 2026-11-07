"""The execute stage of one tool call (LOOP1 c2): the call passed every gate, so run its executor with what the gates
settled, under its limit, and turn what can go wrong into what the model is told. It records nothing: `_run_tool` does."""
from __future__ import annotations

import asyncio

from arslan.aio import within
from arslan.execution_budget import BudgetExceeded
from server.orchestrator import command_gate, parallel_reads
from server.orchestrator.turn_state import ToolTurn

# 0.1.62 F1: run_command's backstop stops this much before the turn's own timeout, so the order
# is fixed: the command's limit first (with its output), this backstop next, the turn last.
_RUN_COMMAND_BACKSTOP_RESERVE_S = 10.0
# Task-record refusals that end one call, never the turn or the job (`run_executor`): what the model is told.
_REFUSED_STEP = {
    "task_reconciliation_required": "This exact action already ran and its outcome is unknown. Do not repeat it; "
                                    "tell the user to check whether it happened.",
    "task_action_already_completed": "This exact action already succeeded in this task. Do not repeat it.",
    # D6 (K3's Claude run, T2 r2): it used to stop the whole background job.
    "task_action_arguments_not_journalable": (
        "This step did not run: its arguments can't go into the task record. They are over 256 KB, or contain "
        "something that looks like a secret (a password, key, token or cookie value). Don't put secrets in files "
        "or commands: read them from an environment variable or a file the user names. Split a very long write "
        "into several smaller ones."),
}


async def run_executor(tool_key, args, executor, plan: command_gate.CommandPlan, budget, turn: ToolTurn) -> dict:
    """Run `executor` for this call and return its result, or what the model is told instead."""
    tool_timeout_s, conversation_id, caller, turn_adapter = (
        turn.tool_timeout_s, turn.conversation_id, turn.caller, turn.turn_adapter)
    command, run_outside, by_grant, sandbox_on = plan.command, plan.run_outside, plan.by_grant, plan.sandbox_on
    unwrapped, kept_wrapped, network = plan.unwrapped, plan.kept_wrapped, plan.network
    deletes_outside, confined = plan.deletes_outside, plan.confined
    # Caller identity (brain-P2 Task 1): set ONLY around the executor call so a
    # memory-write executor can read who is calling (host vs. spawn) and fail-closed
    # (refuse) when no caller was threaded through. Reset in finally — zero residual
    # pollution across dispatches/turns, including on the exception paths below.
    from server.orchestrator import tool_caller, turn_model
    _ct = tool_caller.set_caller(caller) if caller is not None else None
    # 0.1.63 D5: the model THIS turn runs on, for web_search's choice of the provider's own search. Always set
    # (None included) so a value from an outer context can't stand in for this turn's.
    _mt = turn_model.set_model(turn_adapter)
    try:
        from server.services.task_service import current as current_task
        from server.services.task_repository import TaskError
        # S4a (⓪Plan review, fixes 2 and 3, follow-up B): the grant was read before any card and may have been taken
        # back since. Read it again now — after every card, and before the task runtime's admission fence, inside
        # which nothing is awaited (task_service.execute_tool). Gone: the command runs in the sandbox, or, where none
        # can start (switched off, seatbelt unavailable), not at all. Its ledger row is written only once the
        # executor was invoked: never for a command that did not run.
        grant_use = {"found": None, "invoked": False}
        ran_outside, result = run_outside, None
        if by_grant:
            from server.services import command_sandbox
            grant_use["found"] = await command_gate._outside_grant(conversation_id, command)
            if grant_use["found"] is None:
                ran_outside = False
                if not (sandbox_on and command_sandbox.available()):
                    result = {"ok": False, "executed": False,
                              "error": "this conversation's permission to run commands outside the sandbox was "
                                       "taken back while this one waited; it did not run",
                              "note": "Ask the user again if it is still needed."}

        async def execute(admitted_args):
            grant_use["invoked"] = True            # the executor is invoked now (no await before this line)
            # A tool that waits for the user's card or a slow app declares its own limit
            # (`timeout_s`): the default cut a Notes look mid-card on a real Mac (0.1.53).
            own = getattr(executor, "timeout_s", None)
            if tool_key == "run_command" and isinstance(own, (int, float)):
                # 0.1.62 F1: the command's own limit decides, not the loop's 20 s default.
                timeout = (max(0.0, min(float(own), budget.remaining_seconds() - _RUN_COMMAND_BACKSTOP_RESERVE_S))
                           if budget else float(own))
            else:
                timeout = (budget.remaining_seconds() if tool_key == "delegate_work" and budget
                           else max(tool_timeout_s, float(own)) if isinstance(own, (int, float)) else tool_timeout_s)
            return await within(executor.execute(admitted_args), timeout=timeout)
        runtime = current_task()

        async def run_once(outside: bool) -> dict:
            from server.services import terminal_exec
            from server.services import delete_to_trash
            token = terminal_exec.OUTSIDE_SANDBOX.set(outside)
            bare = terminal_exec.UNWRAPPED.set(outside and unwrapped)
            # SMART-8: allowed, outside the sandbox and read with certainty: its targets go to the Trash.
            trash = delete_to_trash.TRASH.set(tool_key == "run_command" and deletes_outside
                                              and (outside or not confined)
                                              and delete_to_trash.plan(command) is not None)
            # S2a-1 piece 2: offline after outside content (wrap-up may have set it too).
            cut = terminal_exec.OFFLINE.set(True) if network.get("offline") else None
            try:
                return await runtime.execute_tool(tool_key, args, execute) if runtime else await execute(args)
            finally:
                if cut is not None:
                    terminal_exec.OFFLINE.reset(cut)
                delete_to_trash.TRASH.reset(trash)
                terminal_exec.UNWRAPPED.reset(bare)
                terminal_exec.OUTSIDE_SANDBOX.reset(token)
        if result is None:
            try:
                async with parallel_reads.executing():      # K9a: the next read's gates may start now
                    result = await run_once(ran_outside)
            except asyncio.CancelledError:
                grant_use["found"] = None          # a stop: no row written while the task is being cancelled
                raise
            finally:
                found, grant_use["found"] = grant_use["found"], None
                if found is not None and grant_use["invoked"]:
                    from server.services import background_jobs, permissions
                    await permissions.note_standing(command_gate._outside_request(command), permissions.Context(
                        conversation_id, job_id=background_jobs._inside_job.get()), found)
            if by_grant and not ran_outside and isinstance(result, dict):
                result["grant_note"] = ("this conversation's permission to run commands outside the sandbox was "
                                        "taken back; it ran in the sandbox")
        # A stop goes back to the model with its note, to find another way (the calibration of 2026-11-07).
        if tool_key == "run_command" and ran_outside and isinstance(result, dict):
            result["ran_outside_sandbox"] = True
        if tool_key == "run_command" and kept_wrapped and isinstance(result, dict):
            result["kept_wrapped"] = True      # the hint names mac_applescript (recovery_hints)
        if tool_key == "run_command" and network.get("note") and isinstance(result, dict):
            result["network_note"] = network["note"]
    except TaskError as exc:
        if exc.code not in _REFUSED_STEP:
            raise
        # 0.1.44: refuse the repeat, never the turn. The model is told why. D6: a step whose
        # arguments can't go into the task record is refused alone, before it runs; the task goes on.
        result = {"ok": False, "external": False, "code": exc.code, "error": _REFUSED_STEP[exc.code]}
    except BudgetExceeded:
        raise
    except TimeoutError:
        # M2 counts the run_command wording (0.1.62 F1): keep it as it is.
        result = ({"ok": False, "code": "time_limit", "error": "stopped by the time limit; no output was captured"}
                  if tool_key == "run_command" else {"ok": False, "error": f"tool '{tool_key}' timed out"})
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "error": f"tool '{tool_key}' failed: {exc}"}
    finally:
        turn_model.reset_model(_mt)
        if _ct is not None:
            tool_caller.reset_caller(_ct)
    return result

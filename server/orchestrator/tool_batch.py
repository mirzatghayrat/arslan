"""One step's tool batch, as per-call stages (LOOP1 c3b).

`_run_native` (tool_loop.py) hands a step's tool calls here. Each call goes through its stages in today's order: the
argument check, the host tools answered by the name the model called, the on-demand unwrap, the host tools answered by
the name the gates see, the four gates (stop, wrap-up, choice card, tool budget), then the execute stage and what follows
a call. Each stage returns what happens to the call next: `Call` (it goes on), `HANDLED` (it has its record) or `Ends`
(the turn ends with this).

The table can change mid-batch (a card adds a capability), so each stage reads it on `state` when it runs, and the next
call of the same batch sees the new one. The reads planned before the first call (`StepBatch.reads`) keep the step's own
table. Values the turn stored when it opened stay as stored."""
from __future__ import annotations

import json
from dataclasses import dataclass, replace

from arslan.llm import trajectory

from server.orchestrator import on_demand, parallel_reads
from server.orchestrator.command_gate import _nobody_to_ask
from server.orchestrator.model_step import _SENT_IS_FINAL
from server.orchestrator.tool_loop import (  # tool_loop imports this module when a batch runs, not at its own import
    FINISH_TOOLS, WRAP_UP_TOOLS, _claim_results, _link_check_note, _native_tool_schemas, _parse_arguments,
    _parse_clarify_args, _progress_note, _propose_plan_change, _record_tool_result, _run_tool, _schema_problem,
    _tool_params, _tool_turn, _web_read_feedback)
from server.orchestrator.turn_state import StepMode, StepReply, TurnRequest, TurnState
from server.orchestrator.turn_stream import _progress_updates, _shown
from server.services import steering

# K9b: a call of the batch not started when the user sent a message (it is read right after these results).
SKIPPED_FOR_MESSAGE = ("Not run: the user sent a message while you were working. It comes right after these "
                       "results; read it first, then call this again only if it still makes sense.")
TRUNCATED_CALL_ERROR = (
    "The output limit was reached while writing this call's arguments; nothing was executed. "
    "Split the work: write the first part with write_file, then append each further part with "
    "edit_file (replace the file's current last line with that line plus the next part), "
    "or shorten the payload.")


@dataclass(frozen=True, slots=True)
class Call:
    """A call that goes on to the next stage, under the name and with the arguments the gates see. `on_demand_call`:
    it was reached through use_tool, or by the name of a tool this turn can run but wasn't shown (K7)."""
    name: str
    args: dict
    on_demand_call: bool = False


@dataclass(frozen=True, slots=True)
class Handled:
    """The call has its record (a refusal, or a host tool's answer): the batch goes on with its next call."""


HANDLED = Handled()


@dataclass(frozen=True, slots=True)
class Ends:
    """The call ends the turn (escalate, a valid choice card): what `run_native` returns."""
    result: dict


@dataclass(frozen=True, slots=True)
class StepBatch:
    """What every call of one batch shares, worked out before its first call."""
    reads: parallel_reads.Batch | None      # K9a, planned with the step's own table
    cut_off: bool                           # the reply hit the output limit: none of its calls runs
    wrap_up: bool
    finishing: bool
    provider_content: object                # Gemini's own reply parts, when it sent them


def _planned_read(call: dict, neutral_call: dict, wired_keys: set, params_by_key: dict) -> tuple[str, dict] | None:
    """K9a: the call's name and arguments as the batch loop will see them, when it is called by its own name
    with arguments that parse and fit its table; otherwise None (it cannot run next to others)."""
    fn = call.get("function") or {}
    name = str(fn.get("name") or "")
    args = fn.get("arguments")
    if not isinstance(args, dict):
        args, bad_json = _parse_arguments(neutral_call["arguments_raw"])
        if bad_json is not None or not isinstance(args, dict):
            return None
    if name not in wired_keys or name in ("use_tool", "find_tools"):
        return None
    if name in params_by_key and _schema_problem(args, params_by_key[name]):
        return None
    return name, args


def _read_steers(steers: list, convo: list[dict], pending: list) -> None:
    """K9b: the messages sent while the turn worked join it after the batch's results (K1's order: tool
    results, then the user's text). They become part of the turn when the next request carries them
    (_commit_steers); until then `pending` holds them, and run_native hands back what no request carried."""
    for steer in steers:
        convo.append({"role": "user", "content": steer.content})
        pending.append(steer)


async def run_batch(request: TurnRequest, state: TurnState, step: int, mode: StepMode, reply: StepReply,
                    wrap_up: bool) -> dict | None:
    """The step's tool calls, each through its stages, then what follows the batch. Returns what the turn ends with
    (escalate, a choice card), or None: the next step reads the results."""
    from server.orchestrator import agent_status
    emit, conversation_id, steerable = request.emit, request.conversation_id, request.steerable
    a, call_ids, turn_state, tool_trace = state.adapter, state.call_ids, state.recovery, state.tool_trace
    resp, stream, tool_calls = reply.resp, reply.stream, reply.tool_calls
    convo = state.convo
    provider_content = getattr(resp, "provider_content", None)
    history_start = len(convo)
    calls = trajectory.unique_ids(
        [trajectory.call_from_response(call, f"call_{step}_{index}")
         for index, call in enumerate(tool_calls)], call_ids, step)
    convo.append(trajectory.assistant(
        resp.content, calls,
        continuation=({"protocol": "gemini", "provider_content": provider_content}
                      if provider_content else getattr(resp, "continuation", None)),
        finish=getattr(resp, "finish_reason", None)))
    marks: list[tuple[int, str]] = []
    # K8b: Claude's progress updates, shown as notes before the calls they introduce; never part of the
    # answer, never spoken, not on the phone (the Bridge maps no `note`).
    for update in _progress_updates(a, resp):
        emit({"type": "note", "text": update[:400]})
    # A reply cut by the output limit may carry incomplete arguments in
    # ANY of its calls: execute none of them (0.1.49 S6).
    cut_off = getattr(resp, "finish_reason", None) == "length"
    if cut_off:
        turn_state.truncated_calls += 1
    elif any((call.get("function") or {}).get("name") != "update_plan" for call in tool_calls):
        state.tool_steps += 1
    # K9a: consecutive reads of this reply run together (parallel_reads); never in a reply cut off
    # or while wrapping up.
    reads = None if cut_off or wrap_up else await parallel_reads.plan(
        [_planned_read(call, neutral_call, state.wired_keys, state.params_by_key)
         for call, neutral_call in zip(tool_calls, calls)])
    batch = StepBatch(reads=reads, cut_off=cut_off, wrap_up=wrap_up, finishing=mode.finishing,
                      provider_content=provider_content)
    steered = False                     # K9b: a message sent meanwhile waits: the rest is not started
    for index, (call, neutral_call) in enumerate(zip(tool_calls, calls)):
        marks.append((len(convo), neutral_call["id"]))
        fn = call.get("function") or {}
        name = str(fn.get("name") or "")
        # K9b: the boundary after the previous call (or group of reads): a message sent meanwhile is
        # read before anything else runs. A call not started is not run, and still gets a result. The
        # message is taken after the batch, right as it is read (nothing can fall between the two).
        # A reply cut off by the output limit runs none of its calls and reads nothing after them: each
        # keeps its truncation note.
        if not steered and index and steerable and conversation_id and not cut_off \
                and steering.waiting(conversation_id):
            steered = True
        if steered and not (reads is not None and reads.has(index)):
            _record_tool_result(name, {}, {"ok": False, "external": False, "code": "skipped_for_message",
                                           "error": SKIPPED_FOR_MESSAGE},
                                emit, tool_trace, json.dumps({"tool": name, "args": {}}), convo)
            continue
        verdict = await _one_call(request, state, batch, index, name, fn, neutral_call)
        if isinstance(verdict, Ends):
            return verdict.result
    # Each handled call appended one record; bind them to the call ids. The
    # Gemini provider pair and the old "invocation completed" text are now
    # renderings of this trajectory (trajectory.to_legacy), not rewrites.
    _claim_results(convo, marks)
    if steerable and conversation_id and not cut_off:
        # The boundary after the batch: what waits joins the turn (no await between take and read).
        _read_steers(steering.take(conversation_id), convo, state.steers)
    # resp.content is narration — surface it as an ephemeral note ONLY, never final. K8a: unless it
    # passed the window and went out as the answer, where it stays (and in the stored answer).
    narration = agent_status.strip_echo((resp.content or "").strip())
    if narration and not (stream is not None and stream.released):
        emit({"type": "note", "text": narration[:400]})
    state.pending_feedback = len(convo) - history_start
    return None


async def _one_call(request: TurnRequest, state: TurnState, batch: StepBatch, index: int, name: str, fn: dict,
                    neutral_call: dict) -> Handled | Ends:
    """One call through its stages, in today's order. The first stage that answers the call is its last."""
    verdict = _check_arguments(request, state, batch, name, fn, neutral_call)
    if not isinstance(verdict, Call):
        return verdict
    host = _BEFORE_UNWRAP.get(verdict.name)          # by the name the model called
    verdict = verdict if host is None else await host(request, state, verdict)
    if not isinstance(verdict, Call):
        return verdict
    verdict = await _unwrap(request, state, verdict)
    if not isinstance(verdict, Call):
        return verdict
    call = verdict
    # A neutral trace record, not a prompt-level execution protocol.
    assistant_content = json.dumps({"tool": call.name, "args": call.args}, ensure_ascii=False)
    host = _AFTER_UNWRAP.get(call.name)              # by the name the gates see
    verdict = call if host is None else await host(request, state, call, assistant_content)
    if not isinstance(verdict, Call):
        return verdict
    ran = batch.reads is not None and batch.reads.has(index)    # K9a: it already ran with the reads next to it
    verdict = _stop_gate(request, state, batch, call, ran)
    if not isinstance(verdict, Call):
        return verdict
    verdict = _wrap_gate(request, state, batch, call)
    if not isinstance(verdict, Call):
        return verdict
    verdict = _choice_card(request, state, call, assistant_content)
    if not isinstance(verdict, Call):
        return verdict
    verdict = _budget_gate(request, state, call, ran)
    if not isinstance(verdict, Call):
        return verdict
    result = await _execute(request, state, batch, index, call, assistant_content)
    await _after_call(request, state, batch, call, result)
    return HANDLED


def _check_arguments(request: TurnRequest, state: TurnState, batch: StepBatch, name: str, fn: dict,
                     neutral_call: dict) -> Call | Handled:
    """The call's arguments, parsed when they came as text. Refused: every call of a reply cut off by the output
    limit, arguments that aren't a JSON object, and arguments that don't fit the tool's table (read at this call)."""
    emit, tool_trace, convo, policy, cut_off = request.emit, state.tool_trace, state.convo, state.policy, batch.cut_off
    args = fn.get("arguments")
    bad_json = None
    if not isinstance(args, dict) and not cut_off:
        args, bad_json = _parse_arguments(neutral_call["arguments_raw"])
    if not isinstance(args, dict):
        args = {}
    if cut_off:
        result = _record_tool_result(name, {}, {"ok": False, "external": False, "code": "output_truncated",
            "error": TRUNCATED_CALL_ERROR}, emit, tool_trace, json.dumps({"tool": name, "args": {}}), convo)
        policy.observe(name, {}, result)
        return HANDLED
    if bad_json is not None:
        result = _record_tool_result(name, {}, {"ok": False, "external": False,
            "code": "invalid_arguments_json",
            "error": f"The arguments for {name} were not valid JSON ({bad_json}); nothing was "
                     "executed. Send the call again with a JSON object."},
            emit, tool_trace, json.dumps({"tool": name, "args": {}}), convo)
        policy.observe(name, {}, result)
        return HANDLED
    schema_problem = (_schema_problem(args, state.params_by_key.get(name)) if name in state.params_by_key
                      else None)
    if schema_problem:
        result = _record_tool_result(name, args, {"ok": False, "external": False,
            "code": "invalid_arguments",
            "error": f"Invalid arguments for {name}: {schema_problem}. Nothing was executed; "
                     "send the call again with corrected arguments."},
            emit, tool_trace, json.dumps({"tool": name, "args": args}, ensure_ascii=False), convo)
        policy.observe(name, args, result)
        return HANDLED
    return Call(name, args)


# ---- host tools answered by the name the model called, before the on-demand unwrap ----

async def _escalate(request: TurnRequest, state: TurnState, call: Call) -> Call | Ends:
    """escalate ends the turn with the need it names, where the caller allows it."""
    allow_escalation, turn_text, tool_trace = request.allow_escalation, state.turn_text, state.tool_trace
    name, args = call.name, call.args
    if name == "escalate" and allow_escalation:
        return Ends({"final": _shown(turn_text), "tool_trace": tool_trace,
                     "escalation": {"kind": str(args.get("kind") or "data"),
                                    "need": str(args.get("need") or "").strip(),
                                    "context": str(args.get("context") or "").strip()}})
    return call


async def _find_tools(request: TurnRequest, state: TurnState, call: Call) -> Call | Handled:
    """K7: find_tools ranks what this turn can run but was not shown."""
    emit, tool_trace, convo, policy, resolve_callable = (
        request.emit, state.tool_trace, state.convo, state.policy, state.resolve_callable)
    name, args = call.name, call.args
    if name == "find_tools" and "find_tools" in state.wired_keys:
        emit({"type": "tool_call", "tool": name, "args_summary": json.dumps(args, ensure_ascii=False)[:200]})
        unseen = [t for t in await resolve_callable() if t["key"] not in state.wired_keys]
        result = _record_tool_result(name, args, on_demand.find(str(args.get("query") or ""), unseen, _tool_params),
                                     emit, tool_trace, json.dumps({"tool": name, "args": args}, ensure_ascii=False),
                                     convo)
        policy.observe(name, args, result)
        return HANDLED
    return call


_BEFORE_UNWRAP = {"escalate": _escalate, "find_tools": _find_tools}


async def _unwrap(request: TurnRequest, state: TurnState, call: Call) -> Call | Handled:
    """K7: use_tool, or a direct call of a tool this turn can run but was not shown, goes on under the tool's real
    name once its arguments check out against its own table, so the approval, the trace and the receipts are a
    direct call's. This decides which name the gates see."""
    emit, confirm_command, conversation_id = request.emit, request.confirm_command, request.conversation_id
    tool_trace, convo, policy, resolve_callable = state.tool_trace, state.convo, state.policy, state.resolve_callable
    name, args, on_demand_call = call.name, call.args, call.on_demand_call
    if (name == "use_tool" and str(args.get("name") or "").strip() == "run_command"
            and _nobody_to_ask(confirm_command)):
        # v0.1.63: refused (and listed) as a direct call is, not "no tool named run_command".
        inner = args.get("arguments")
        name, args = "run_command", inner if isinstance(inner, dict) else {}
    elif "use_tool" in state.wired_keys and (name == "use_tool" or name not in state.wired_keys):
        reachable = {t["key"]: t for t in await resolve_callable()}
        if name == "use_tool" or name in reachable:
            wanted = args if name == "use_tool" else {"name": name, "arguments": args}
            real, inner, refusal = on_demand.unwrap(wanted, reachable, state.wired_keys, _tool_params,
                                                    _schema_problem)
            if refusal is not None:
                result = _record_tool_result(name, args, refusal, emit, tool_trace,
                                             json.dumps({"tool": name, "args": args}, ensure_ascii=False), convo)
                policy.observe(name, args, result)
                return HANDLED
            name, args, on_demand_call = real, inner, True
            on_demand.note_used(on_demand.conversation(conversation_id), name)
    return Call(name, args, on_demand_call)


# ---- host tools answered by the name the gates see, after the unwrap ----

async def _plan_change(request: TurnRequest, state: TurnState, call: Call, assistant_content: str) -> Call | Handled:
    """0.1.50 S2: the plan is host bookkeeping — no executor, no tool budget, no progress signal; allowed during
    wrap-up too."""
    emit, tool_trace, convo = request.emit, state.tool_trace, state.convo
    name, args, on_demand_call = call.name, call.args, call.on_demand_call
    if name == "propose_plan_change" and (name in state.wired_keys or on_demand_call):
        # 0.1.56 §7: bookkeeping like update_plan — the proposal waits for the
        # user on a card; nothing in the plan changes here.
        emit({"type": "tool_call", "tool": name,
              "args_summary": json.dumps(args, ensure_ascii=False)[:200]})
        outcome = await _propose_plan_change(args, emit)
        _record_tool_result(name, args, outcome, emit, tool_trace, assistant_content, convo)
        return HANDLED
    return call


async def _capability_card(request: TurnRequest, state: TurnState, call: Call,
                           assistant_content: str) -> Call | Handled:
    """The install, save-a-skill and memory import cards, asked in this window only."""
    emit, allow_escalation, confirm_command, conversation_id = (
        request.emit, request.allow_escalation, request.confirm_command, request.conversation_id)
    tool_trace, convo, resolve_tools = state.tool_trace, state.convo, state.resolve_tools
    name, args, on_demand_call = call.name, call.args, call.on_demand_call
    if name in ("propose_capability", "create_skill", "import_memories") and (name in state.wired_keys
                                                                               or on_demand_call):
        # 0.1.57 §3: the install-and-retry card; v0.1.64 CAP2a: the save-a-skill card, on the
        # same channel (DELETE-BY: v0.1.65, when "for you to look at" takes a written skill); CAP8b: the
        # memory import card. A blocking ask in THIS window (confirm_command carries it); a job or a
        # turn nobody watches adds nothing. On success the tools are read again, so the new
        # capability (or read_skill's list) is there for the rest of this turn.
        emit({"type": "tool_call", "tool": name,
              "args_summary": json.dumps(args, ensure_ascii=False)[:200]})
        from server.services import background_jobs, capability_flow, memory_import, skill_forge
        ask = None if background_jobs.inside_job() else getattr(confirm_command, "ask_capability", None)
        if name == "create_skill":
            outcome = await skill_forge.propose(args, conversation_id=conversation_id, ask=ask)
        elif name == "import_memories":
            outcome = await memory_import.propose(args, conversation_id=conversation_id, ask=ask)
        else:
            outcome = await capability_flow.propose(args, conversation_id=conversation_id, ask=ask,
                                                    emit=emit)
        refresh = bool(outcome.pop("refresh", False))
        _record_tool_result(name, args, outcome, emit, tool_trace, assistant_content, convo)
        if refresh:
            state.wired = await resolve_tools()
            state.wired_keys = {t["key"] for t in state.wired}
            state.schemas = _native_tool_schemas(state.wired, allow_escalation=allow_escalation)
            state.params_by_key = {t["key"]: _tool_params(t) for t in state.wired}
        return HANDLED
    return call


async def _update_plan(request: TurnRequest, state: TurnState, call: Call, assistant_content: str) -> Call | Handled:
    """The turn's own plan (turn_plan), shown on the island."""
    emit, tool_trace, convo, plan = request.emit, state.tool_trace, state.convo, state.plan
    name, args = call.name, call.args
    if name == "update_plan" and "update_plan" in state.wired_keys:
        emit({"type": "tool_call", "tool": name,
              "args_summary": json.dumps(args, ensure_ascii=False)[:200]})
        outcome = plan.update(args)
        _record_tool_result(name, args, outcome, emit, tool_trace, assistant_content, convo)
        if outcome.get("ok"):
            from server.services import desktop_status
            desktop_status.note_plan(plan.items)
        return HANDLED
    return call


_AFTER_UNWRAP = {"propose_plan_change": _plan_change, "propose_capability": _capability_card,
                 "create_skill": _capability_card, "import_memories": _capability_card, "update_plan": _update_plan}


# ---- the gates, in their order: stop, wrap-up, choice card, tool budget ----

def _stop_gate(request: TurnRequest, state: TurnState, batch: StepBatch, call: Call, ran: bool) -> Call | Handled:
    """After repeated work without progress only the save tools run, and only while finishing."""
    emit, tool_trace, convo, policy = request.emit, state.tool_trace, state.convo, state.policy
    finishing, wrap_up, name = batch.finishing, batch.wrap_up, call.name
    if policy.stopped and not (finishing and name in FINISH_TOOLS) and not ran:
        state.wrap_refused += bool(wrap_up)
        _record_tool_result(name, {}, {"ok": False, "external": False,
            "code": "task_no_progress", "error": "Execution paused after repeated work without progress."},
            emit, tool_trace, json.dumps({"tool": name, "args": {}}), convo)
        return HANDLED
    return call


def _wrap_gate(request: TurnRequest, state: TurnState, batch: StepBatch, call: Call) -> Call | Handled:
    """Wrapping up: only the save tools and run_command run."""
    emit, tool_trace, convo, offline_note = request.emit, state.tool_trace, state.convo, state.offline_note
    wrap_up, name = batch.wrap_up, call.name
    if wrap_up and name not in FINISH_TOOLS:
        state.wrap_refused += 1
        _record_tool_result(name, {}, {"ok": False, "external": False, "code": "wrap_up",
            "error": "Wrapping up: no more research. Write the deliverable from what you have."
                     + offline_note},
            emit, tool_trace, json.dumps({"tool": name, "args": {}}), convo)
        return HANDLED
    return call


def _choice_card(request: TurnRequest, state: TurnState, call: Call, assistant_content: str) -> Call | Handled | Ends:
    """PA-3 terminal tool: a VALID ask_user_choice call ends the turn — the
    caller emits the clarify_options card and waits for the user's click.
    Gated on the RESOLVED toolset so loops that don't wire it (spawns)
    fall through to the normal "tool not available" dispatch error."""
    emit, tool_trace, convo, policy, runtime, turn_text = (
        request.emit, state.tool_trace, state.convo, state.policy, state.runtime, state.turn_text)
    name, args = call.name, call.args
    if name == "ask_user_choice" and "ask_user_choice" in state.wired_keys:
        clarify, err = _parse_clarify_args(args)
        if err is not None:
            result = _record_tool_result(
                name, args, {"ok": False, "external": False, "error": err},
                emit, tool_trace, assistant_content, convo)
            policy.observe(name, args, result)
            return HANDLED
        if runtime:
            runtime.pause_reason = "task_input_required"
        return Ends({"final": _shown(turn_text), "escalation": None, "clarify": clarify,
                     "tool_trace": tool_trace})
    return call


def _budget_gate(request: TurnRequest, state: TurnState, call: Call, ran: bool) -> Call | Handled:
    """The batch crossed the hard tool budget: record the rest as not run and let the next step (forced) deliver
    what was gathered, instead of aborting the turn with an empty reply."""
    emit, tool_trace, convo, budget, name = request.emit, state.tool_trace, state.convo, state.budget, call.name
    if budget.tool_calls >= budget.limits.tool_calls and not ran:
        _record_tool_result(name, {}, {"ok": False, "external": False,
            "code": "task_budget_exhausted",
            "error": "The tool budget for this turn is used up: this call did not run. "
                     "Answer with what you already have."},
            emit, tool_trace, json.dumps({"tool": name, "args": {}}), convo)
        return HANDLED
    return call


# ---- execute, and after ----

async def _execute(request: TurnRequest, state: TurnState, batch: StepBatch, index: int, call: Call,
                   assistant_content: str) -> dict:
    """The call through `_run_tool` and every gate there, or its result from the reads that ran together (K9a). A
    command run while wrapping up runs offline."""
    emit, tool_trace, convo, budget, reads = request.emit, state.tool_trace, state.convo, state.budget, batch.reads
    wrap_up, name, args = batch.wrap_up, call.name, call.args
    from server.services import terminal_exec
    offline = terminal_exec.OFFLINE.set(True) if wrap_up and name == "run_command" else None
    try:
        turn = _tool_turn(request, state)
        if reads is not None and reads.launchable(index):
            await reads.run(index, lambda key, arguments, **own: _run_tool(
                key, arguments, json.dumps({"tool": key, "args": arguments}, ensure_ascii=False),
                replace(turn, **own)),
                exhausted=lambda: budget.tool_calls >= budget.limits.tool_calls)
        if reads is not None and reads.has(index):
            result = reads.take(index, emit=emit, tool_trace=tool_trace, convo=convo)
        else:
            result = await _run_tool(name, args, assistant_content, turn)
    finally:
        if offline is not None:
            terminal_exec.OFFLINE.reset(offline)
    return result


async def _after_call(request: TurnRequest, state: TurnState, batch: StepBatch, call: Call, result: dict) -> None:
    """What follows a call that ran: the progress check, the link check of a saved table, the web reads kept for a
    later compaction, and the lane's progress."""
    tool_trace, convo, policy, runtime = state.tool_trace, state.convo, state.policy, state.runtime
    research_source_feedback, link_hints = state.research_source_feedback, state.link_hints
    provider_content, name, args = batch.provider_content, call.name, call.args
    if not policy.observe(name, args, result) and policy.count >= 2 and convo \
            and convo[-1].get("role") == "tool":
        convo[-1]["content"] += _progress_note(policy)
    # 0.1.50: a saved table of links gets the host link check (link_check).
    if name in WRAP_UP_TOOLS and result.get("ok") is True and convo \
            and convo[-1].get("role") == "tool":
        note = await _link_check_note(name, args, result, tool_trace, link_hints)
        if note:
            convo[-1]["content"] += note
    if not provider_content:
        if name == "web_extract" and _web_read_feedback(name, args, result) is not None:
            research_source_feedback.append((convo[-1], result))
        elif (name == "write_file" and result.get("ok") is True and not _SENT_IS_FINAL.get()
              and len(research_source_feedback) >= 2
              and str(args.get("path", "")).lower().endswith((".md", ".txt"))):
            # K3b: never on a provider that clears old results itself (Claude's native path):
            # editing what was sent sends the prompt cache back to the system prompt, and the
            # request rewrites the whole history (45k tokens in K3's Claude run, T2 r1).
            from server.orchestrator import saved_context
            state.history_compacted = saved_context.compact_saved_context(
                convo, research_source_feedback, args.get("content")) or state.history_compacted
    if runtime:
        runtime.progress = runtime.progress.model_copy(update={
            "loop_fingerprints": tuple(sorted(policy.seen))[-256:]})
        await runtime.checkpoint("loop_progress")

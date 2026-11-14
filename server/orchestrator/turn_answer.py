"""A step's answer (LOOP1 c3c): the reply of a step that called no tool, or of the forced step, through its guards.

`_run_native` (tool_loop.py) hands such a step here. The answer is checked in today's order: a capability it denies the
turn had, a claim without a receipt or a promise of action (bounced back to the model, a bounded number of times), then
H3's "handed back" check when its switch is on (finish_check.py), then a reply that can't stand (replaced from the
findings, salvaged, or kept as shown), then the task's acceptance checks
(one bounded repair, or the failed checks said). `finish` returns what the turn ends with, or None when a correction or
a repair went back to the model: the next step answers it."""
from __future__ import annotations

import hashlib
import json

from arslan.llm import trajectory

from server.orchestrator import finish_check
from server.orchestrator.answer_guards import _embeds_protocol, _is_deferral_stub, _unverified_claim
from server.orchestrator.answer_salvage import (
    _chat_miss_message, _fallback_with_digest, _salvage_plain, _synthesize_from_findings)
from server.orchestrator.turn_state import StepMode, StepReply, TurnRequest, TurnState
from server.orchestrator.turn_stream import _UNVERIFIED_BOUNCES, _correct, _kept_note, _not_verified


async def finish(request: TurnRequest, state: TurnState, mode: StepMode, reply: StepReply) -> dict | None:
    """The step's answer, or None: a correction or a repair went back to the model, and the next step answers it."""
    from server.orchestrator import agent_status
    user_content, on_chunk = request.user_content, request.on_chunk
    # Set once when the turn opened and never rebound.
    a, acceptance_runtime, system, turn_state, tool_trace, turn_text = (
        state.adapter, state.acceptance_runtime, state.system, state.recovery, state.tool_trace, state.turn_text)
    forced = mode.forced
    resp, stream, tool_calls = reply.resp, reply.stream, reply.tool_calls
    convo = state.convo                 # rebound only when the history is fitted, before the request
    # No tool calls (or forced) → resp.content should be the FINAL answer. GUARD: the model
    # (esp. on the forced step) may ignore "answer now" and instead narrate or write a TEXT
    # tool-call in its content. Never surface that. Salvage once with a hard no-tools prompt,
    # then synthesize from the accumulated TOOL RESULTs so we NEVER end empty or with a fake
    # tool-call. Native content separation alone does not prevent malformed output.
    # Even a provider ignoring tools=None still marks narration with tool_calls.
    # Never turn that narration into a final answer on a forced synthesis step.
    final_text = "" if tool_calls else agent_status.strip_echo((resp.content or "").strip())
    # The reply's continuation replays its own text verbatim (Claude: byte for byte); once the host
    # changed that text (an echo stripped, tool-call text replaced) it goes, as at the repair below.
    own_continuation = getattr(resp, "continuation", None) if final_text == (resp.content or "").strip() else None
    streamed = stream is not None and stream.released          # K8a: this step's text already went out
    claimed = _unverified_claim(final_text, tool_trace, state.wired_keys)
    deferred = _is_deferral_stub(final_text)
    protocol_text = _embeds_protocol(final_text) or (stream is not None and stream.stopped)
    # 0.1.50: an answer that denies a capability this turn had (bench: "no file
    # write ability" with write_file offered) gets one correction.
    from server.orchestrator import capability_truth
    denied = (None if forced or turn_state.capability_bounced or claimed or deferred or protocol_text
              else capability_truth.denied_capability(final_text, state.wired_keys, tool_trace))
    if denied:
        turn_state.capability_bounced = True
        await _correct(turn_text, streamed)
        convo.extend([trajectory.assistant(final_text, continuation=own_continuation),
                      {"role": "user", "content": capability_truth.correction(denied, state.wired_keys)}])
        return None
    if not forced and (claimed or ((deferred or protocol_text) and state.wired_keys)) \
            and turn_state.unverified_bounces < _UNVERIFIED_BOUNCES:
        turn_state.unverified_bounces += 1
        await _correct(turn_text, streamed)
        # Never execute rescued JSON, nor echo a malformed invocation back
        # as an example to imitate. Permit a new structured call only through
        # the normal tool resolver, permission gate and existing budgets.
        convo.extend([trajectory.assistant(
            "Non-executable tool-call text omitted." if protocol_text else final_text,
            continuation=None if protocol_text else own_continuation), {"role": "user", "content":
            ("The proposed answer was tool-call text, not a native tool request; it executed no action. " if protocol_text else
             f"The proposed answer lacks a successful {claimed} receipt. " if claimed else
             "The proposed answer only promises future action. ") +
            "Use an available native tool if needed, or give an honest answer stating the limitation. "
            "Do not claim an action or artifact exists without evidence. Do not output tool-call JSON as text."}])
        return None
    # H3 (`harness_finish_check`, default off): an answer that hands work back to the user, or leaves out a step that
    # was declined or blocked, goes back once. Only the model's own answer: one the guards above would replace isn't.
    if final_text and not (protocol_text or deferred or claimed) and (
            note := await finish_check.check(request, state, mode, final_text)):
        await _correct(turn_text, streamed)
        convo.extend([trajectory.assistant(final_text, continuation=own_continuation),
                      {"role": "user", "content": note}])
        return None
    # A clean answer is prose. Reject content that is / embeds a tool-call or escalate object
    # (DeepSeek writes "Let me search…{\"tool\":…}" when it wants to keep going but can't), or a
    # SHORT deferral stub that promises action without delivering. A long, substantive answer is
    # KEPT even if it mentions action verbs — describing capabilities ("我能搜索、画图表") is not a
    # deferral (live bug: capability answers were bounced to the digest/「继续」 floor). When rejected,
    # repair — but HOW depends on whether any tool actually ran this turn:
    #   • tool_trace non-empty  → a real research round: synthesize the answer from the gathered
    #     findings (may honestly fall to a findings-digest + 「继续」 nudge — work WAS done).
    #   • tool_trace EMPTY      → a chat/meta turn (or a first-step narration stub). There are NO
    #     findings and NOTHING is unfinished, so the "还没做完，回复继续" research nudge would be a
    #     lie. Salvage a direct plain-text answer instead.
    replaced = (not final_text) or protocol_text or deferred or claimed
    if replaced:
        from server.services import runtime_messages
        notice_locale = await runtime_messages.selected_locale()
        await _correct(turn_text, streamed)
        replacement = (await _synthesize_from_findings(a, system, user_content, tool_trace, or_none=True)
                       if tool_trace else await _salvage_plain(a, system, user_content))
        if replacement and _unverified_claim(replacement, tool_trace, state.wired_keys):
            replacement = None
        if replacement:
            final_text = replacement
        elif turn_text is not None and turn_text.pending is not None:
            # K8a (#694 review): nothing usable replaces what the user saw, so it stays, with one note.
            turn_text.keep_shown()
            final_text = await _kept_note(turn_text)
        else:
            final_text = (_fallback_with_digest(user_content, tool_trace, locale=notice_locale)
                          if tool_trace else _chat_miss_message(user_content, locale=notice_locale))
    # K8a: what is still to be shown at the end (nothing when this step's text already went out), and
    # the whole answer as the user will have read it.
    to_show = final_text if replaced or not streamed else ""
    answer = final_text if turn_text is None else turn_text.after(to_show)
    if acceptance_runtime is not None:
        from server.services import task_validation
        report = await task_validation.validate_output(acceptance_runtime, answer, tool_trace, model_adapter=a)
        validation_failures = task_validation.failures(report)
        if validation_failures:
            repair_fingerprint = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
            prior_repairs = acceptance_runtime.progress.validation_repairs
            links = task_validation.unverified_links(answer, report)
            if not forced and len(prior_repairs) < 2 and repair_fingerprint not in prior_repairs:
                acceptance_runtime.progress = acceptance_runtime.progress.model_copy(update={
                    "validation_repairs": (*prior_repairs, repair_fingerprint)})
                await acceptance_runtime.checkpoint("validation_repair")
                if streamed and links:      # K8a Q1: what went out is never rewritten; the repair follows
                    await _not_verified(turn_text, links)
                # The reply's continuation belongs to its own text only; a
                # synthesized/salvaged answer came from another request.
                own = final_text == (resp.content or "").strip()
                convo.extend([trajectory.assistant(
                    final_text, continuation=getattr(resp, "continuation", None) if own else None),
                              {"role": "user", "content":
                    "Deterministic validation failed: " + "; ".join(validation_failures)[:3000] +
                    ". Repair only within the existing task scope, permissions and remaining budget. "
                    "Do not repeat successful or uncertain external writes. If repair is unavailable, "
                    "state the failed checks and remaining work; do not claim acceptance."}])
                return None
            acceptance_runtime.pause_reason = "task_validation_failed"
            if turn_text is not None and (streamed or turn_text.parts):
                turn_text.append(to_show)           # K8a Q1: appended to, never rewritten
                to_show = ""
                await _not_verified(turn_text, links)
            else:
                final_text = task_validation.failure_output(final_text, report, acceptance_runtime.spec.locale)
    if turn_text is not None and (streamed or turn_text.parts):
        turn_text.append(to_show)
        return {"final": turn_text.text, "escalation": None, "tool_trace": tool_trace,
                "stop_reason": state.stop_reason, "history_compacted": state.history_compacted}
    if final_text:
        on_chunk(final_text)
    return {"final": final_text, "escalation": None, "tool_trace": tool_trace,
            "stop_reason": state.stop_reason, "history_compacted": state.history_compacted}

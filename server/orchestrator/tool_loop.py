"""Budget-governed native execution and shared tool/evidence safety boundaries."""
from __future__ import annotations

import asyncio
import json
import logging
import os

from arslan.execution_budget import BudgetExceeded, governed
from arslan.llm import tool_names, trajectory, usage_sink
from arslan.runtime_policy import ProgressPolicy, bounded_history

from server.orchestrator import run_trace
from server.orchestrator.answer_salvage import _CHAT_TIMEOUT_S
from server.orchestrator import command_gate, on_demand, tool_execute, tool_gates, turn_answer, turn_context
from server.orchestrator.command_gate import _scheduled_command_refused, refuses_commands
from server.orchestrator.model_step import (
    _SENT_IS_FINAL, _SchemaDrops, _context_parts, _hiding, _model_call, _rendered_size, _server_trims)
from server.orchestrator.turn_stream import TextShown, _StepStream, _TurnText, _streams_answer
from server.orchestrator.turn_state import (  # noqa: F401
    TOOL_TIMEOUT_S, ResolveTools, StepMode, StepReply, ToolTurn, TurnRequest, TurnState)
from server.orchestrator.untrusted import GUARD_NOTE, wrap_external
from server.registry import tool_defs
from server.registry.executors import EXECUTORS, resolve_executor
from server.services.llm_factory import build_adapter
from server.services.replay_safety import _check_fetch_budget

logger = logging.getLogger(__name__)

# The in-turn history's bound on a provider that doesn't clear old results itself (rendered characters).
# K4a gate (⓪Plan's DeepSeek run, T2): over the bound, the history is trimmed to half of it in one go.
# Trimmed back under the bound one message at a time, the start of the history changed on every step,
# and the provider's prefix cache missed everything after the system prompt (about 60k uncached tokens a
# step); now the cache breaks once per chunk and the steps in between only append (the K3b family).
_IN_TURN_CHARS = 64_000
_IN_TURN_CHARS_RESEARCH = 96_000
# Each built-in tool by name: `_run_tool` looks its gate up here (`Tool.gate`, LOOP1 c2).
_BUILT_IN = {tool.name: tool for tool in tool_defs.TOOLS}
# The T1 write tools, gated as a category (P1b): the tools whose gate is the write card. The tool
# list in _arslan_tools decides what is OFFERED, `Tool.gate` decides what is GATED, and a writer
# without the write card's gate would be a silently ungated writer (test_workspace_tool_gate).
_WORKSPACE_WRITE_TOOLS = frozenset(name for name, tool in _BUILT_IN.items()
                                   if tool.gate in (tool_gates.workspace_write, tool_gates.file_arguments_then_write))



def _get_adapter():
    """Indirection so tests can stub adapter construction."""
    return build_adapter(role="execute")


async def _adapter_for_turn(*, has_images: bool, conversation_id: str | None = None):
    """The adapter for this turn, honouring the vision slot ONLY when it carries an image.

    🔴 THE `has_images` CONDITION IS THE WHOLE POINT, not an optimization. Ruling ②B
    chose an explicit vision slot over gating on a capability flag, because that flag is
    hardcoded True for every Anthropic model, never set for Gemini or any
    OpenAI-compatible provider, and toggleable in localStorage where nothing
    server-side reads it — gating on it would block Gemini entirely while waving through
    models that cannot see. Explicit beats guessing.

    But "explicit" only holds if it applies where the user meant it. Without this
    condition, setting a vision model would silently move EVERY turn onto it — the
    silent model swap this spec exists to remove, arriving through the feature meant to
    prevent it. Image on this turn, the slot applies; no image, the ordinary execute
    adapter, unchanged.

    This does NOT gate on whether the chosen model can actually see. That decision stays
    where server/orchestrator/vision_errors.py left it: send, and make the failure
    legible.
    """
    # 0.1.58 §6: the model chosen for this conversation, when there is one. v0.1.64 (⓪Plan's Q2, option c): it wins
    # on an image turn too, over the vision slot. The user said "this chat runs on X"; if X can't read the image, its
    # refusal names X and its provider (llm_errors.error_frame) and the window offers to switch. Whether a model can
    # see is not known on this path (ModelCatalogCache is never read here, and the vision flag is unreliable).
    if conversation_id:
        from server.services.llm_factory import build_conversation_adapter
        try:
            chosen = await build_conversation_adapter(conversation_id)
        except Exception:  # noqa: BLE001 — a broken choice must never take the turn down
            chosen = None
        if chosen is not None:
            return chosen
    if has_images:
        from server.services.llm_factory import build_slot_adapter

        slotted = await build_slot_adapter("vision_config_id")
        if slotted is not None:
            return slotted
    adapter = _get_adapter()
    return await adapter if hasattr(adapter, "__await__") else adapter


def _summarize_result(result: dict) -> str:
    if not result.get("ok"):
        return str(result.get("error") or "failed")
    if result.get("summary"):
        return str(result["summary"])
    if "results" in result:
        return f"{len(result['results'])} results"
    if "text" in result:
        return f"{len(result['text'])} chars extracted"
    return "ok"


# PB-3: turn-scoped MCP degradation. When an `mcp_*` tool fails this many times
# CONSECUTIVELY within one run_native invocation, its recorded tool result gains a
# deterministic hint steering the model to the equivalent BUILTIN tool. Guide, never
# hard-switch — the model stays free to disagree. 条件2: the counter dict lives in
# run_native's locals (a fresh invocation = a fresh turn = count 0), and a success
# resets that tool's streak.
_MCP_FAIL_HINT_AT = 2


def _mcp_degrade_hint(n: int) -> str:
    return (f"⚠ This MCP tool has failed {n} times in a row this turn. Use the equivalent built-in tool "
            "instead (web_extract to read a page, web_search to search); do not retry this MCP tool.")


def _web_read_feedback(tool_key, args, result):
    """Keep bounded read text AND its receipt intact across model transport.

    Generic tool JSON still has its historical cap. Valid web receipts need a
    larger, structured envelope; slicing their JSON hid both text and provenance.
    Escape-heavy inputs are shortened before hashing/logging, with partial status.
    """
    if tool_key != "web_extract":
        return None
    from arslan.companion.research import admitted_sources, receipt
    from server.registry.net_pin import _MAX_EXTRACT_CHAR_LIMIT
    sources = admitted_sources([{"tool": tool_key, "args": args, "result": result}])
    if not sources:
        return None
    source, original = next(iter(sources.values()))
    total = result.get("total_chars")
    total = total if type(total) is int and total >= len(original) else len(original)

    def envelope(length):
        text = original[:length]
        partial = source.truncated or length < len(original)
        delivered = receipt(source.url, text, truncated=partial).model_dump(mode="json")
        delivered["retrieved_at"] = source.retrieved_at.isoformat()
        value = {"ok": True, "url": source.url, "text": text, "source": delivered,
                 "returned_chars": len(text), "total_chars": total}
        if length < len(original):
            value["delivery_truncated"] = True
        return value, json.dumps(value, ensure_ascii=False)

    high = min(len(original), _MAX_EXTRACT_CHAR_LIMIT)
    prepared = envelope(high)
    if len(prepared[1]) <= 60_000:
        return prepared
    low = 0
    # Leave room for the untrusted frame inside bounded_history's 64k default.
    while low < high:
        mid = (low + high + 1) // 2
        if len(envelope(mid)[1]) <= 60_000:
            low = mid
        else:
            high = mid - 1
    return envelope(low)


def _record_tool_result(tool_key, args, result, emit, tool_trace, assistant_content, convo,
                        mcp_fail_counts: dict | None = None) -> dict:
    # Hands v2 screenshots (spec 2026-10-08-0157 §4.2-4.5): `images` go to the model as image
    # parts of this result and nowhere else - not the payload text, the trace, the run trace,
    # the UI event or any file. The result everyone else sees says only that one was taken.
    images = result.get("images") if isinstance(result.get("images"), list) else None
    image_label = str(result.get("image_label") or tool_key)
    if "images" in result or "image_label" in result:
        result = {k: v for k, v in result.items() if k not in ("images", "image_label")}
    web_feedback = _web_read_feedback(tool_key, args, result)
    if web_feedback is not None:
        result, raw_payload = web_feedback
    else:
        feedback = {k: v for k, v in result.items() if k != "artifact"}
        raw_payload = json.dumps(feedback, ensure_ascii=False)
        if len(raw_payload) > 8000:
            # 0.1.49 S9: never a silent cut. Keep head and tail in context and
            # the full result on disk where read_file can page through it.
            from server.services import tool_outputs
            try:
                saved = tool_outputs.save(raw_payload, label=tool_key)
            except OSError:
                saved = None
            raw_payload = tool_outputs.excerpt(raw_payload, saved)
    from server.services import tool_review
    emit({"type": "tool_result", "tool": tool_key, "ok": bool(result.get("ok")),
          "summary": _summarize_result(result), "artifact": result.get("artifact"),
          "artifacts": result.get("artifacts") or [],
          # The phone's quick review (mobile bridge): recorded with the step, never framed.
          "review": tool_review.capture(tool_key, args, result)})
    tool_trace.append({"tool": tool_key, "args": args, "result": result})
    run_trace.record(tool=tool_key, args=args, result=result,
                      ok=bool(result.get("ok")), error=result.get("error"), ms=None)
    from server.orchestrator import untrusted as _untrusted
    framed = (raw_payload if result.get("external") is False else wrap_external(raw_payload)
              if _untrusted.from_the_web(tool_key, args) else _untrusted.wrap_tool_output(raw_payload))
    # S64-0c: a failure counts once the call reached the outside (an MCP server's error, a network command's
    # output on a non-zero exit); only a result that says it never left (`executed: False`) does not.
    reached = result.get("executed") is not False
    if reached and (_untrusted.counts_as_external(tool_key, args)
                    or (tool_key in ("read_skill", "background_status", "find_tools")  # S64-0b/0c: per result
                        and result.get("external") is True)):
        _untrusted.mark_external()           # 0.1.52: this turn read outside content
    if not _untrusted.known_local_call(tool_key, result):
        _untrusted.mark_off_the_list()       # INB2 (#475 F2): any call off the user's allowlist, run or not
    # PB-3 degrade hint. Placement is deliberate: `framed` ends with its frame's close, so the
    # hint sits AFTER the data frame — it is OUR trusted framing (like the
    # "TOOL RESULT for X" header and the "Use this to continue" trailer), never inside
    # the untrusted region the GUARD_NOTE tells the model to distrust.
    hint = ""
    if mcp_fail_counts is not None:
        if result.get("ok"):
            mcp_fail_counts.pop(tool_key, None)          # success resets the streak
        elif tool_key.startswith("mcp_") and result.get("executed") is not False:
            # S1: a refusal (a card's no, nobody to ask) never reached the server: not a failure of the tool.
            n = mcp_fail_counts[tool_key] = mcp_fail_counts.get(tool_key, 0) + 1
            if n >= _MCP_FAIL_HINT_AT:
                hint = "\n" + _mcp_degrade_hint(n)
    # 0.1.50: a concrete alternative at the moment of failure (recovery_hints).
    from server.orchestrator.recovery_hints import hint_for
    recovery = hint_for(tool_key, result)
    if recovery:
        hint += f"\n[Host hint: {recovery}]"
    # 0.1.49: one neutral tool record (arslan/llm/trajectory.py). It starts as a
    # host-run result carrying its invocation text; run_native claims it for the
    # model's tool call (_claim_results). Rendering per provider happens at
    # request time; trajectory.to_legacy reproduces the old "TOOL RESULT for X"
    # user turn byte for byte.
    convo.append(trajectory.tool_result(None, tool_key, f"{framed}{hint}",
                                        synthetic=True, legacy_call=assistant_content,
                                        images=images, image_label=image_label))
    if images and not _SENT_IS_FINAL.get():
        trajectory.keep_latest_images(convo)
    return result


async def _commit_steers(pending: list, conversation_id: str) -> None:
    """K9b: the request about to go carries these messages: each is stored as a user message tagged with this
    run (so the undo of the turn, S3b, takes it with the turn and never counts it as a later one), one from the
    iPhone is shown in the Mac windows as today (never journaled: it is in the history; never echoed to its own
    sender, the Bridge, whose next turn would read as the phone's), and its sender hears `dequeued` with
    `inserted`. Each leaves `pending` before it is stored: a stop landing as it is stored counts it as stored (it
    is never run twice); a store that fails puts it back, to go back with the rest."""
    from server.orchestrator import memory
    from server.services import personal_context, run_registry
    from server.ws import protocol
    current = personal_context.current()
    run_id = current.source_run_id if current is not None else None
    while pending:
        steer = pending.pop(0)
        try:
            message_id = await memory.add_message(conversation_id, "user", steer.content, source=steer.source,
                                                  run_id=run_id)
        except asyncio.CancelledError:
            steer.settle()
            raise
        except Exception:
            pending.insert(0, steer)
            raise
        steer.settle()
        if steer.source == "phone":
            run_registry.make_emit(conversation_id, skip=steer.sink)(
                protocol.message(message_id, steer.content, "user") | {"source": "phone"})
        try:
            await steer.tell({"type": "dequeued", "inserted": True})
        except Exception:  # noqa: BLE001 — its socket closed; the message is in the turn anyway
            pass


def _claim_results(convo: list[dict], marks: list[tuple[int, str]]) -> None:
    """Bind each call's result record to the model's tool call id.

    marks: (len(convo) before the call was handled, call id), in order. Every
    handled call appends exactly one record, and nothing moves inside a batch,
    so a call owns the record at its mark when exactly one message follows it."""
    for index, (mark, call_id) in enumerate(marks):
        end = marks[index + 1][0] if index + 1 < len(marks) else len(convo)
        if end != mark + 1:
            continue
        record = convo[mark]
        if record.get("role") == "tool" and record.get("_synthetic"):
            record.pop("_synthetic", None)
            record.pop("_legacy_call", None)
            record["tool_call_id"] = call_id


def _parse_arguments(raw: str | None) -> tuple[dict | None, str | None]:
    """(arguments, problem) for a call whose arguments did not parse upstream.

    One repair only: strict=False, which accepts raw control characters (e.g.
    newlines) inside strings, a common slip in long write payloads. Anything
    else is reported back to the model, never guessed at (0.1.49 S8)."""
    text = (raw or "").strip()
    if not text:
        return {}, None                      # a no-argument call
    try:
        value = json.loads(text, strict=False)
    except json.JSONDecodeError as exc:
        return None, f"{exc.msg} at character {exc.pos}"
    if not isinstance(value, dict):
        return None, f"expected a JSON object, got {type(value).__name__}"
    return value, None


_JSON_TYPES = {"string": (str,), "integer": (int,), "number": (int, float), "boolean": (bool,),
               "array": (list,), "object": (dict,)}


def _schema_problem(args: dict, schema: dict | None) -> str | None:
    """Missing required fields and wrong top-level types, stated so the model
    can fix the call; None when the schema says nothing checkable."""
    if not isinstance(schema, dict):
        return None
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    problems = []
    for name in schema.get("required") or []:
        if name not in args:
            kind = (props.get(name) or {}).get("type")
            problems.append(f"missing required '{name}'" + (f" ({kind})" if isinstance(kind, str) else ""))
    for name, value in args.items():
        kind = (props.get(name) or {}).get("type")
        kinds = [kind] if isinstance(kind, str) else kind if isinstance(kind, list) else []
        accepted = tuple(t for k in kinds for t in _JSON_TYPES.get(k, ()))
        if not accepted or value is None and "null" in kinds:
            continue
        if isinstance(value, bool) and bool not in accepted or not isinstance(value, accepted):
            problems.append(f"'{name}' must be {' or '.join(kinds)}")
    return "; ".join(problems) or None


def _progress_note(policy) -> str:
    """Trusted host note appended to a result that made no progress, so the
    model sees the loop detector before it stops the turn."""
    return (f"\n[Host note: no new progress — {policy.count} of {policy.limit} steps without "
            "progress before this turn stops. Change approach, or answer with what you have.]")


_OFFLINE_NOTE = (" Files you already fetched can still be processed with run_command (it runs without "
                 "network now).")


async def _log_degrade_hint(conversation_id, tool_key, count) -> None:
    """PB-3 observability: one conversation_events row the FIRST time the degrade hint
    fires for a tool this turn (PB-4's warning wiring reads these). Fail-open — logging
    must never touch the turn."""
    try:
        from server.services import recap_service
        await recap_service.log_event(
            conversation_id, "mcp_degrade_hint",
            {"tool_key": tool_key, "count": count},
            f"MCP tool {tool_key} failed {count} times in a row this turn; suggested the built-in equivalent")
    except Exception:  # noqa: BLE001 — observability is never fatal
        pass


#: 0.1.63 K4b (decision D4, ⓪Plan Q1 = A): a chat turn this long (its own time: a card's wait doesn't
#: count) is told once, in its status block, that it may continue the rest as background work, and the
#: user's reply gets one `note` line. A suggestion, never forced. No setting: nothing interrupts the user,
#: so the card's "can be switched off" was dropped with that decision.
LONG_TURN_S = 600
_LONG_TURN_NOTE = (f"This turn has been working for {LONG_TURN_S // 60} minutes. If what remains is long and "
                   "doesn't need the user meanwhile, you may continue it as background work: call "
                   "start_background_work with a goal that says what is already done in this turn and what "
                   "remains, then tell the user. Otherwise keep going here.")


#: 0.1.63 K5 (⓪Plan's Q5/Q6): once a turn has had two steps whose calls are not only update_plan, its status
#: block asks for four closing lines. Arslan's own turns only (never a delegated worker, which answers in
#: JSON). "Unverified" in the reply's language, never 没查到: _CLAIMS_SEARCH_RE reads that as a claim to
#: have searched (K8 fixes the pattern).
#: v0.1.64 SMART-5: and only once the turn did work (a call that succeeded and is not a read): the bench found the
#: lines on answers to questions (two reads, then a one-line answer and four lines of footer), against "These rules are
#: for reports, not for chatting".
_CLOSING_NOTE = ("This turn used tools in several steps. End your final reply with four short lines, in the "
                 "reply's language: what you did; how you checked it; what you did not check (call it "
                 "unverified, in the reply's language, e.g. 未核对 in Chinese); what the user should watch. Skip them "
                 "if the user asked a question and you only looked things up to answer it.")


#: Looking, not working, though task_service.effect_of (which also decides retries) calls them external writes: they
#: search, find or probe and change nothing. For the closing lines only (#701 review). find_tools is how a turn reaches
#: my_status (itself a read), so a version question is two steps of looking (SMART-5 round 2).
_LOOKS_ONLY = frozenset({"conversation_search", "find_capability", "find_tools", "scan_local_network", "ssh_probe"})


async def _did_work(tool_trace: list, work: dict) -> bool:
    """SMART-5: whether a call of this turn succeeded and was not a read (task_service.effect_of: a write, a command
    that isn't a read, a job started, an MCP tool not known to only read). Each call is judged once."""
    from server.services import task_service
    for step in tool_trace[work["seen"]:]:
        if not work["done"] and (step.get("result") or {}).get("ok") is True and step.get("tool") not in _LOOKS_ONLY:
            try:
                effect = await task_service.effect_of(str(step.get("tool")), step.get("args") or {})
            except Exception:  # noqa: BLE001 — the footer is never a reason to fail a turn; unknown is not a read
                effect = "external_write"
            work["done"] = effect != "read"
    work["seen"] = len(tool_trace)
    return work["done"]


async def _status_workspace(wired_keys) -> tuple:
    """(workspace root, is Arslan's own folder) for the status block; (None,
    False) when no writer is wired or the setting cannot be read."""
    if not wired_keys & {"write_file", "edit_file", "run_command"}:
        return None, False
    from server.db import session as db_session
    from server.services import settings_service
    try:
        async with db_session.AsyncSessionLocal() as db:
            return (await settings_service.workspace_dir_for_run(db),       # SUB5c: a sub-session's own folder
                    await settings_service.workspace_is_default(db))
    except Exception:  # noqa: BLE001
        return None, False


async def _link_check_note(name: str, args: dict, result: dict, tool_trace: list,
                           hints: dict[str, int]) -> str | None:
    """Host link check for a saved text file in a turn that researched; at most
    MAX_HINTS_PER_FILE per file, so a stubborn table cannot loop the turn."""
    from server.orchestrator import link_check
    path = str(result.get("path") or args.get("path") or "")
    if not link_check.applies(path) or hints.get(path, 0) >= link_check.MAX_HINTS_PER_FILE:
        return None
    seen = link_check.evidence(tool_trace)
    if not seen:
        return None
    content = args.get("content") if name == "write_file" else await _read_saved(path)
    found = link_check.review(content, seen) if isinstance(content, str) else None
    if not found:
        return None
    hints[path] = hints.get(path, 0) + 1
    return link_check.hint(path, found)


async def _read_saved(rel: str) -> str | None:
    """The file an edit_file just changed, read back inside the workspace boundary."""
    from server.db import session as db_session
    from server.services import settings_service
    from server.services.workspace_paths import resolve_in_workspace
    try:
        async with db_session.AsyncSessionLocal() as db:
            root = await settings_service.workspace_dir_for_run(db)       # SUB5c: where `rel` was written
        return resolve_in_workspace(rel, root).read_text(encoding="utf-8", errors="replace")[:200_000]
    except Exception:  # noqa: BLE001 — a check that cannot read simply does not run
        return None


async def _unavailable(tool_key: str, live: set[str]) -> dict:
    """The answer to a call this turn cannot run."""
    if tool_key.startswith("mcp_"):
        # 0.1.61 §B1: a server that stopped since this turn's tool list was built answers with its
        # state and reason, not "not available to you" — the call never left Arslan.
        from server.mcp.executor import not_ready_for_key
        not_ready = await not_ready_for_key(tool_key)
        if not_ready is not None:
            return not_ready
    import difflib
    callable_as = {tool_names.wire(key): key for key in live}      # NAME1: the names the model can call
    near = difflib.get_close_matches(tool_key, sorted(callable_as), n=5, cutoff=0.3) or sorted(callable_as)[:5]
    result = {"ok": False, "external": False, "code": "tool_unavailable",
              "error": f"tool '{tool_key}' is not available to you"
                       + (f"; available tools include: {', '.join(near)}" if near else "")
                       + "; you may escalate a need instead"}
    from server.orchestrator import untrusted
    if any(untrusted.odd_mcp_key(key) for key in live if tool_names.wire(key) in near):
        # S64-0c: a key it lists carries a server's odd tool name: framed (no external: False), and marked.
        untrusted.mark_external()
        del result["external"]
    return result


async def _admit(tool_key, args, assistant_content, budget, turn: ToolTurn) -> dict | set[str]:
    """The first stage: the call spends one from the budget, what no gate may see is refused before its frame
    goes out, and a call this turn can't run is refused after. The refusal, recorded, or the keys this turn can run."""
    resolve_tools, resolve_callable = turn.resolve_tools, turn.resolve_callable
    emit, tool_trace, convo = turn.emit, turn.tool_trace, turn.convo
    confirm_command, mcp_fail_counts, conversation_id = turn.confirm_command, turn.mcp_fail_counts, turn.conversation_id
    if budget is not None:
        try:
            budget.tool()
        except BudgetExceeded:
            from server.services.task_service import current as current_task
            if current_task():
                current_task().pause_reason = "task_budget_exhausted"
            raise
    from arslan.execution_checkpoint import save
    await save("tool_admitted")
    # Screen before emitting argument previews or recording traces. The durable
    # task journal also screens, but that later boundary cannot protect UI/logs.
    from arslan.companion.content_policy import contains_credential_data
    if contains_credential_data(args):
        result = {"ok": False, "external": False, "code": "credentials_not_tool_data",
                  "error": "Credentials cannot be passed as ordinary tool arguments. Use an approved connection."}
        safe_call = json.dumps({"tool": tool_key, "args": {}}, ensure_ascii=False)
        return _record_tool_result(tool_key, {}, result, emit, tool_trace, safe_call, convo,
                                   mcp_fail_counts=mcp_fail_counts)
    from server.services import desktop_status
    emit({"type": "tool_call", "tool": tool_key,
          "args_summary": json.dumps(args, ensure_ascii=False)[:200],
          # The one short thing that names the step (a host, a file, a command): a job's
          # "now doing" line and the phone's step titles. Never framed to a window.
          "target": desktop_status.step_target(tool_key, args)})
    desktop_status.note_step(tool_key, args)   # the island's "now doing" line (0.1.51)

    # A run with nobody to ask runs no command at all, whatever rule, grant or "always" answer stands, unless it is a
    # scheduled task's own fire (ASK1-b: the gate then runs what needs no card, in the sandbox). The heartbeat and a
    # sub-session's turn with nobody to ask are refused here, before whether this turn could run it is read:
    # run_command is not offered there, and naming it anyway (or through use_tool) is still listed and explained.
    if tool_key == "run_command" and refuses_commands(confirm_command, conversation_id):
        return _record_tool_result(tool_key, args, await _scheduled_command_refused(args, conversation_id), emit,
                                   tool_trace, assistant_content, convo, mcp_fail_counts=mcp_fail_counts)

    # K7: what this turn can run is settled before any card or file I/O (⓪Plan, Q4): a call to a tool
    # the turn cannot run never shows the user an approval card. The set is every reachable tool,
    # shown in this request or found on demand.
    live = {t["key"] for t in await (resolve_callable or resolve_tools)()}
    if tool_key not in live:
        return _record_tool_result(tool_key, args, await _unavailable(tool_key, live), emit, tool_trace,
                                   assistant_content, convo, mcp_fail_counts=mcp_fail_counts)
    return live


async def _run_tool(tool_key, args, assistant_content, turn: ToolTurn) -> dict:
    """Execute one tool (gated), emit its frames, record the trace, and append one
    framed tool-result record into convo. Returns the raw result dict.

    The stages, in today's order (LOOP1 c2): admit, the eval allowance, the tool's own gate (`Tool.gate`), the eval
    backstop, execute, after."""
    emit, tool_trace, convo = turn.emit, turn.tool_trace, turn.convo
    mcp_fail_counts, conversation_id = turn.mcp_fail_counts, turn.conversation_id
    from arslan.execution_budget import current
    budget = current()
    live = await _admit(tool_key, args, assistant_content, budget, turn)
    if isinstance(live, dict):
        return live

    # S5a: plan mode runs reads only, before any card or file I/O.
    from server.services import permissions
    refusal = await permissions.plan_refusal(tool_key, args, conversation_id)
    if refusal is not None:
        return _record_tool_result(tool_key, args, refusal, emit, tool_trace, assistant_content, convo,
                                   mcp_fail_counts=mcp_fail_counts)

    # FU-2b: the eval/replay allowance (live reads have none since 0.1.63 K4b).
    refusal = await _check_fetch_budget(tool_key, conversation_id=conversation_id)
    if refusal is not None:
        return _record_tool_result(tool_key, args, refusal, emit, tool_trace,
                                   assistant_content, convo,
                                   mcp_fail_counts=mcp_fail_counts)

    # The tool's own gate (LOOP1 c2): the refusal to record (enrolling's card is its answer), the command gate's
    # plan, or None. One per tool, so these gates have no order among themselves.
    plan = command_gate.NOT_A_COMMAND
    gate = getattr(_BUILT_IN.get(tool_key), "gate", None)
    if gate is not None:
        gated = await gate(tool_key, args, turn)
        if isinstance(gated, dict):
            return _record_tool_result(tool_key, args, gated, emit, tool_trace, assistant_content, convo,
                                       mcp_fail_counts=mcp_fail_counts)
        if gated is not None:
            plan = gated

    refusal = _eval_backstop(tool_key, conversation_id)
    if refusal is not None:
        return _record_tool_result(tool_key, args, refusal, emit, tool_trace,
                                   assistant_content, convo,
                                   mcp_fail_counts=mcp_fail_counts)

    executor = await resolve_executor(tool_key)
    if executor is None:
        result = await _unavailable(tool_key, live)
    else:
        # SBX settings: what the proxy refuses while a command runs becomes the window's card, never part of the result.
        from server.services import sandbox_proxy, trusted_devices
        watch = sandbox_proxy.watch() if tool_key == "run_command" else None
        result = await tool_execute.run_executor(tool_key, args, executor, plan, budget, turn)
        for frame in await trusted_devices.offer(conversation_id, tool_key, result, sandbox_proxy.unwatch(watch)):
            emit(frame)
    return await _after(tool_key, args, result, assistant_content, turn)


def _eval_backstop(tool_key, conversation_id) -> dict | None:
    """The last common gate, after the tool's own: in an eval or replay, only what is safe to replay runs."""
    # Fail-closed hermetic backstop (eval sealing): in an evolution eval/replay context,
    # refuse ANY tool that isn't read-only-safe, independent of resolve_tools() and the
    # replay flag. This is the throat every tool call passes through (model-driven AND the
    # force_tools pre-run), so a forgotten upstream replay=True cannot silently re-open a
    # side-effecting tool. run_python's unsandboxed escape valve is also refused here — a
    # networked run_python is not hermetic.
    from server.services.replay_safety import is_hermetic_context, is_replay_safe
    if is_hermetic_context(conversation_id):
        # Honest, model-readable refusal: the model's behavior here is scored by the judge,
        # so name the eval context explicitly and tell it not to retry side-effecting tools
        # (a generic "failed" would make it flail with compensatory actions that pollute the
        # score). The refusal itself is deterministic and identical across arms.
        if not is_replay_safe(tool_key):
            result = {"ok": False, "external": False,
                      "error": f"evaluation context: '{tool_key}' is unavailable here. This "
                               "run is a hermetic evaluation replay that exposes read-only "
                               "tools only (no side-effecting or external tools). Do not retry "
                               "this tool — answer with the read-only tools you have."}
            return result
        if tool_key == "run_python" and os.environ.get("ARSLAN_ALLOW_UNSANDBOXED_PY"):
            result = {"ok": False, "external": False,
                      "error": "evaluation context: run_python is unavailable because the "
                               "unsandboxed escape valve (ARSLAN_ALLOW_UNSANDBOXED_PY) is set; "
                               "a networked run_python is not hermetic. Answer without it."}
            return result
    return None


async def _after(tool_key, args, result, assistant_content, turn: ToolTurn) -> dict:
    """The last stage: the call's one record, and the degrade hint the first time an MCP tool fails often enough."""
    emit, tool_trace, convo = turn.emit, turn.tool_trace, turn.convo
    mcp_fail_counts, mcp_hint_logged = turn.mcp_fail_counts, turn.mcp_hint_logged
    conversation_id, log_events = turn.conversation_id, turn.log_events
    out = _record_tool_result(tool_key, args, result, emit, tool_trace,
                              assistant_content, convo, mcp_fail_counts=mcp_fail_counts)
    if (log_events and mcp_fail_counts is not None and mcp_hint_logged is not None
            and mcp_fail_counts.get(tool_key, 0) >= _MCP_FAIL_HINT_AT
            and tool_key not in mcp_hint_logged):
        # log_events=False (E3 hermetic replay): the degrade counter still advances (the
        # guard runs), only the ConversationEvent write is suppressed. In replay MCP tools
        # are filtered out anyway, so this is belt-and-suspenders against a hallucinated key.
        mcp_hint_logged.add(tool_key)
        await _log_degrade_hint(conversation_id, tool_key, mcp_fail_counts[tool_key])
    return out



async def _propose_plan_change(args: dict, emit) -> dict:
    """Record Arslan's changed plan for this conversation's project and show it as a card
    ("计划要不要跟着改？"). The user keeps the old plan or takes the new one."""
    from server.db import session as db_session
    from server.db.models import Project
    from server.services import personal_context, project_plan
    ctx = personal_context.current()
    if ctx is None or not ctx.project_id:
        return {"ok": False, "error": "this conversation has no project"}
    try:
        async with db_session.AsyncSessionLocal() as db:
            project = await db.get(Project, ctx.project_id)
            if project is None or project.status != "active":
                return {"ok": False, "error": "the project is not available"}
            event = await project_plan.propose_plan(db, project, args.get("levels") or [], str(args.get("reason") or ""))
            await db.commit()
    except project_plan.PlanError as exc:
        return {"ok": False, "error": exc.code}
    emit({"type": "plan_proposed", "project_id": ctx.project_id, "proposal_id": event.id,
          "diff": event.payload["diff"], "reason": event.payload["reason"], "cleared": event.payload["cleared"]})
    return {"ok": True, "proposal_id": event.id,
            "note": "Shown to the user as a card. Nothing changed yet; they keep the plan or take this one."}


# Native tool-calling is the sole production execution loop.

# Minimal OpenAI-format parameter schemas per known tool key. The executor re-validates args,
# so these can be loose; they exist only to nudge the model toward the right shape.
_NATIVE_PARAM_SCHEMAS: dict[str, dict] = {
    **tool_defs.SCHEMAS,
    # 0.1.63 K7: the two tools that reach everything a request is not shown (on_demand.py).
    **on_demand.SCHEMAS,
}

# PA-3: ask_user_choice is a TERMINAL tool (same pattern as `escalate`): a VALID call
# ends the turn — the caller renders a structured choice card (`clarify_options`) and
# the user's click advances the conversation. Validation is recoverable: a malformed
# call gets a tool error the model can react to (retry with 2-4 options, or answer).
CLARIFY_MIN_OPTIONS = 2
CLARIFY_MAX_OPTIONS = 4


def _parse_clarify_args(args: dict) -> tuple[dict | None, str | None]:
    """Validate + clamp ask_user_choice args.

    Returns ({question, options: [{label, hint}] (2-4)}, None) on success, or
    (None, recoverable-error-text) when the question is missing or fewer than
    2 distinct labelled options survive cleaning. Over-long lists clamp to 4."""
    question = str(args.get("question") or "").strip()
    options: list[dict] = []
    raw = args.get("options")
    if isinstance(raw, list):
        for o in raw:
            if isinstance(o, str):                 # some models send bare strings
                label, hint = o.strip(), ""
            elif isinstance(o, dict):
                label = str(o.get("label") or "").strip()
                hint = str(o.get("hint") or "").strip()
            else:
                continue
            if label and not any(x["label"] == label for x in options):
                options.append({"label": label, "hint": hint})
    if not question or len(options) < CLARIFY_MIN_OPTIONS:
        return None, ("ask_user_choice needs a question plus 2-4 DISTINCT options "
                      "(each {label, hint?}). Give at least 2 real options, or just "
                      "answer the user directly.")
    return {"question": question, "options": options[:CLARIFY_MAX_OPTIONS]}, None

_ESCALATE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "escalate",
        "description": "Raise a missing capability or missing data you cannot get with your "
                       "tools. Describe the OUTCOME you need, never an operation to run.",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["data", "capability"]},
                "need": {"type": "string"},
                "context": {"type": "string"},
            },
            "required": ["need"],
        },
    },
}

# Appended to `system` in native mode. Curbs the "N tiny searches" pattern the old text loop
# suffered from — see spec §效率.
# General research discipline (domain-agnostic) — converges any gather-then-answer task with any
# single model, instead of fumbling N snippet searches on noisy results.
# 0.1.63 K5: the research rules ("RESEARCH DISCIPLINE") used to be appended to every run_native system,
# tools or not; they now live in web_search's and web_extract's descriptions (arslan._arslan_tools).

_PERMISSIVE_PARAMS = {"type": "object", "properties": {}, "additionalProperties": True}


def _tool_params(t: dict) -> dict:
    """Resolve the OpenAI `parameters` schema for one tool dict.

    Precedence: built-in hardcoded schema (never clobbered) > the tool's stored
    `input_schema` (the JSON Schema captured at MCP discovery — an MCP tool with a
    real schema stops the model guessing arg names) > permissive fallback. `input_schema`
    is a JSON column (already a dict), but a stringified schema is parsed defensively;
    anything empty/None/malformed degrades to permissive — never raises."""
    key = t.get("key")
    if key in _NATIVE_PARAM_SCHEMAS:               # built-ins keep their hardcoded schema
        return _NATIVE_PARAM_SCHEMAS[key]
    raw = t.get("input_schema")
    if isinstance(raw, str):                       # defensive: a schema stored as JSON text
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raw = None
    if isinstance(raw, dict) and raw:              # non-empty stored schema → hand it to the model
        return raw
    return _PERMISSIVE_PARAMS                       # genuinely no schema → executor re-validates args


def _native_tool_schemas(wired: list[dict], *, allow_escalation: bool) -> list[dict]:
    """Turn resolve_tools()'s [{key, description, input_schema}] into OpenAI function schemas.
    Tools carrying a stored `input_schema` expose it as `parameters`; keys with no schema get a
    permissive one (executor re-validates args). Adds `escalate` when allowed.

    0.1.63 K3: sorted by name, `escalate` last. The table renders before Claude's cached system, so its
    order is part of the cache key; tools loaded later (K7) are appended after it, never sorted in."""
    from server.orchestrator import untrusted
    if any(untrusted.odd_mcp_key(t["key"]) for t in wired):
        untrusted.mark_external()       # S64-0c: a key in the table carries a server's odd tool name
    schemas: list[dict] = []
    resident = sorted((t for t in wired if not t.get("appended")), key=lambda tool: tool["key"])
    for t in resident + [t for t in wired if t.get("appended")]:
        key = t["key"]
        schemas.append({
            "type": "function",
            "function": {"name": key,
                         "description": t.get("description", ""),
                         "parameters": _tool_params(t)},
        })
    if allow_escalation:
        schemas.append(_ESCALATE_SCHEMA)
    return schemas


# Tools a job may still use while wrapping up: saving the deliverable. LOOP1 a6: each tool's `saves` trait.
WRAP_UP_TOOLS = tool_defs.named(lambda traits: traits.saves)


def _stop_for_limit(runtime, reason: str, trace: list[dict], *, finishing: bool = False) -> None:
    """0.1.62 F2 ④: a work limit stops this turn. With a deliverable saved this turn, it is only
    noted (`limit_reason`): the task holds for it only if the finish-time checks do not pass a
    saved file (task_service._run). Otherwise it holds the task, as before. `finishing`: the limit
    opened the wrap-up steps, which are there to save; only noted, and the forced step after them
    (or _run) decides."""
    if finishing or any(item.get("tool") in WRAP_UP_TOOLS and (item.get("result") or {}).get("ok") is True
                        for item in trace):
        runtime.limit_reason = reason
    else:
        runtime.pause_reason = reason
# What a wrapping-up run may still call (0.1.50): the save tools, plus run_command
# to process files it already fetched — run without network (terminal_exec.OFFLINE).
FINISH_TOOLS = WRAP_UP_TOOLS | {"run_command"}
# K3: refused calls while wrapping up before the next step is text only (the table never narrows).
WRAP_REFUSALS_BEFORE_TEXT = 2


def _host_turn(caller, progress_lane) -> bool:
    """Arslan's own turn (a chat turn or a background job), not a delegated worker.
    The chat path and jobs pass ToolCaller(actor="host"); tests and older paths pass none."""
    return progress_lane is None and (caller is None or getattr(caller, "actor", None) == "host")


@governed
async def run_native(**kwargs) -> dict:
    """One answer turn: `_run_native` below, plus completion first at the hard stop
    (0.1.50, S6 bench T2 r2). A chat turn that reaches its hard work limit after
    doing real work ends with a closing message the host writes — what was saved,
    where, how many pages were read, how to continue — instead of an error that
    hides a deliverable already on disk. No model call: the limit is reached.
    Background jobs and delegated workers still raise; their machinery records
    the stop itself."""
    request, state = TurnRequest(**kwargs), TurnState()
    from server.orchestrator import untrusted as _untrusted
    from server.services import tool_outputs
    seen = _untrusted.track_turn()
    if _untrusted.history_from_outside(request.history) or _untrusted.context_from_outside(request.user_content):
        _untrusted.mark_external()       # S64-0b: a job's result framed as outside content, or a summary of one
    sent_is_final = _SENT_IS_FINAL.set(False)
    # S2a-1 piece 5: the saved outputs of this turn belong to its conversation (a command may read them).
    copies_of = tool_outputs.conversation.set(request.conversation_id)
    try:
        result = await _run_native(request, state)
        if isinstance(result, dict):
            result["external_seen"] = _untrusted.external_seen()
            _learn_after(request, state, result)
        return result
    except BudgetExceeded as stopped:
        from server.services import background_jobs
        trace = state.tool_trace
        # 0.1.52: the chat path passes ToolCaller(actor="host"); checking for no caller
        # at all left this closing message unreachable from a real chat turn.
        host_turn = _host_turn(request.caller, request.progress_lane)
        if host_turn and background_jobs.inside_job():
            # A job's turn ends with no text here (a job shows no streamed text, and nothing is returned). The job
            # records the stop and reports it; the report carries what this turn's records show (`_report`).
            stopped.closing = await _stop_records(request, state)
        if not host_turn or background_jobs.inside_job():
            raise                       # workers and jobs record the stop themselves
        text = await _budget_closing(trace, state.ws_root, state.started)
        if not any((t.get("result") or {}).get("ok") for t in trace) and (records := await _stop_records(request,
                                                                                                         state)):
            # Nothing ran, so the closing alone names nothing: what was blocked and what is left, from the records.
            text = f"{text}\n\n{records}"
        from server.services.task_service import current as current_task
        task = current_task()
        if task is not None:
            _stop_for_limit(task, "task_budget_exhausted", trace)
        if (turn_text := state.turn_text) is not None and turn_text.parts:
            turn_text.append(text, answer=False)    # K8a: after what this turn already showed
            text = turn_text.text
        elif text:
            request.on_chunk(text)
        return {"final": text, "escalation": None, "tool_trace": trace,
                "stop_reason": "task_budget_exhausted", "history_compacted": False,
                "external_seen": _untrusted.external_seen()}
    except asyncio.CancelledError:
        # A job's wall clock ran out: its timeout cancels this turn, so no BudgetExceeded reaches here. The job's
        # report gets the same closing as a budget stop (`background_jobs._execute`). The user's stop is not this.
        from arslan.execution_budget import wall_clock_expired
        from server.services import background_jobs
        if (_host_turn(request.caller, request.progress_lane) and background_jobs.inside_job()
                and wall_clock_expired()):
            background_jobs.note_wall_closing(await _stop_records(request, state))
        raise
    finally:
        # K9b: a message read after the last batch that no request carried (the turn stopped, hit its limit
        # or failed first) goes back to its sender, to run once as a turn of its own.
        for steer in state.steers:
            steer.hand_back()
        known_local = _untrusted.known_local()      # read before end_turn drops the holder
        _untrusted.end_turn(seen)
        run_trace.record_outside(not known_local)   # INB2: the run's own record (runs.read_outside), the allowlist
        _SENT_IS_FINAL.reset(sent_is_final)
        tool_outputs.conversation.reset(copies_of)


def _learn_after(request: TurnRequest, state: TurnState, result: dict) -> None:
    """0.1.52 S5: after a host turn, off the reply path — counters for the lessons this
    turn recalled, then any detour worth keeping (lessons.after_turn)."""
    if not _host_turn(request.caller, request.progress_lane):
        return
    from server.services import lessons, personal_context
    ctx = personal_context.current()
    lessons.note_turn(request.conversation_id, list(state.tool_trace))
    lessons.later(lessons.after_turn(
        conversation_id=request.conversation_id, user_request=(ctx.query if ctx else "") or "",
        trace=list(state.tool_trace), external_seen=bool(result.get("external_seen")),
        recalled=list(state.recalled_lessons),
        ok=bool(result.get("final")) and not result.get("stop_reason"), emit=request.emit))


async def _stop_records(request: TurnRequest, state: TurnState) -> str:
    """Done / Blocked / Left for a turn a limit stopped, from its own records (`answer_salvage._records_closing`):
    a job's against the goal the user gave it, a chat turn's against the user's message. "" if it failed."""
    from server.orchestrator import answer_salvage
    from server.services import background_jobs, personal_context, runtime_messages
    ctx = personal_context.current()
    request_text = (background_jobs.current_goal() or (ctx.query if ctx is not None else "")
                    or (request.user_content if isinstance(request.user_content, str) else ""))
    try:
        return answer_salvage._records_closing(request_text, state.tool_trace, state.plan.items if state.plan else [],
                                               locale=await runtime_messages.selected_locale())
    except Exception:  # noqa: BLE001 — broad on purpose, and loud: see below
        # This runs while a stop propagates (BudgetExceeded, or the wall clock's cancellation). Whatever it raised
        # would replace that stop: the job would read as failed rather than out of budget, and the chat turn would
        # lose its closing. So any failure is logged as an error with its traceback, and the stop goes on with the
        # job's budget note (or the chat's closing) and no records.
        logger.exception("stop closing not written")
        return ""


async def _budget_closing(trace: list, ws_root, started: float) -> str:
    from arslan.execution_budget import current
    from server.orchestrator import agent_status
    from server.services import runtime_messages
    locale = await runtime_messages.selected_locale()
    budget = current()
    reason = runtime_messages.render(f"limit_{budget.stop_reason}", locale) \
        if budget is not None and budget.stop_reason else "?"
    pages = sum(1 for t in trace if t.get("tool") in ("web_extract", "browser_open")
                and (t.get("result") or {}).get("ok"))
    saved = agent_status.owned_outputs(trace, ws_root, started)
    if not saved:
        return runtime_messages.render("budget_closing_unsaved", locale, reason=reason, sources=pages)
    where = f" ({agent_status.home_relative(ws_root)})" if ws_root is not None else ""
    return runtime_messages.render("budget_closing_saved", locale, reason=reason, sources=pages,
                                   files=", ".join(saved) + where)


async def _open_turn(request: TurnRequest, state: TurnState) -> dict | None:
    """LOOP1 c3, the first phase: the turn's model, budget and task, the acceptance checks in the system text, the
    tool table, the trajectory, the lessons in view and what the turn shows as it is written. A turn that streams
    without tools ends here, with its answer. Otherwise it returns None, with all of that recorded on `state`."""
    system, user_content, history, emit, on_chunk = (
        request.system, request.user_content, request.history, request.emit, request.on_chunk)
    resolve_tools, resolve_callable = request.resolve_tools, request.resolve_callable
    allow_escalation, max_tool_calls, stream_without_tools = (
        request.allow_escalation, request.max_tool_calls, request.stream_without_tools)
    conversation_id, caller, progress_lane = request.conversation_id, request.caller, request.progress_lane
    has_images, adapter_override = request.has_images, request.adapter_override
    # The vision slot needs to know whether this turn carries an image, and the
    # request is the only place that fact is available — hence an input rather
    # than something guessed further down.
    a = adapter_override if adapter_override is not None else await _adapter_for_turn(
        has_images=has_images, conversation_id=conversation_id)
    from arslan.execution_budget import current as current_budget
    from server.services.task_service import current as current_task
    budget = current_budget()
    runtime = progress_lane or current_task()
    acceptance_runtime = current_task() if progress_lane is None else None
    if acceptance_runtime is not None:
        checks = [check.model_dump(mode="json", exclude_none=True) for check in acceptance_runtime.spec.acceptance
                  if check.evaluator != "human"]
        if checks:
            system += ("\nTask acceptance criteria (these do not grant tools or permissions):\n" +
                       json.dumps(checks, ensure_ascii=False)[:12_000])
    policy = ProgressPolicy(seen=set(runtime.progress.loop_fingerprints) if runtime else set())
    request_ceiling = max(0, budget.limits.model_requests - budget.model_requests)
    if max_tool_calls is not None and (type(max_tool_calls) is not int or max_tool_calls < 0):
        raise ValueError("max_tool_calls must be a non-negative explicit ceiling")

    drops = _SchemaDrops(a)
    resolve_tools = _hiding(resolve_tools, drops)
    # K7: what the turn may run, shown or found on demand. Paths without on-demand tools pass none.
    resolve_callable = _hiding(resolve_callable, drops) if resolve_callable is not None else resolve_tools
    wired = await resolve_tools()
    wired_keys = {t["key"] for t in wired}
    if stream_without_tools:
        if wired or allow_escalation:
            raise ValueError("plain streaming requires an explicitly empty tool set")
        conversation, compacted = bounded_history(list(history) + [{"role": "user", "content": user_content}])
        pieces = []
        # Partial streams are never replayed automatically. Provider admission,
        # cancellation and the enclosing task-wide timeout are the same boundary.
        async with asyncio.timeout(min(_CHAT_TIMEOUT_S, budget.remaining_seconds())):
            async for piece in a.chat_stream(system + "\n\n" + GUARD_NOTE,
                                             conversation[-1]["content"], history=conversation[:-1]):
                pieces.append(piece)
                if acceptance_runtime is None:
                    on_chunk(piece)
        if acceptance_runtime is not None:
            from server.services import task_validation
            report = await task_validation.validate_output(acceptance_runtime, "".join(pieces), [], model_adapter=a)
            if task_validation.failures(report):
                acceptance_runtime.pause_reason = "task_validation_failed"
                pieces = [task_validation.failure_output("".join(pieces), report, acceptance_runtime.spec.locale)]
            if pieces:
                on_chunk("".join(pieces))
        return {"final": "".join(pieces), "escalation": None, "tool_trace": [],
                "stop_reason": None, "history_compacted": compacted}
    schemas = _native_tool_schemas(wired, allow_escalation=allow_escalation)
    params_by_key = {t["key"]: _tool_params(t) for t in wired}
    # GUARD_NOTE = injection defense (wrapped tool/web content is untrusted DATA, not instructions) — the
    # same guard the old loop carried. (K5: the research rules moved to the web tools' descriptions.)
    system = system + "\n\n" + GUARD_NOTE

    # convo is the neutral in-turn trajectory (arslan/llm/trajectory.py): one
    # assistant message per model reply that called tools, one tool record per
    # handled call. It is rendered per request (_render_request); compaction
    # evicts whole call groups.
    current_request = trajectory.request(user_content)
    convo: list[dict] = list(history) + [current_request]
    # 0.1.52 S5: practices learned before that match this request ride in the status
    # block (never the system prompt). Host turns only; recall applies memory's permissions.
    lesson_notes: list[str] = []
    if _host_turn(caller, progress_lane):
        from server.services import lessons, personal_context
        ctx_now = personal_context.current()
        recalled = await lessons.recall((ctx_now.query if ctx_now else "") or turn_context.users_words(user_content))
        lesson_notes = lessons.status_lines(recalled)
        if not all(item["users"] for item in recalled):
            from server.orchestrator import untrusted as _untrusted
            _untrusted.mark_off_the_list()   # #475 H1: a practice in view that came from a run off the list
        state.recalled_lessons = recalled
    research_source_feedback: list = []
    # PB-3 (条件2): consecutive-failure counts per mcp_* tool key. These are LOCALS of this
    # run_native invocation — one invocation = one turn — so a new turn starts at zero by
    # construction; nothing persists or is shared. mcp_hint_logged bounds the observability
    # row to once per turn per tool.
    mcp_fail_counts: dict[str, int] = {}
    mcp_hint_logged: set[str] = set()
    call_ids: set[str] = set()
    from server.orchestrator import agent_status
    from server.orchestrator.model_call import TurnRecovery
    from server.orchestrator.turn_plan import Plan
    turn_state = TurnRecovery()
    plan = Plan()
    turn_started = agent_status.now()
    ws_root, own_folder = await _status_workspace(wired_keys)
    # K8a: what this turn shows as it is written (None: every answer shown whole, as before).
    turn_text = (_TurnText(on_chunk, lambda label, keep: emit({"type": "stream_restart", "label": label, "keep": keep}))
                 if on_chunk is not None and _streams_answer(a, acceptance_runtime) else None)
    state.ws_root, state.started, state.turn_text = ws_root, turn_started, turn_text
    state.adapter, state.budget, state.runtime, state.acceptance_runtime, state.policy = (
        a, budget, runtime, acceptance_runtime, policy)
    state.request_ceiling, state.system, state.drops = request_ceiling, system, drops
    state.resolve_tools, state.resolve_callable = resolve_tools, resolve_callable
    state.wired, state.wired_keys, state.schemas, state.params_by_key = wired, wired_keys, schemas, params_by_key
    state.current_request, state.convo, state.lesson_notes = current_request, convo, lesson_notes
    state.research_source_feedback, state.mcp_fail_counts, state.mcp_hint_logged, state.call_ids = (
        research_source_feedback, mcp_fail_counts, mcp_hint_logged, call_ids)
    state.recovery, state.plan, state.own_folder = turn_state, plan, own_folder
    return None


def _tool_turn(request: TurnRequest, state: TurnState) -> ToolTurn:
    """What a call of this turn goes through its gates with, built for each call from the turn as it stands then:
    the trajectory is rebound when the history is fitted."""
    return ToolTurn(resolve_tools=state.resolve_tools, emit=request.emit, tool_timeout_s=request.tool_timeout_s,
                    tool_trace=state.tool_trace, convo=state.convo, confirm_command=request.confirm_command,
                    confirm_workspace_write=request.confirm_workspace_write, confirm_schedule=request.confirm_schedule,
                    mcp_fail_counts=state.mcp_fail_counts, mcp_hint_logged=state.mcp_hint_logged,
                    conversation_id=request.conversation_id, log_events=request.log_events, caller=request.caller,
                    turn_adapter=state.adapter, resolve_callable=state.resolve_callable)


async def _presearch(request: TurnRequest, state: TurnState) -> None:
    """A turn with `force_tools` may search first, through `_run_tool` as any call does. What it records is the
    first request's newest feedback (`state.pending_feedback`)."""
    user_content, force_tools, conversation_id = request.user_content, request.force_tools, request.conversation_id
    wired_keys, policy, convo = state.wired_keys, state.policy, state.convo
    unseen_start = len(convo)
    # Deterministic pre-search uses the same admission and progress boundaries.
    if force_tools and "web_search" in wired_keys and "web_search" in EXECUTORS:
        from server.services import tool_intent
        try:
            intent = await tool_intent.classify(user_content, sorted(wired_keys), conversation_id=conversation_id)
        except Exception:  # noqa: BLE001
            intent = None
        if intent is not None and intent.needs and intent.tool == "web_search":
            q = (intent.query or user_content)[:400]
            result = await _run_tool("web_search", {"query": q},
                                     json.dumps({"tool": "web_search", "args": {"query": q}}, ensure_ascii=False),
                                     _tool_turn(request, state))
            policy.observe("web_search", {"query": q}, result)
    state.pending_feedback = len(convo) - unseen_start


def _step_mode(request: TurnRequest, state: TurnState, step: int) -> StepMode:
    """LOOP1 c3: what this step may do. The budget's checks come first, then finish mode (sticky once entered), then
    whether the step is forced to text. A step that stops records its reason, and the turn keeps it."""
    max_tool_calls = request.max_tool_calls
    budget, runtime, policy, turn_state, tool_trace = (
        state.budget, state.runtime, state.policy, state.recovery, state.tool_trace)
    finish_reason, finish_from, finish_steps, wrap_refused, can_save, stop_reason = (
        state.finish_reason, state.finish_from, state.finish_steps, state.wrap_refused, state.can_save,
        state.stop_reason)
    budget.check()
    if budget.model_requests >= budget.limits.model_requests:
        if runtime:
            runtime.pause_reason = "task_budget_exhausted"
        budget.stop("model_requests")
    # Three batches of tool calls cut off by the output limit (none of which
    # ran): stop asking for tools and get an answer (0.1.49 S6 breaker).
    truncation_stop = turn_state.truncated_calls >= 3
    if finish_reason is None and not truncation_stop:
        if policy.stopped:
            finish_reason, finish_from = "no_progress", len(tool_trace)
    saved = any(item.get("tool") in WRAP_UP_TOOLS and (item.get("result") or {}).get("ok") is True
                for item in tool_trace[finish_from:]) if finish_reason else False
    finishing = finish_reason is not None and can_save and finish_steps < 3 and not saved
    finish_done = finish_reason is not None and not finishing
    forced = (finish_done or (policy.stopped and not finishing) or truncation_stop
              or budget.tool_calls >= budget.limits.tool_calls
              or (max_tool_calls is not None and step >= max_tool_calls)
              or wrap_refused >= WRAP_REFUSALS_BEFORE_TEXT)
    no_progress = policy.stopped or finish_reason == "no_progress"
    if forced or (finishing and no_progress):
        stop_reason = "task_no_progress" if no_progress or truncation_stop else "task_budget_exhausted"
        if runtime:
            _stop_for_limit(runtime, stop_reason, tool_trace, finishing=finishing and no_progress and not forced)
    state.finish_reason, state.finish_from, state.stop_reason = finish_reason, finish_from, stop_reason
    return StepMode(forced=forced, finishing=finishing, saved=saved, no_progress=no_progress,
                    truncation_stop=truncation_stop)


async def _step_notes(request: TurnRequest, state: TurnState, mode: StepMode) -> tuple[list[str], bool]:
    """LOOP1 c3: this step's notes for the status block, and whether it wraps up."""
    emit, caller, progress_lane = request.emit, request.caller, request.progress_lane
    budget, tool_trace, wired_keys, work, offline_note = (
        state.budget, state.tool_trace, state.wired_keys, state.work, state.offline_note)
    finish_steps, long_turn_told, tool_steps, wrap_refused = (
        state.finish_steps, state.long_turn_told, state.tool_steps, state.wrap_refused)
    forced, finishing, saved, no_progress, truncation_stop = (
        mode.forced, mode.finishing, mode.saved, mode.no_progress, mode.truncation_stop)
    # 0.1.50 S1: the system prompt stays byte-identical for the whole turn
    # (prefix cache); this step's notes go to the <agent_status> block.
    notes: list[str] = []
    if forced:
        notes.append("The deliverable is saved. Give the final answer now: where it is, what is verified and "
                     "what is missing. Text only." if saved else
                     "Repeated actions made no progress. Explain what was verified and what is blocked. Text only."
                     if no_progress else
                     "Your tool calls kept exceeding the output limit and none of them ran. Report briefly what "
                     "was verified and what remains. Text only." if truncation_stop else
                     "Research is over and the calls outside wrapping up were refused: give the final answer "
                     "now from what you have, marking what is unverified. Text only."
                     if wrap_refused >= WRAP_REFUSALS_BEFORE_TEXT else
                     "Tool budget exhausted: report the verified results and remaining work. Text only.")
    # 0.1.43 completion first: past the soft limit (or, 0.1.50, in finish mode),
    # stop gathering and FINISH. Research tools are withdrawn; saving the
    # deliverable stays possible. Not a failure: the completion checks decide
    # the outcome as usual.
    wrap_up = not forced and (finishing or budget.soft_reached())
    # K3: the tool table stays as it is (narrowing it would rewrite Claude's cache from the tools
    # on); the status says what still runs, and dispatch refuses the rest with its reason.
    still_run = sorted(FINISH_TOOLS & wired_keys)
    allowed_note = (f" Tools that still run: {', '.join(still_run)}; any other call is refused."
                    if still_run else " No tool runs any more: answer in text.") if wrap_up else ""
    if finishing:
        finish_steps += 1
        notes.append("Repeated actions made no progress, so research has stopped."
                     " Using only what you already have, save the deliverable now if one was asked for "
                       "(write_file), marking anything missing or unverified; then give the final answer: "
                       "what was done, what is blocked." + allowed_note + offline_note)
    elif wrap_up:
        notes.append("Work budget nearly used: stop researching now. Using only what you already have, "
                     "produce the complete deliverable the user asked for (save it if a file was asked for), "
                     "clearly marking anything you could not verify. Then give the final answer."
                     + allowed_note + offline_note)
    # K4b: once a turn, only where start_background_work is offered (never inside a job), and only in
    # the status block, so the system text and the tools (K3's cached prefix) stay as they are.
    if (not long_turn_told and not forced and not wrap_up and "start_background_work" in wired_keys
            and budget.elapsed() >= LONG_TURN_S):
        long_turn_told = True
        notes.append(_LONG_TURN_NOTE)
        from server.services import runtime_messages
        emit({"type": "note", "text": runtime_messages.render(
            "turn_long", await runtime_messages.selected_locale(), minutes=LONG_TURN_S // 60)})
    if tool_steps >= 2 and _host_turn(caller, progress_lane) and await _did_work(tool_trace, work):
        notes.append(_CLOSING_NOTE)
    state.finish_steps, state.long_turn_told = finish_steps, long_turn_told
    return notes, wrap_up


def _fit_history(state: TurnState, notes: list[str]) -> None:
    """LOOP1 c3: the in-turn history fitted to its bound before the request, and the notes that go with it. The
    trajectory may come back as a new list, so `state.convo` is rebound here and read again after."""
    a, turn_state, convo, tool_trace, wired_keys = (
        state.adapter, state.recovery, state.convo, state.tool_trace, state.wired_keys)
    pending_feedback, history_compacted = state.pending_feedback, state.history_compacted
    # Deliver one new tool batch atomically before normal old-history
    # eviction. Keep a bounded 96k research window so a <=96k source batch
    # can survive the following save/readback steps, not just one request.
    # Other turns retain the 64k target. Apply extra protection only
    # to batches <=96k, never permanently pin sources or widen task budgets.
    # Existing opaque-provider pair retention is otherwise unchanged.
    # 0.1.63 K1b: Claude's native path never edits what it sent; the API clears old tool results
    # (context editing). After a refusal of that, local trimming resumes (screenshots too).
    server_trims = _server_trims(a, turn_state)
    _SENT_IS_FINAL.set(server_trims)
    if not server_trims:
        trajectory.keep_latest_images(convo)
    oversized_feedback = (not server_trims and pending_feedback
                          and _rendered_size(convo[-pending_feedback:]) > 96_000)
    has_web_evidence = any(item.get("tool") == "web_extract" and
                           (item.get("result") or {}).get("ok") for item in tool_trace)
    if has_web_evidence:
        notes.append(
            "Research scope: deliver the smallest useful report answering the requested dimensions. "
            "For a question about one capability, do not expand into an inventory of unrelated README "
            "differences. Unless comprehensive coverage is requested, use at most six relevant comparison "
            "rows and short source quotations, with a concise conclusion and explicit unknowns. "
            "Do not add an exhaustive 'not mentioned' list that the user did not ask for. "
            "Omission from one quoted sentence is not absence from a document. Each shared claim must "
            "be supported by BOTH sources; otherwise attribute it only to the source that says it. "
            "A shared commit URL does not date a translation's baseline or prove why texts differ. "
            "Stay within the existing budget; extra detail is not a substitute for an accurate deliverable.")
    in_turn = _IN_TURN_CHARS_RESEARCH if has_web_evidence else _IN_TURN_CHARS
    convo, compacted = (convo, False) if server_trims else bounded_history(
        convo, max_chars=in_turn, trim_to=in_turn // 2,
        preserve_tail=0 if oversized_feedback else pending_feedback, size_of=_rendered_size)
    pending_feedback = 0
    if oversized_feedback:
        notes.append("The newest tool-result batch exceeded the bounded delivery window. Some newly fetched "
                     "content may have been omitted before you saw it. Do not claim to have inspected omitted "
                     "content; request smaller sequential reads or disclose the limitation within remaining budgets.")
    history_compacted = history_compacted or compacted
    if history_compacted:
        notes.append("Earlier conversation turns were compacted. Do not repeat completed effects." + (
            " Saved task progress and owned outputs remain available through task_progress."
            if "task_progress" in wired_keys else
            " task_progress is not available in this turn; do not invent a call to it."))
    state.convo, state.pending_feedback, state.history_compacted = convo, pending_feedback, history_compacted


async def _request(request: TurnRequest, state: TurnState, mode: StepMode, notes: list[str]) -> StepReply | dict:
    """LOOP1 c3: this step's request, with its status block and the messages sent meanwhile that it carries. If the
    reply fails after part of the answer went out, the turn ends here (the dict). A schema the provider refused
    reads the table again."""
    from server.orchestrator import agent_status
    conversation_id, allow_escalation, turn_notes = request.conversation_id, request.allow_escalation, request.turn_notes
    a, system, convo, current_request, tool_trace, plan = (
        state.adapter, state.system, state.convo, state.current_request, state.tool_trace, state.plan)
    budget, turn_state, drops, turn_text, acceptance_runtime = (
        state.budget, state.recovery, state.drops, state.turn_text, state.acceptance_runtime)
    lesson_notes, ws_root, own_folder, turn_started = state.lesson_notes, state.ws_root, state.own_folder, state.started
    wired, wired_keys, schemas, params_by_key = state.wired, state.wired_keys, state.schemas, state.params_by_key
    history_compacted, forced = state.history_compacted, mode.forced
    # On the forced step pass tools=None so the model CANNOT call a tool and MUST produce
    # prose from the accumulated TOOL RESULTs — never an empty turn.
    # Rolling evidence eviction must not erase this turn's task or its
    # restrictions. Restore the exact request at user priority, not as a
    # system instruction or an invented summary, only in this payload.
    # K3: the same tool table on every step of the turn, wrapping up included (a narrowed table was a
    # cache miss from the tools on, K1b). Exceptions, one miss each: a capability added mid-turn, an
    # MCP schema the provider refused, relax() on a retry.
    step_tools = None if forced else schemas
    offered = {t["function"]["name"] for t in step_tools or []}
    # Nothing done, planned or noted yet (a plain chat turn, or step 0): no
    # block — the request goes out as the user wrote it. Step 0's write
    # facts live in the tool descriptions (S5); the block starts with work.
    # 0.1.63 D1: turn_notes are host facts about this whole turn (a turn from the iPhone).
    turn_lines = list(turn_notes or ())
    status = "" if not (tool_trace or notes or plan.items or lesson_notes or turn_lines) else agent_status.render(
        workspace=agent_status.home_relative(ws_root) if ws_root is not None else None,
        writers=[k for k in ("write_file", "edit_file", "run_command") if k in offered],
        own_folder=own_folder, saved=agent_status.owned_outputs(tool_trace, ws_root, turn_started),
        plan=plan.render(), tool_calls=budget.tool_calls, model_calls=budget.model_requests,
        wrap_up_at=budget.soft.tool_calls if budget.soft is not None else None,
        notes=lesson_notes + turn_lines + notes)
    try:
        usage_sink.note_context_parts(_context_parts(system, schemas, convo, current_request, status))
    except Exception:  # noqa: BLE001 — the ring's breakdown is telemetry: it never fails a turn
        logger.warning("context parts not measured", exc_info=True)
        usage_sink.note_context_parts(None)      # say nothing rather than show an older request's
    if state.steers:
        # K9b: this request carries them, once it is sure to go (its tokens and dollars too, which the
        # provider checks as it sends; a stop here hands them back).
        budget.check_request()
        await _commit_steers(state.steers, conversation_id)
    stream = _StepStream(turn_text) if turn_text is not None else None
    try:
        resp = await _model_call(a, system, convo, current_request, tools=step_tools,
                                 schemas=schemas, forced=forced, state=turn_state, status=status,
                                 drops=drops, conversation_id=conversation_id, step=stream)
    except TextShown:
        # K8a (⓪Plan Q2): part of the answer is out; resending would show it twice. The turn ends with
        # what was shown and says so, and the run records a failure (no `error` frame: the window
        # would drop the text the phone kept).
        from server.services import host_run, runtime_messages
        stream.finish()
        turn_text.append(runtime_messages.render("stream_interrupted", await runtime_messages.selected_locale()),
                         answer=False)
        host_run.note_failure("model_error_after_text")
        if acceptance_runtime is not None:
            acceptance_runtime.pause_reason = "model_error_after_text"
        return {"final": turn_text.text, "escalation": None, "tool_trace": tool_trace,
                "stop_reason": "model_error_after_text", "history_compacted": history_compacted}
    if stream is not None:
        stream.finish()
    if drops.changed:              # a refused MCP schema was left out: the rest of the turn too
        drops.changed = False
        wired = drops.keep(wired)
        wired_keys = {t["key"] for t in wired}
        schemas = _native_tool_schemas(wired, allow_escalation=allow_escalation)
        params_by_key = {t["key"]: _tool_params(t) for t in wired}
    # A context-overflow recovery compacted convo in place (S6).
    history_compacted = history_compacted or turn_state.context_retry_used
    tool_calls = list(getattr(resp, "tool_calls", None) or [])
    state.wired, state.wired_keys, state.schemas, state.params_by_key = wired, wired_keys, schemas, params_by_key
    state.history_compacted = history_compacted
    return StepReply(resp=resp, stream=stream, tool_calls=tool_calls)


async def _run_native(request: TurnRequest, state: TurnState) -> dict:
    """Canonical native tool loop. Its core return shape
    ({"final": str|None, "escalation": dict|None, "tool_trace": list}).

    Each step calls adapter.chat(..., tools=schemas) → LLMResponse{content, tool_calls}:
      - tool_calls non-empty → dispatch each through the shared gate; content is narration
        ONLY, never surfaced as the answer; continue.
      - escalate tool call → return {"escalation": {...}} (when allow_escalation).
      - no tool_calls → content IS the final answer; stream it and return.
      - no progress or no remaining tools → one text-only synthesis if request budget permits.

    Production calls use the shared task budget, with no fixed eight-round cap.
    max_tool_calls is an optional explicit compatibility ceiling, never a default.

    LOOP1 c3: the turn opens (`_open_turn`, `_presearch`), then each step runs its phases (`_step_mode`,
    `_step_notes`, `_fit_history`, `_request`) and either its tool batch (`tool_batch.run_batch`) or its answer
    (`turn_answer.finish`).
    """
    opened = await _open_turn(request, state)
    if opened is not None:
        return opened
    await _presearch(request, state)
    from server.orchestrator import tool_batch      # tool_batch imports this module
    state.offline_note = _OFFLINE_NOTE if "run_command" in state.wired_keys else ""
    state.can_save = bool(WRAP_UP_TOOLS & state.wired_keys)
    # Set once when the turn opened and never rebound, so the end below reads them by name, as before.
    budget, runtime = state.budget, state.runtime
    for step in range(state.request_ceiling):
        mode = _step_mode(request, state, step)
        notes, wrap_up = await _step_notes(request, state, mode)
        _fit_history(state, notes)
        reply = await _request(request, state, mode, notes)
        if isinstance(reply, dict):
            return reply

        if not mode.forced and reply.tool_calls:
            # Each call through its stages: arguments, host tools, the unwrap, the gates, execute and after.
            ended = await tool_batch.run_batch(request, state, step, mode, reply, wrap_up)
            if ended is not None:
                return ended
            continue
        # No tool calls (or forced): the step's answer, through its guards. None: a correction or a repair went back
        # to the model, and the next step answers it.
        answered = await turn_answer.finish(request, state, mode, reply)
        if answered is not None:
            return answered

    if runtime:
        runtime.pause_reason = "task_budget_exhausted"
    budget.stop("model_requests")

"""One model call of a turn's step: what is sent, and how a refused or cut request recovers (split from tool_loop, LOOP1
c1b)."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from contextvars import ContextVar

from arslan.llm import tool_names, trajectory
from arslan.runtime_policy import bounded_history

from server.orchestrator import turn_context
from server.orchestrator.turn_state import ResolveTools
from server.orchestrator.turn_stream import TextShown, _StepStream
from server.orchestrator.untrusted import wrap_external

logger = logging.getLogger(__name__)


# 0.1.63 K1b: set for each step of a turn whose provider clears old context itself (Claude's native
# path): what was sent is never edited again, so screenshots are not turned into stubs here.
_SENT_IS_FINAL: ContextVar[bool] = ContextVar("sent_is_final", default=False)


def _server_trims(a, state) -> bool:
    """Whether this step goes natively to a provider that clears old tool results server-side."""
    use_native = getattr(a, "native_trajectory", None)
    trims = getattr(getattr(a, "_provider", None), "trims_context_server_side", None)
    return bool(not state.legacy and callable(use_native) and use_native() and callable(trims) and trims())


def _render_request(convo: list[dict], current_request: dict, status: str = "") -> list[dict]:
    """The model input for this step. Rolling eviction must not erase this
    turn's task: restore the exact request at user priority (not a summary,
    not a system instruction) in this payload only. The step's <agent_status>
    rides at the end of the last message (agent_status.attach), never stored."""
    from server.orchestrator import agent_status
    messages = convo if any(item is current_request for item in convo) else [current_request, *convo]
    rendered = trajectory.to_legacy(messages)
    # Last means last: after the legacy trailer too. A Gemini function-response
    # turn (list content) carries it inside the newest result instead.
    if status and rendered and isinstance(rendered[-1].get("content"), str):
        return agent_status.attach(rendered, status)
    return trajectory.to_legacy(agent_status.attach(messages, status))


CONTINUE_PROMPT = ("Your previous reply was cut off by the output limit. Continue exactly where it "
                   "stopped, without repeating anything already written and without any preamble.")


# Hands v2 §4.4: model configurations that refused an image this process. Their screenshots are
# read by this Mac's text recognition before sending, instead of failing again.
_REFUSES_IMAGES: set[tuple[str, str, str]] = set()


# 0.1.62 F3: (model, tool key, sha256 of the schema as the server wrote it) for MCP schemas a
# provider refused this process. A changed schema hashes differently and is tried again.
_BAD_TOOLS: set[tuple[tuple[str, str, str], str, str]] = set()


def _model_key(a) -> tuple[str, str, str]:
    provider = getattr(a, "_provider", None)
    return (type(provider).__name__, str(getattr(provider, "model", "")), str(getattr(provider, "base_url", "")))


# ── 0.1.62 F3: a refused MCP schema costs that tool, at worst every MCP tool, never the turn ──
# A fallback for what arslan/llm/tool_schema.normalise does not cover. Delete with _BAD_TOOLS
# once the M2 weekly report shows zero `mcp_schema_relaxed` four weeks running (v0.1.65 at the
# earliest; docs/plans/0162/F3-mcp-schema.md).
_SCHEMA_WORDS = re.compile(r"\b(tools?|functions?|schema|parameters)\b", re.I)


def _schema_hash(params) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()


class _SchemaDrops:
    """The MCP tools one turn leaves out: refused by name this turn, every one after a second
    refusal, and any this model refused earlier in this process (_BAD_TOOLS)."""

    def __init__(self, a):
        self.model = _model_key(a)
        self.names: set[str] = set()
        self.every = False
        self.changed = False

    def hides(self, key: str, params) -> bool:
        return key.startswith("mcp_") and (
            self.every or key in self.names or (self.model, key, _schema_hash(params)) in _BAD_TOOLS)

    def keep(self, wired: list[dict]) -> list[dict]:
        from server.orchestrator.tool_loop import _tool_params     # tool_loop imports this module; a5 moves the schemas
        return [t for t in wired if not self.hides(t["key"], _tool_params(t))]

    def keep_schemas(self, schemas):
        if schemas is None:
            return None
        return [t for t in schemas
                if not self.hides(t["function"]["name"], t["function"].get("parameters"))] or None


def _hiding(resolve_tools: ResolveTools, drops: _SchemaDrops) -> ResolveTools:
    """resolve_tools as this turn sees it: the step's tool list, the capability refresh and the
    executor's `live` check all go through it, so a left-out tool answers `tool_unavailable`."""
    async def resolve() -> list[dict]:
        return drops.keep(await resolve_tools())
    return resolve


def _refused_tool(a, sent: list[dict], text: str) -> str | None:
    """The MCP tool a refusal points at, only ever one this request carried: the provider reads
    its own error against its own payload order, else the longest MCP name the text mentions.
    NAME1: the provider wrote the names it was sent (tool_names.wire); both lead back to the key."""
    mcp = {t["function"]["name"] for t in sent if t["function"]["name"].startswith("mcp_")}
    named = getattr(a, "named_tool", None) or getattr(getattr(a, "_provider", None), "named_tool", None)
    name = named(sent, text) if callable(named) else None
    if name in mcp:
        return name
    mentioned = {n: max(len(form) for form in (n, tool_names.wire(n)) if form in text)
                 for n in mcp if n in text or tool_names.wire(n) in text}
    return max(sorted(mentioned), key=mentioned.get) if mentioned else None


async def _images_to_text(convo: list[dict]) -> int:
    """Tier 2 (spec §4.4, server/services/ocr_fallback.py): every screenshot in this turn becomes
    the text macOS Vision reads off it, framed as untrusted like the window it came from.
    In place; returns how many were read."""
    import asyncio
    import base64
    from server.services import ocr_fallback
    ui_language, chosen = await ocr_fallback.current_ui_language(), await ocr_fallback.current_ocr_languages()
    read = 0
    for message in convo:
        images = message.pop("_images", None)
        if not images:
            continue
        label = message.pop("_image_label", None) or message.get("name") or "screenshot"
        texts = []
        for image in images:
            try:
                data = base64.b64decode(image["data"])
            except (KeyError, ValueError):
                continue
            text, _status = await asyncio.to_thread(ocr_fallback.read_locally, data, ui_language=ui_language,
                                                    chosen_languages=chosen)
            texts.append(text)
            read += 1
        body = "\n".join(t for t in texts if t) or "(no text could be read off it)"
        message["content"] = (f"{message.get('content', '')}\n[screenshot of {label}: this model cannot take "
                              f"images; the text this Mac read off it follows]\n{wrap_external(body)}")
    return read


async def _model_call(a, system: str, convo: list[dict], current_request: dict, *,
                      tools, schemas, forced: bool, state, status: str = "",
                      drops: _SchemaDrops | None = None, conversation_id: str | None = None,
                      step: "_StepStream | None" = None):
    """The one model call of a run_native step, with recovery (0.1.49 S6).

    Native adapters (OpenAI-compatible and Gemini; Claude from K1b;
    ARSLAN_TOOL_PROTOCOL not "legacy") get the trajectory in their own tool
    protocol; a forced step keeps the SAME tools with tool_choice "none".
    Everything else (test doubles, rollback) gets the legacy rendering, unchanged.

    Recovery (server/orchestrator/model_call.py): classified transport retries;
    a protocol rejection switches this turn to the legacy rendering; a context
    overflow compacts once; a finish_reason "length" cut is re-sent with the
    endpoint's ceiling, then a cut answer is continued. A cut tool call is
    returned as is: run_native never executes it. `state` is per turn.

    `status` (0.1.50 S1) is appended to the last message of the step's base
    messages in both renderings (on a provider with APPENDS_STATUS natively: stored
    once in the trajectory as its own block, K1); continuation turns follow it, so a
    continuation request shares the original request's exact prefix.

    `step` (K8a) gets the answer's text as it arrives, where the endpoint streams. Once some of it was
    shown, nothing re-sends the request (a retry, a protocol switch, a compaction or a raised output limit
    would show it twice): TextShown ends the turn instead. A cut answer is still continued."""
    from server.orchestrator import agent_status
    from server.orchestrator import model_call as mc

    def build_messages():
        return convo if any(item is current_request for item in convo) else [current_request, *convo]

    if trajectory.image_count(convo) and _model_key(a) in _REFUSES_IMAGES:
        await _images_to_text(convo)          # known not to take images: read them first
    messages = build_messages()
    native = False
    use_native = getattr(a, "native_trajectory", None)
    if not state.legacy and callable(use_native) and use_native():
        try:
            trajectory.validate(messages)
            native = True
        except trajectory.TrajectoryError as exc:
            # Never send a malformed native history; the legacy rendering of the
            # same trajectory is always well-formed. Sticky for this turn.
            state.legacy, state.reason = True, f"invalid trajectory: {exc}"
            logger.warning("native tool protocol degraded to legacy: %s", exc)
    # 0.1.63 K1: a provider that must never see history edited (Claude's preserved thinking; Gemini
    # too) keeps each step's status in the trajectory, as its own block after the step's results,
    # instead of having it glued onto the last message for one request and gone the next.
    status_record = None
    if native and status and getattr(getattr(a, "_provider", None), "APPENDS_STATUS", False):
        status_record = trajectory.status(status)
        convo.append(status_record)
        messages = build_messages()

    async def request(extra=None, max_tokens=None):
        base = list(messages) if status_record is not None and native else agent_status.attach(messages, status)
        sent = base + list(extra or [])
        kwargs = {"max_tokens": max_tokens} if max_tokens else {}
        if native:
            step_tools = schemas if forced else tools
            # tool_choice only with tools: leaving every MCP tool out (0.1.62 F3) can empty the list.
            if step is not None:
                kwargs["on_text"] = step.feed
            return await a.chat_trajectory(system, sent, tools=step_tools,
                                           tool_choice="none" if forced and step_tools else None, **kwargs)
        # One legacy entry point (_render_request) for every request of the step.
        rendered = _render_request(convo, current_request, status) + trajectory.to_legacy(list(extra or []))
        return await a.chat(system, rendered[-1]["content"], history=rendered[:-1], tools=tools, **kwargs)

    async def relax(exc, *, last: bool = False) -> bool:
        """0.1.62 F3: an `input` refusal of a request carrying MCP tools that names one (or reads
        like a schema problem): leave it out (`last`, or none named: every MCP tool) and say so."""
        nonlocal tools, schemas, status, status_record, messages
        sent = ((schemas if forced else tools) if native else tools) or []
        if (drops is None or exc.kind not in ("input", "protocol") or state.exhausted
                or not any(t["function"]["name"].startswith("mcp_") for t in sent)):
            return False
        text = exc.excerpt or ""        # the provider's own words; str(exc) also carries our recovery notes
        name = _refused_tool(a, sent, text)
        # 0.1.63 K1a: a refusal naming an MCP tool whose name holds a protocol word
        # (mcp_1__get_tool_result) classifies as "protocol"; it is still that tool's schema.
        if exc.kind == "protocol" and name is None:
            return False
        if name is None and not _SCHEMA_WORDS.search(text):
            return False
        if name is not None:            # remembered even when this is the last try and every tool goes
            params = next(t["function"].get("parameters") for t in sent if t["function"]["name"] == name)
            drops.names.add(name)
            _BAD_TOOLS.add((drops.model, name, _schema_hash(params)))
        if name is None or last:
            drops.every, left_out = True, "all"
        else:
            left_out = name
        drops.changed = True
        tools, schemas = drops.keep_schemas(tools), drops.keep_schemas(schemas)
        what = "every MCP tool" if left_out == "all" else f"the MCP tool {left_out}"
        state.note(f"left out {what} (the provider refused its parameter schema)")
        shown = "every MCP tool" if left_out == "all" else f"the MCP tool {tool_names.wire(left_out)}"  # NAME1
        status = (f"{status}\n\n" if status else "") + (
            f"Note: {shown} is not available in this turn: the model provider refused its parameter "
            "schema. Use the other tools, or tell the user that capability cannot be used right now.")
        if status_record is not None:
            status_record["content"] = status       # not accepted by the provider yet: still editable
        elif native and getattr(getattr(a, "_provider", None), "APPENDS_STATUS", False):
            status_record = trajectory.status(status)
            convo.append(status_record)
            messages = build_messages()
        provider = getattr(a, "_provider", None)
        reported = getattr(a, "report_provider", None) or getattr(provider, "provider_name", type(provider).__name__)
        try:
            from server.services import recap_service
            await recap_service.log_event(
                conversation_id, "mcp_schema_relaxed", {"tool_key": left_out, "provider": str(reported)},
                f"left out {what}: the provider refused its parameter schema")
        except Exception:  # noqa: BLE001 — observability is never fatal
            pass
        return True

    remaining = _remaining_seconds()
    relaxed = False
    try:
        resp = await mc.call_with_recovery(_once_shown(request, step), state, remaining_s=remaining)
    except mc.ModelCallError as exc:
        from server.services import ocr_fallback
        if step is not None and step.released:
            raise TextShown(exc.excerpt) from exc
        # First: an image refusal can also look like a protocol rejection; switching protocols
        # would send the same screenshots again and fail the same way.
        if (trajectory.image_count(convo) and not state.images_read_locally
                and ocr_fallback.model_refused_the_image(f"{exc.excerpt} {exc}")):
            # §4.4: the model refused the screenshots as images (vision_errors' narrow match, never
            # a rate limit or a bad key). Read them locally, remember this model, ask once more.
            state.images_read_locally = True
            _REFUSES_IMAGES.add(_model_key(a))
            await _images_to_text(convo)
            messages = build_messages()
            state.note("read screenshots as text (this model cannot take images)")
        elif await relax(exc):
            relaxed = True
        elif exc.kind == "protocol" and native and not state.exhausted:
            native = False
            state.legacy, state.reason = True, f"endpoint rejected native history: {exc.excerpt[:200]}"
            state.note("switched to the legacy tool protocol")
            logger.warning("native tool protocol degraded to legacy: %s", exc.excerpt[:200])
        elif exc.kind == "context" and not state.context_retry_used and not state.exhausted:
            state.context_retry_used = True
            convo[:], _ = bounded_history(convo, max_chars=max(8_000, _rendered_size(convo) // 2),
                                          size_of=_rendered_size)
            messages = build_messages()
            state.note("compacted context")
            if _SENT_IS_FINAL.get():
                # K1b: the one edit of sent history this path allows; thinking blocks after it drop.
                from arslan.execution_budget import current
                if (budget := current()) is not None:
                    budget.note_context("compacted", reason="context_overflow", count=1)
        else:
            raise
        try:
            resp = await mc.call_with_recovery(_once_shown(request, step), state, remaining_s=remaining)
        except mc.ModelCallError as again:
            # Refused again after one tool was left out: every MCP tool goes, for one last try.
            if not (relaxed and await relax(again, last=True)):
                raise
            resp = await mc.call_with_recovery(_once_shown(request, step), state, remaining_s=remaining)
    return await _recover_truncation(a, resp, request, state, remaining, step)


def _once_shown(make, step: "_StepStream | None"):
    """K8a: `make` for call_with_recovery, whose retries resend the whole request. A retry goes out only
    while nothing of the failed attempt was shown; otherwise TextShown (never classified, never retried)."""
    tries = 0

    async def attempt():
        nonlocal tries
        tries += 1
        if tries > 1 and step is not None and not step.retry_ok():
            raise TextShown("the model stopped after part of the answer was shown")
        return await make()
    return attempt


def _remaining_seconds():
    from arslan.execution_budget import current
    budget = current()
    return budget.remaining_seconds if budget is not None else None


def _output_clamped() -> bool:
    from arslan.execution_budget import current
    budget = current()
    return bool(budget is not None and budget.last_output_clamped)


def _replaced(resp, **fields):
    if hasattr(resp, "model_copy"):
        return resp.model_copy(update=fields)
    import copy
    clone = copy.copy(resp)
    for key, value in fields.items():
        setattr(clone, key, value)
    return clone


async def _recover_truncation(a, resp, request, state, remaining, step=None):
    """finish_reason == "length": raise to the endpoint's ceiling once, then
    continue a cut answer. A cut caused by the work budget is not raised (that
    would spin: raise -> clamp -> cut). Per-turn caps live on `state`. Once the
    answer was shown as it was written (K8a), only continuing it is allowed."""
    from server.orchestrator import model_call as mc
    if getattr(resp, "finish_reason", None) != "length" or _output_clamped():
        return resp
    provider = getattr(a, "_provider", None)
    ceiling, current_max = getattr(provider, "output_ceiling", None), getattr(provider, "max_tokens", None)
    raise_to = ceiling if isinstance(ceiling, int) and isinstance(current_max, int) and ceiling > current_max else None
    if raise_to and state.output_raises < 2 and not state.exhausted and not (step is not None and step.released):
        state.output_raises += 1
        state.note(f"raised output limit to {raise_to}")
        resp = await mc.call_with_recovery(_once_shown(lambda: request(max_tokens=raise_to), step), state,
                                           remaining_s=remaining)
        if getattr(resp, "finish_reason", None) != "length" or _output_clamped():
            return resp
    text = resp.content or ""
    if getattr(resp, "tool_calls", None) or not text.strip():
        return resp     # cut tool call (never executed) or reasoning-only cut: caller handles
    last = resp
    while state.continuations < 2 and not state.exhausted:
        state.continuations += 1
        state.note("continued a cut-off answer")
        # Reasoning belongs to one reply's own text; joined text has none.
        extra = [trajectory.assistant(text, continuation=getattr(last, "continuation", None)
                                      if last is resp else None),
                 {"role": "user", "content": CONTINUE_PROMPT}]
        last = await mc.call_with_recovery(_once_shown(lambda: request(extra=extra, max_tokens=raise_to), step),
                                           state, remaining_s=remaining)
        text += last.content or ""
        if getattr(last, "finish_reason", None) != "length" or getattr(last, "tool_calls", None) \
                or _output_clamped():
            break
    # The joined text is no single reply's output: no continuation state.
    return _replaced(resp, content=text, finish_reason=getattr(last, "finish_reason", None),
                     tool_calls=[], continuation=None)


def _context_parts(system: str, schemas: list[dict] | None, convo: list[dict], current_request: dict,
                   status: str) -> dict[str, int]:
    """0.1.63 K4b: what the request about to be sent is made of, estimated with the one estimator, for
    the composer's ring breakdown (its total stays the provider's last_input): the system text, the
    tools, the turn's reference block (memory and context), earlier turns, and this turn (the user's
    words, tool calls and results, kept and current status blocks)."""
    from arslan.context_budget import IMAGE_TOKEN_GUESS, estimate_tokens

    def size(messages: list[dict]) -> int:
        rendered = json.dumps(trajectory.to_legacy(messages, images=False), ensure_ascii=False, default=str)
        kept = "".join(m.get("content") or "" for m in messages if m.get("_status"))
        return (estimate_tokens(rendered) + estimate_tokens(kept)
                + IMAGE_TOKEN_GUESS * trajectory.image_count(messages))
    at = next((i for i, m in enumerate(convo) if m is current_request), None)
    history, after = (convo[:at], convo[at + 1:]) if at is not None else ([], convo)
    content = current_request.get("content")
    words = estimate_tokens(turn_context.users_words(content))
    return {"system": estimate_tokens(system),
            "tools": estimate_tokens(json.dumps(schemas, ensure_ascii=False)) if schemas else 0,
            "context": max(0, estimate_tokens(content) - words),
            "history": size(history),
            "turn": words + size(after) + estimate_tokens(status)}


def _rendered_size(messages: list[dict]) -> int:
    """Context size of what is actually sent, not of local bookkeeping. Kept status blocks
    (trajectory.status, K1) are sent natively though the legacy rendering leaves them out."""
    kept = sum(len(m.get("content") or "") for m in messages if m.get("_status"))
    return (len(json.dumps(trajectory.to_legacy(messages, images=False), ensure_ascii=False, default=str))
            + trajectory.IMAGE_SIZE_CHARS * trajectory.image_count(messages) + kept)

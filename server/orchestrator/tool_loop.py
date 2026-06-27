"""Bounded mini agent-loop, spawn-agnostic (Phase 1 of the capability/MCP layer).

Output protocol per step (model replies with ONE of):
  plain text                                      -> final answer
  {"tool": "<key>", "args": {...}}                -> tool call
  {"escalate": {"kind","need","context"}}         -> end turn, raise to caller
"""
from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable

from server.orchestrator.json_protocol import first_json_object, parse_json_object
from server.orchestrator.untrusted import GUARD_NOTE, wrap_external
from server.registry.executors import EXECUTORS
from server.services.llm_factory import build_adapter

MAX_TOOL_CALLS = 5
TOOL_TIMEOUT_S = 20.0

_PROTOCOL = (
    "\n\nTOOL PROTOCOL: To use a tool, reply with ONLY this JSON and nothing else — NO text "
    "before or after it, not even '好的' / 'let me search'; the JSON object must be the ENTIRE "
    "message: "
    '{{"tool": "<name>", "args": {{...}}}}. Available tools:\n{tool_lines}\n'
    "To escalate a missing capability or missing data, reply with ONLY: "
    '{{"escalate": {{"kind": "data" or "capability", "need": "<what outcome you need>", '
    '"context": "<why>"}}}} — describe the OUTCOME you need, never an operation to run.\n'
    "If a tool reports it is not configured, tell the user plainly and answer with what you know.\n"
    "Otherwise reply with your final answer as normal text.\n\n"
    f"{GUARD_NOTE}"
)

ResolveTools = Callable[[], Awaitable[list[dict]]]


def _get_adapter():
    """Indirection so tests can stub adapter construction."""
    return build_adapter(role="execute")


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


_CLAIMS_CHART_RE = re.compile(
    r"上图|已生成图|已为您生成|已绘制|图表已|chart (is )?(generated|ready|done)|here('s| is) (the|your) chart",
    re.IGNORECASE)
_CLAIMS_SEARCH_RE = re.compile(
    r"我搜索|搜索了|查到了?|获取到(了|的)?数据|我已搜|i (just )?searched|let me search|i looked it up",
    re.IGNORECASE)


def _claims_chart(text: str) -> bool:
    return bool(_CLAIMS_CHART_RE.search(text or ""))


def _claims_search(text: str) -> bool:
    return bool(_CLAIMS_SEARCH_RE.search(text or ""))


async def _dispatch_tool(tool_key, args, assistant_content, *, resolve_tools, emit,
                         tool_timeout_s, tool_trace, convo) -> dict:
    """Execute one tool (gated), emit its frames, record the trace, and append the
    assistant turn + framed tool result into convo. Returns the raw result dict."""
    emit({"type": "tool_call", "tool": tool_key,
          "args_summary": json.dumps(args, ensure_ascii=False)[:200]})
    live = {t["key"] for t in await resolve_tools()}
    if tool_key not in live or tool_key not in EXECUTORS:
        result = {"ok": False, "error": f"tool '{tool_key}' is not available to you; you may escalate a need instead"}
    else:
        try:
            result = await asyncio.wait_for(EXECUTORS[tool_key].execute(args), timeout=tool_timeout_s)
        except TimeoutError:
            result = {"ok": False, "error": f"tool '{tool_key}' timed out"}
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error": f"tool '{tool_key}' failed: {exc}"}
    emit({"type": "tool_result", "tool": tool_key, "ok": bool(result.get("ok")),
          "summary": _summarize_result(result), "artifact": result.get("artifact")})
    tool_trace.append({"tool": tool_key, "args": args, "result": result})
    convo.append({"role": "assistant", "content": assistant_content})
    feedback = {k: v for k, v in result.items() if k != "artifact"}
    raw_payload = json.dumps(feedback, ensure_ascii=False)[:8000]
    framed = raw_payload if result.get("external") is False else wrap_external(raw_payload)
    convo.append({"role": "user",
                  "content": f"TOOL RESULT for {tool_key}:\n{framed}"
                             "\nUse this to continue: call another tool, escalate, or give your final answer."})
    return result


async def run(
    *,
    system: str,
    user_content: str,
    history: list[dict],
    emit: Callable[[dict], None],
    on_chunk: Callable[[str], None],
    resolve_tools: ResolveTools,
    allow_escalation: bool = True,
    max_tool_calls: int = MAX_TOOL_CALLS,
    tool_timeout_s: float = TOOL_TIMEOUT_S,
    force_tools: bool = False,
) -> dict:
    """Run the loop. Returns {"final": str|None, "escalation": dict|None, "tool_trace": list}.
    Exactly one of final/escalation is non-None. resolve_tools() returns the currently
    live tool descriptors [{"key","description"}] — re-awaited per call so grants can expire."""
    adapter = _get_adapter()
    a = await adapter if hasattr(adapter, "__await__") else adapter

    wired = await resolve_tools()
    tool_lines = "\n".join(f"- {t['key']}: {t['description']}" for t in wired) or "- (none live)"
    system = system + _PROTOCOL.format(tool_lines=tool_lines)

    convo = list(history) + [{"role": "user", "content": user_content}]
    tool_trace: list[dict] = []
    fired: set[str] = set()          # tool keys actually executed this run
    forced_retry: set[str] = set()   # tools we've already forced a retry for (bound the loop)
    wired_keys = {t["key"] for t in wired}

    # Proactive deterministic forcing (spawn path only): when force_tools=True and the
    # classifier says the task needs web_search, run it ourselves before the model's first
    # turn — no model dependence. Only web_search is force-run (its call is a deterministic
    # {"query": ...} we can build from the task); other tools still go through the model.
    if force_tools and "web_search" in wired_keys and "web_search" in EXECUTORS:
        from server.services import tool_intent
        try:
            intent = await tool_intent.classify(user_content, sorted(wired_keys))
        except Exception:  # noqa: BLE001
            intent = None
        if intent is not None and intent.needs and intent.tool == "web_search":
            q = (intent.query or user_content)[:400]
            await _dispatch_tool("web_search", {"query": q},
                                 json.dumps({"tool": "web_search", "args": {"query": q}}, ensure_ascii=False),
                                 resolve_tools=resolve_tools, emit=emit, tool_timeout_s=tool_timeout_s,
                                 tool_trace=tool_trace, convo=convo)
            fired.add("web_search")

    for step in range(max_tool_calls + 1):
        forced = step == max_tool_calls
        sys_now = system if not forced else (
            system + "\n\nTool budget exhausted: answer now with what you have. Text only."
        )
        raw = ""
        shown = 0  # chars already forwarded to on_chunk — never includes a '{'-led tool/escalate JSON
        async for piece in a.chat_stream(sys_now, convo[-1]["content"], history=convo[:-1]):
            raw += piece
            if not raw.lstrip():
                continue                           # still only whitespace; keep accumulating
            # Structural separation (no first-char guessing): stream visible prose ONLY up to the
            # first '{'. Any tool/escalate JSON — even when the model prepends prose like '好的我去搜'
            # — is buffered from the '{' onward and never shown. parse_json_object (below) rescues an
            # embedded object, so the tool still fires; the raw JSON just never reaches the user.
            brace = raw.find("{")
            visible_end = brace if brace != -1 else len(raw)
            if visible_end > shown:
                on_chunk(raw[shown:visible_end])
                shown = visible_end
        content = raw.strip()
        # first_json_object extracts the FIRST balanced {...} (handles prose + multiple objects,
        # e.g. '好我去搜{tool a}{tool b}' → dispatch tool a now, the rest on a later step).
        parsed = first_json_object(content) or parse_json_object(content)

        if not forced and isinstance(parsed, dict) and isinstance(parsed.get("escalate"), dict):
            if not allow_escalation:
                convo.append({"role": "assistant", "content": content})
                convo.append({"role": "user",
                              "content": "Escalation is not available right now; answer "
                                         "with what you have."})
                continue
            esc = parsed["escalate"]
            return {"final": None, "tool_trace": tool_trace,
                    "escalation": {"kind": str(esc.get("kind") or "data"),
                                   "need": str(esc.get("need") or "").strip(),
                                   "context": str(esc.get("context") or "").strip()}}

        if not forced and isinstance(parsed, dict) and parsed.get("tool"):
            tool_key = str(parsed["tool"])
            args = parsed.get("args") if isinstance(parsed.get("args"), dict) else {}
            await _dispatch_tool(tool_key, args, content, resolve_tools=resolve_tools,
                                 emit=emit, tool_timeout_s=tool_timeout_s,
                                 tool_trace=tool_trace, convo=convo)
            fired.add(tool_key)
            continue

        # Reactive hallucination guard: the model claims a tool result it never produced this run.
        if not forced:
            claimed = None
            if (_claims_chart(content) and "render_chart" in wired_keys
                    and "render_chart" not in fired and "render_chart" not in forced_retry):
                claimed = "render_chart"
            elif (_claims_search(content) and "web_search" in wired_keys
                    and "web_search" not in fired and "web_search" not in forced_retry):
                claimed = "web_search"
            if claimed:
                forced_retry.add(claimed)
                convo.append({"role": "assistant", "content": content})
                convo.append({"role": "user", "content":
                    f"You claimed to have used {claimed} (searched / produced a chart), but you did NOT "
                    f"actually call it this turn — so there is no result and no chart. Emit ONLY the "
                    f"{claimed} tool JSON now, or answer honestly WITHOUT claiming you used a tool or made a chart."})
                continue

        # plain text = final answer (parsed was not a dispatchable tool/escalate)
        if isinstance(parsed, dict):
            # The model emitted a real JSON object that we did NOT dispatch (a non-tool dict, or
            # extra/garbled tool blobs after the first). It is protocol output, not prose — drop
            # it from BOTH display and the persisted final. The answer is the prose before it
            # (already streamed up to the first '{').
            brace = raw.find("{")
            final_text = raw[:brace].strip() if brace != -1 else content
            if not final_text:
                # nothing but a JSON object and no prose → show it rather than an empty reply
                final_text = content
                if shown < len(raw):
                    on_chunk(raw[shown:])
        else:
            # no valid JSON object: any '{' was ordinary prose → flush the unshown remainder
            if shown < len(raw):
                on_chunk(raw[shown:])
            final_text = content
        return {"final": final_text, "escalation": None, "tool_trace": tool_trace}

    raise AssertionError("unreachable")  # forced branch always returns

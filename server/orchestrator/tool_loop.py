"""Bounded mini agent-loop, spawn-agnostic (Phase 1 of the capability/MCP layer).

Output protocol per step (model replies with ONE of):
  plain text                                      -> final answer
  {"tool": "<key>", "args": {...}}                -> tool call
  {"escalate": {"kind","need","context"}}         -> end turn, raise to caller
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

from server.orchestrator.json_protocol import parse_json_object
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
    if "results" in result:
        return f"{len(result['results'])} results"
    if "text" in result:
        return f"{len(result['text'])} chars extracted"
    return "ok"


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
        parsed = parse_json_object(content)

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
            emit({"type": "tool_call", "tool": tool_key,
                  "args_summary": json.dumps(args, ensure_ascii=False)[:200]})
            # Gate: re-resolve the live tool set per call (grants may expire); execute
            # only if the key is both currently allowed AND backed by an executor.
            live = {t["key"] for t in await resolve_tools()}
            if tool_key not in live or tool_key not in EXECUTORS:
                result = {"ok": False,
                          "error": f"tool '{tool_key}' is not available to you; "
                                   "you may escalate a need instead"}
            else:
                try:
                    result = await asyncio.wait_for(
                        EXECUTORS[tool_key].execute(args), timeout=tool_timeout_s
                    )
                except TimeoutError:
                    result = {"ok": False, "error": f"tool '{tool_key}' timed out"}
                except Exception as exc:  # noqa: BLE001
                    result = {"ok": False, "error": f"tool '{tool_key}' failed: {exc}"}
            emit({"type": "tool_result", "tool": tool_key,
                  "ok": bool(result.get("ok")), "summary": _summarize_result(result)})
            tool_trace.append({"tool": tool_key, "args": args, "result": result})
            convo.append({"role": "assistant", "content": content})
            raw_payload = json.dumps(result, ensure_ascii=False)[:8000]
            convo.append({"role": "user",
                          "content": "TOOL RESULT for "
                                     f"{tool_key}:\n{wrap_external(raw_payload)}"
                                     "\nUse this to continue: call another tool, escalate, or give your final answer."})
            continue

        # plain text (or unparseable JSON) = final answer
        if shown < len(raw):
            on_chunk(raw[shown:])    # flush any buffered tail (a '{' that wasn't a tool/escalate → it's prose)
        return {"final": content, "escalation": None, "tool_trace": tool_trace}

    raise AssertionError("unreachable")  # forced branch always returns

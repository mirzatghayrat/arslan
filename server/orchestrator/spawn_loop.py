"""Bounded mini agent-loop for equipped spawns (spec §5.1).

Output protocol per step (model replies with ONE of):
  plain text                                      -> final answer
  {"tool": "<key>", "args": {...}}                -> tool call
  {"escalate": {"kind","need","context"}}         -> end turn, raise to Arslan
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

from server.orchestrator.json_protocol import parse_json_object
from server.registry.executors import EXECUTORS
from server.registry.service import wired_tools_for_spawn
from server.services.llm_factory import build_adapter

MAX_TOOL_CALLS = 5
TOOL_TIMEOUT_S = 20.0

_PROTOCOL = (
    "\n\nTOOL PROTOCOL: To use a tool, reply with ONLY this JSON and nothing else: "
    '{{"tool": "<name>", "args": {{...}}}}. Available tools:\n{tool_lines}\n'
    "To escalate a missing capability or missing data to Arslan, reply with ONLY: "
    '{{"escalate": {{"kind": "data" or "capability", "need": "<what outcome you need>", '
    '"context": "<why>"}}}} — describe the OUTCOME you need, never an operation to run.\n'
    "Otherwise reply with your final answer as normal text."
)


def _get_adapter():
    """Indirection so tests can stub adapter construction."""
    return build_adapter()


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
    spawn_id: int,
    system: str,
    user_content: str,
    history: list[dict],
    current_turn: int,
    emit: Callable[[dict], None],
    on_chunk: Callable[[str], None],
    allow_escalation: bool = True,
) -> dict:
    """Run the loop. Returns {"final": str|None, "escalation": dict|None,
    "tool_trace": list}. Exactly one of final/escalation is non-None."""
    adapter = _get_adapter()
    a = await adapter if hasattr(adapter, "__await__") else adapter

    wired = await wired_tools_for_spawn(spawn_id, current_turn=current_turn)
    tool_lines = "\n".join(f"- {t['key']}: {t['description']}" for t in wired) or "- (none live)"
    system = system + _PROTOCOL.format(tool_lines=tool_lines)

    convo = list(history) + [{"role": "user", "content": user_content}]
    tool_trace: list[dict] = []

    for step in range(MAX_TOOL_CALLS + 1):
        forced = step == MAX_TOOL_CALLS
        sys_now = system if not forced else (
            system + "\n\nTool budget exhausted: answer now with what you have. Text only."
        )
        resp = await a.chat(sys_now, convo[-1]["content"], history=convo[:-1])
        content = (resp.content or "").strip()
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
            # Layer-3 gate: equipped ∩ safe ∩ wired, re-resolved per call (grants may expire).
            wired_now = {t["key"] for t in
                         await wired_tools_for_spawn(spawn_id, current_turn=current_turn)}
            if tool_key not in wired_now or tool_key not in EXECUTORS:
                result = {"ok": False,
                          "error": f"tool '{tool_key}' is not available to you; "
                                   "you may escalate a need instead"}
            else:
                try:
                    result = await asyncio.wait_for(
                        EXECUTORS[tool_key].execute(args), timeout=TOOL_TIMEOUT_S
                    )
                except TimeoutError:
                    result = {"ok": False, "error": f"tool '{tool_key}' timed out"}
                except Exception as exc:  # noqa: BLE001
                    result = {"ok": False, "error": f"tool '{tool_key}' failed: {exc}"}
            emit({"type": "tool_result", "tool": tool_key,
                  "ok": bool(result.get("ok")), "summary": _summarize_result(result)})
            tool_trace.append({"tool": tool_key, "args": args, "result": result})
            convo.append({"role": "assistant", "content": content})
            convo.append({"role": "user",
                          "content": "TOOL RESULT for "
                                     f"{tool_key}:\n{json.dumps(result, ensure_ascii=False)[:8000]}"
                                     "\nUse this to continue: call another tool, escalate, or give your final answer."})
            continue

        # plain text (or unparseable JSON) = final answer
        # v1 tradeoff (per plan §Task 12): the loop uses non-streaming chat calls, so the final answer arrives as ONE chunk. Streaming the final step is a known UX follow-up.
        on_chunk(content)
        return {"final": content, "escalation": None, "tool_trace": tool_trace}

    raise AssertionError("unreachable")  # forced branch always returns

"""Neutral in-turn trajectory for the native tool loop (0.1.49 P1, design doc
docs/specs/2026-10-01-0149-p1-execution-layer.md section 3).

run_native keeps one representation and renders it per request:
- native OpenAI-compatible: the provider translates these dicts directly
  (assistant tool_calls + role "tool" + verbatim continuation fields);
- legacy (test doubles, Anthropic, ARSLAN_TOOL_PROTOCOL=legacy): `to_legacy`,
  byte-identical to the pre-0.1.49 text format, Gemini provider pairs included.

Messages:
  {"role": "user", "content": ...}
  {"role": "assistant", "content": str|None, "tool_calls": [call...],
   "_continuation": dict|None, "_finish": str|None}
      call = {"id", "name", "arguments": dict|None, "arguments_raw": str,
              "provider_id"?: str}
  {"role": "tool", "tool_call_id", "name", "content", "_synthetic"?: bool,
   "_legacy_call"?: str, "_legacy_raw"?: bool, "_legacy_suffix"?: str}

Keys starting with "_" are local bookkeeping and never reach a wire payload.
Pure functions only: no I/O, no provider imports.
"""
from __future__ import annotations

import json
from typing import Any

LEGACY_TRAILER = "\nUse this to continue: call another tool, escalate, or give your final answer."
LEGACY_COMPLETED = "Native tool invocation completed: "


class TrajectoryError(ValueError):
    """The trajectory violates the call/result pairing invariant."""


def assistant(content: str | None, tool_calls: list[dict] | None = None, *,
              continuation: dict | None = None, finish: str | None = None) -> dict:
    return {"role": "assistant", "content": content, "tool_calls": list(tool_calls or []),
            "_continuation": continuation, "_finish": finish}


def call_from_response(raw: dict, fallback_id: str) -> dict:
    """Normalise one provider tool call (LLMResponse.tool_calls entry)."""
    fn = raw.get("function") or {}
    args = fn.get("arguments")
    raw_text = raw.get("arguments_raw")
    if raw_text is None:
        raw_text = args if isinstance(args, str) else json.dumps(args or {}, ensure_ascii=False)
    call = {"id": str(raw.get("id") or "") or fallback_id, "name": str(fn.get("name") or ""),
            "arguments": args if isinstance(args, dict) else None, "arguments_raw": raw_text}
    if raw.get("provider_id"):
        call["provider_id"] = raw["provider_id"]
    return call


def unique_ids(calls: list[dict], seen: set[str], step: int) -> list[dict]:
    """Servers sometimes send empty or repeated ids ("call_0" every step). Ids
    only have to be consistent within one request; make them unique per turn."""
    out = []
    for index, call in enumerate(calls):
        cid = call["id"]
        if not cid or cid in seen:
            cid = f"call_{step}_{index}"
            while cid in seen:
                cid += "_"
        seen.add(cid)
        out.append({**call, "id": cid})
    return out


def tool_result(call_id: str, name: str, content: str, *, synthetic: bool = False,
                legacy_call: str | None = None) -> dict:
    msg = {"role": "tool", "tool_call_id": call_id, "name": name, "content": content}
    if synthetic:
        msg["_synthetic"] = True
    if legacy_call is not None:
        msg["_legacy_call"] = legacy_call
    return msg


def is_call_group_start(message: dict) -> bool:
    return message.get("role") == "assistant" and bool(message.get("tool_calls"))


def validate(messages: list[dict]) -> None:
    """Every assistant tool call is answered by exactly one tool message, in
    order, immediately after it; no tool message answers anything else.
    Synthetic (host-run) tool messages stand alone."""
    index = 0
    while index < len(messages):
        message = messages[index]
        role = message.get("role")
        if role == "tool" and not message.get("_synthetic"):
            raise TrajectoryError(f"orphan tool result at {index}: {message.get('tool_call_id')!r}")
        if is_call_group_start(message):
            ids = [call["id"] for call in message["tool_calls"]]
            if len(set(ids)) != len(ids):
                raise TrajectoryError(f"duplicate tool call ids at {index}: {ids}")
            answers = messages[index + 1:index + 1 + len(ids)]
            got = [m.get("tool_call_id") if m.get("role") == "tool" and not m.get("_synthetic") else None
                   for m in answers]
            if got != ids:
                raise TrajectoryError(f"tool calls at {index} answered by {got}, expected {ids}")
            index += 1 + len(ids)
            continue
        index += 1


def groups(messages: list[dict]) -> list[list[dict]]:
    """Eviction units: an assistant call message with all of its results, or a
    single message. Splitting a group would orphan results or calls."""
    out: list[list[dict]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if is_call_group_start(message):
            end = index + 1
            while end < len(messages) and messages[end].get("role") == "tool" \
                    and not messages[end].get("_synthetic"):
                end += 1
            out.append(messages[index:end])
            index = end
        else:
            out.append([message])
            index += 1
    return out


OMITTED_RESULT = ("[Result omitted before delivery: this tool-result batch exceeded the context window. "
                  "Nothing here was seen. Re-request it in smaller parts if it is still needed.]")


def shrink_group(group: list[dict], max_chars: int, size_of) -> list[dict]:
    """Fit an oversized call group without breaking pairing: replace the oldest
    results' content with an explicit omission notice (never drop a record —
    an unanswered call is a protocol error, and silence would read as "seen")."""
    if not is_call_group_start(group[0]) or size_of(group) <= max_chars:
        return group
    out = list(group)
    for index in range(1, len(out)):
        out[index] = {key: value for key, value in out[index].items()
                      if key not in ("_legacy_raw", "_legacy_suffix")}
        out[index]["content"] = OMITTED_RESULT
        if size_of(out) <= max_chars:
            break
    return out


def _legacy_result(message: dict) -> str:
    # _legacy_raw: the record's content already replaced the whole old user turn
    # (research_review receipts). _legacy_suffix: text the old format appended
    # after the trailer (research_review draft); native rendering drops it
    # because the draft already travels in the call's own arguments.
    if message.get("_legacy_raw"):
        return message["content"] + message.get("_legacy_suffix", "")
    return (f"TOOL RESULT for {message['name']}:\n{message['content']}{LEGACY_TRAILER}"
            + message.get("_legacy_suffix", ""))


def to_legacy(messages: list[dict]) -> list[dict]:
    """Render to the pre-0.1.49 text protocol, byte for byte.

    Each executed call becomes an assistant "Native tool invocation completed: X"
    turn plus a user "TOOL RESULT for X" turn; host-run (synthetic) calls keep
    their original JSON invocation text; a Gemini call message with its
    continuation becomes the provider_content + function_response pair. Model
    narration beside tool calls was never part of the prompt and is not now.
    (The old loop replaced the call JSON with "invocation completed" because
    repeating it as prose invited imitation and duplicated large write payloads;
    the native protocol carries arguments in tool_calls instead.)"""
    out: list[dict] = []
    for group in groups(messages):
        head = group[0]
        if not is_call_group_start(head):
            if head.get("role") == "tool":  # synthetic, host-run
                out.append({"role": "assistant", "content": head.get("_legacy_call") or json.dumps(
                    {"tool": head["name"], "args": {}})})
                out.append({"role": "user", "content": _legacy_result(head)})
            else:
                out.append({k: v for k, v in head.items() if not k.startswith("_")
                            and not (k == "tool_calls" and not v)})
            continue
        results = group[1:]
        continuation = head.get("_continuation") or {}
        if continuation.get("protocol") == "gemini":
            responses = []
            for call, result in zip(head["tool_calls"], results):
                response = {"type": "function_response", "name": call["name"],
                            "response": {"result": _legacy_result(result)}}
                if call.get("provider_id"):
                    response["id"] = call["provider_id"]
                responses.append(response)
            out.append({"role": "assistant", "content": [
                {"type": "provider_content", **continuation["provider_content"]}]})
            out.append({"role": "user", "content": responses})
            continue
        for result in results:
            out.append({"role": "assistant", "content": LEGACY_COMPLETED + result["name"]})
            out.append({"role": "user", "content": _legacy_result(result)})
    return out


def public(message: dict[str, Any]) -> dict[str, Any]:
    """Drop local bookkeeping keys."""
    return {k: v for k, v in message.items() if not k.startswith("_")}

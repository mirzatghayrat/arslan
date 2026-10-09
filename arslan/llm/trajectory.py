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
   "_legacy_call"?: str, "_legacy_raw"?: bool, "_legacy_suffix"?: str,
   "_images"?: [neutral image block...], "_image_label"?: str}

Images in a tool result (Hands v2 screenshots, spec 2026-10-08-0157 §4.3) are neutral image
blocks kept beside the text: the legacy rendering puts them in the result's own user turn
(Gemini: in the function-response turn); the native OpenAI-compatible provider adds one user
message after that step's tool messages, because a role "tool" message carries text only.
Only the newest IMAGES_KEPT stay images (`keep_latest_images`); older ones become a stub.

Keys starting with "_" are local bookkeeping and never reach a wire payload.
Pure functions only: no I/O, no provider imports.
"""
from __future__ import annotations

import json
from typing import Any

LEGACY_TRAILER = "\nUse this to continue: call another tool, escalate, or give your final answer."
IMAGES_KEPT = 2
# What an image counts for when the history is measured (context size is chars of the
# rendered text): about 1.5k tokens for a 1280-px screenshot, not its base64 length.
IMAGE_SIZE_CHARS = 6_000
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
                legacy_call: str | None = None, images: list[dict] | None = None,
                image_label: str = "") -> dict:
    msg = {"role": "tool", "tool_call_id": call_id, "name": name, "content": content}
    if synthetic:
        msg["_synthetic"] = True
    if legacy_call is not None:
        msg["_legacy_call"] = legacy_call
    if images:
        msg["_images"] = [{"type": "image", "mime_type": i["mime_type"], "data": i["data"]} for i in images]
        msg["_image_label"] = image_label or name
    return msg


def keep_latest_images(messages: list[dict], keep: int = IMAGES_KEPT) -> int:
    """Turn every image but the newest `keep` into a stub in its result's text (§4.5).
    In place; returns how many were dropped."""
    seen, dropped = 0, 0
    for message in reversed(messages):
        images = message.get("_images")
        if not images:
            continue
        if seen + len(images) <= keep:
            seen += len(images)
            continue
        label = message.get("_image_label") or message.get("name") or "screenshot"
        message.pop("_images")
        message["content"] = f"{message.get('content', '')}\n[screenshot of {label}: no longer shown]"
        dropped += len(images)
    return dropped


def image_count(messages: list[dict]) -> int:
    return sum(len(m.get("_images") or ()) for m in messages)


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
                      if key not in ("_legacy_raw", "_legacy_suffix", "_images", "_image_label")}
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


def _with_images(text: str, message: dict, images: bool):
    """A result's user-turn content: its text, plus its images when there are any."""
    if not message.get("_images"):
        return text
    if not images:
        return f"{text}\n[screenshot of {message.get('_image_label') or message['name']}]"
    return [{"type": "text", "text": text}, *message["_images"]]


def to_legacy(messages: list[dict], *, images: bool = True) -> list[dict]:
    """Render to the pre-0.1.49 text protocol, byte for byte.

    Each executed call becomes an assistant "Native tool invocation completed: X"
    turn plus a user "TOOL RESULT for X" turn; host-run (synthetic) calls keep
    their original JSON invocation text; a Gemini call message with its
    continuation becomes the provider_content + function_response pair. Model
    narration beside tool calls was never part of the prompt and is not now.
    (The old loop replaced the call JSON with "invocation completed" because
    repeating it as prose invited imitation and duplicated large write payloads;
    the native protocol carries arguments in tool_calls instead.)

    images=False renders each image as a one-line stub (for measuring, never for sending)."""
    out: list[dict] = []
    for group in groups(messages):
        head = group[0]
        if not is_call_group_start(head):
            if head.get("role") == "tool":  # synthetic, host-run
                out.append({"role": "assistant", "content": head.get("_legacy_call") or json.dumps(
                    {"tool": head["name"], "args": {}})})
                out.append({"role": "user", "content": _with_images(_legacy_result(head), head, images)})
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
            for result in results:
                if result.get("_images"):
                    shown = _with_images(f"Screenshot from {result['name']}", result, images)
                    responses.extend(shown if isinstance(shown, list) else [{"type": "text", "text": shown}])
            out.append({"role": "user", "content": responses})
            continue
        for result in results:
            out.append({"role": "assistant", "content": LEGACY_COMPLETED + result["name"]})
            out.append({"role": "user", "content": _with_images(_legacy_result(result), result, images)})
    return out


def public(message: dict[str, Any]) -> dict[str, Any]:
    """Drop local bookkeeping keys."""
    return {k: v for k, v in message.items() if not k.startswith("_")}

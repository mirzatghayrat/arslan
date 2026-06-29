"""Builders for WebSocket JSON messages (single source of truth for the wire format)."""
from __future__ import annotations

from typing import Any


def question(
    node_id: str,
    text: str,
    options: list[str] | None,
    multi_select: bool,
    hint: str,
) -> dict[str, Any]:
    return {
        "type": "question",
        "node_id": node_id,
        "text": text,
        "options": options,
        "multi_select": multi_select,
        "hint": hint,
    }


def progress(step: int, total: int, node_id: str) -> dict[str, Any]:
    return {"type": "progress", "step": step, "total": total, "node_id": node_id}


def build_complete(spawn_id: int, spawn_name: str) -> dict[str, Any]:
    return {"type": "build_complete", "spawn_id": spawn_id, "spawn_name": spawn_name}


def stream_start(message_id: int) -> dict[str, Any]:
    return {"type": "stream_start", "message_id": message_id}


def stream_chunk(content: str) -> dict[str, Any]:
    return {"type": "stream_chunk", "content": content}


def stream_end(message_id: int) -> dict[str, Any]:
    return {"type": "stream_end", "message_id": message_id}


def message(message_id: int, content: str, role: str = "assistant") -> dict[str, Any]:
    return {"type": "message", "message_id": message_id, "content": content, "role": role}


def error(code: str, msg: str, recoverable: bool = False) -> dict[str, Any]:
    return {"type": "error", "code": code, "message": msg, "recoverable": recoverable}


def ping(ts: int) -> dict[str, Any]:
    return {"type": "ping", "ts": ts}


def routing(spawn_id: int, spawn_name: str | None = None) -> dict[str, Any]:
    return {"type": "routing", "spawn_id": spawn_id, "spawn_name": spawn_name}


def stream_start_src(source: str, spawn_id: int | None = None) -> dict[str, Any]:
    return {"type": "stream_start", "source": source, "spawn_id": spawn_id}


def suggest_create(
    draft: dict[str, Any],
    task_brief: str | None = None,
    overlaps: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {"type": "suggest_create", "draft": draft, "task_brief": task_brief, "overlaps": overlaps}


def spawn_meta(
    *, arslan_message_id: int, spawn_id: int, assistant_message_id: int, task_brief: str
) -> dict[str, Any]:
    return {
        "type": "spawn_meta",
        "arslan_message_id": arslan_message_id,
        "spawn_id": spawn_id,
        "assistant_message_id": assistant_message_id,
        "task_brief": task_brief,
    }


def fact_saved(content: str, sensitive: bool) -> dict[str, Any]:
    return {"type": "fact_saved", "content": content, "sensitive": sensitive}


def spawn_created(
    spawn_id: int,
    spawn_name: str,
    equipment: dict[str, Any] | None = None,
    intro: str | None = None,
) -> dict[str, Any]:
    return {
        "type": "spawn_created",
        "spawn_id": spawn_id,
        "spawn_name": spawn_name,
        "equipment": equipment or {"toolsets": [], "skills": []},
        "intro": intro,
    }


def tool_call(tool: str, args_summary: str) -> dict[str, Any]:
    return {"type": "tool_call", "tool": tool, "args_summary": args_summary}


def tool_result(tool: str, ok: bool, summary: str, artifact: dict | None = None) -> dict[str, Any]:
    frame: dict[str, Any] = {"type": "tool_result", "tool": tool, "ok": ok, "summary": summary}
    if artifact is not None:
        frame["artifact"] = artifact
    return frame


def escalation(spawn_id: int, spawn_name: str | None, kind: str, need: str) -> dict[str, Any]:
    return {"type": "escalation", "spawn_id": spawn_id, "spawn_name": spawn_name,
            "kind": kind, "need": need}


def escalation_refused(spawn_id: int, why: str) -> dict[str, Any]:
    return {"type": "escalation_refused", "spawn_id": spawn_id, "why": why}


def escalation_resolved(spawn_id: int, how: str, detail: str = "") -> dict[str, Any]:
    return {"type": "escalation_resolved", "spawn_id": spawn_id, "how": how, "detail": detail}


def orchestrator_action(tool: str, reason: str) -> dict[str, Any]:
    return {"type": "orchestrator_action", "tool": tool, "reason": reason}


def proposal(spawn_id: int, spawn_name: str | None) -> dict[str, Any]:
    return {"type": "proposal", "spawn_id": spawn_id, "spawn_name": spawn_name}


def roster_update(members: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "roster_update", "members": members}


def attachment_stored(spawn_name: str | None, chunks: int) -> dict[str, Any]:
    return {"type": "attachment_stored", "spawn_name": spawn_name, "chunks": chunks}


def propose_invite(spawn_id: int, reason: str) -> dict[str, Any]:
    """Arslan proposes bringing an existing spawn into the conversation.

    The frontend renders a confirmation card; on confirm it sends the existing
    `roster_invite {spawn_id}` frame which joins exactly that one spawn. Emitting
    this frame does NOT join the roster — the join awaits the user's confirmation.
    """
    return {"type": "propose_invite", "spawn_id": spawn_id, "reason": reason}


def propose_staffing(candidates: list[dict], create_draft: dict) -> dict[str, Any]:
    """Arslan offers a staffing choice: pick one of the comparable existing spawns
    (each {spawn_id, name, score, why}) OR create a fresh one from `create_draft`.

    Like `propose_invite`, emitting this frame joins NOTHING and creates NOTHING —
    the frontend renders a picker card; the user's choice drives a `roster_invite`
    (pick) or a `confirm_create` (create) on the existing single, idempotent paths.
    """
    return {"type": "propose_staffing", "candidates": candidates, "create_draft": create_draft}


def roster_event(action: str, spawn_id: int, spawn_name: str | None) -> dict[str, Any]:
    """Notify the client that a spawn joined or left the roster.

    `action` is "joined" or "left".
    """
    return {"type": "roster_event", "action": action, "spawn_id": spawn_id, "spawn_name": spawn_name}

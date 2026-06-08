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


def suggest_create(draft: dict[str, Any]) -> dict[str, Any]:
    return {"type": "suggest_create", "draft": draft}


def fact_saved(content: str, sensitive: bool) -> dict[str, Any]:
    return {"type": "fact_saved", "content": content, "sensitive": sensitive}


def spawn_created(spawn_id: int, spawn_name: str) -> dict[str, Any]:
    return {"type": "spawn_created", "spawn_id": spawn_id, "spawn_name": spawn_name}

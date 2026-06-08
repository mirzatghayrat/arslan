"""WebSocket endpoint for the unified Arslan orchestrator conversation."""
from __future__ import annotations

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from server.auth import is_ws_token_valid
from server.db import session as db_session
from server.db.models import ArslanMessage
from server.orchestrator import arslan
from server.services import spawn_service
from server.ws import protocol


def _build_system_prompt(draft: dict) -> str:
    role = draft.get("persona_role") or "a helpful assistant"
    tone = draft.get("persona_tone") or ""
    domain = draft.get("domain") or ""
    parts = [f"You are {role}."]
    if tone:
        parts.append(f"Tone: {tone}.")
    if domain:
        parts.append(f"Domain focus: {domain}.")
    return " ".join(parts)


async def _history(conversation_id: str) -> list[dict]:
    async with db_session.AsyncSessionLocal() as db:
        rows = await db.execute(
            select(ArslanMessage)
            .where(ArslanMessage.conversation_id == conversation_id)
            .order_by(ArslanMessage.id)
        )
        msgs = rows.scalars().all()
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.display_content or m.content,  # DISPLAY copy
            "spawn_id": m.spawn_id,
        }
        for m in msgs
    ]


async def _create_from_draft(draft: dict):
    domain = draft.get("domain") or "other"
    category, _, subcategory = domain.partition(".")
    async with db_session.AsyncSessionLocal() as db:
        spawn = await spawn_service.create_spawn(
            db,
            name=draft.get("name") or "new-spawn",
            domain_category=category or "other",
            domain_subcategory=subcategory or None,
            capabilities=draft.get("capabilities") or [],
            persona_role=draft.get("persona_role"),
            persona_tone=draft.get("persona_tone"),
            system_prompt=_build_system_prompt(draft),
            generation_level=1,
        )
        return spawn.id, spawn.name


async def arslan_endpoint(ws: WebSocket, conversation_id: str) -> None:
    if not is_ws_token_valid(ws.query_params.get("token")):
        await ws.close(code=4001)
        return

    await ws.accept()
    await ws.send_json({"type": "history", "messages": await _history(conversation_id)})

    # Emit-sink buffers events from the (sync-callback) orchestration loop, flushed to the socket.
    outbox: list[dict] = []

    def emit(ev: dict) -> None:
        outbox.append(ev)

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")

            if msg_type in ("ping", "pong"):
                continue

            if msg_type == "resume":
                last_id = int(data.get("last_message_id", 0))
                for m in await _history(conversation_id):
                    if m["id"] > last_id:
                        await ws.send_json(protocol.message(m["id"], m["content"], m["role"]))
                continue

            if msg_type == "confirm_create":
                spawn_id, spawn_name = await _create_from_draft(data.get("draft") or {})
                await ws.send_json(protocol.spawn_created(spawn_id, spawn_name))
                continue

            if msg_type != "user_message":
                await ws.send_json(protocol.error("INVALID_INPUT", "Unknown message type"))
                continue

            outbox.clear()
            await arslan.handle_user_message(conversation_id, data.get("content", ""), emit)
            for ev in outbox:
                await ws.send_json(_to_frame(ev))
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001
        try:
            await ws.send_json(protocol.error("INTERNAL_ERROR", str(exc), recoverable=True))
            await ws.close(code=1011)
        except Exception:  # noqa: BLE001
            pass
        return


def _to_frame(ev: dict) -> dict:
    """Map an orchestration event dict to a wire frame (already frame-shaped here)."""
    t = ev.get("type")
    if t == "routing":
        return protocol.routing(ev.get("spawn_id"), ev.get("spawn_name"))
    if t == "stream_start":
        return protocol.stream_start_src(ev.get("source", "arslan"), ev.get("spawn_id"))
    if t == "suggest_create":
        return protocol.suggest_create(ev.get("draft") or {})
    if t == "fact_saved":
        return protocol.fact_saved(ev.get("content", ""), bool(ev.get("sensitive")))
    return ev  # stream_chunk / stream_end / error already match the wire shape

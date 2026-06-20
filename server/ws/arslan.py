"""WebSocket endpoint for the unified Arslan orchestrator conversation."""
from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from server.auth import is_ws_token_valid
from server.db import session as db_session
from server.db.models import ArslanMessage
from server.orchestrator import arslan
from server.services import spawn_service
from server.ws import protocol


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
            "message_id": m.id,
            "role": m.role,
            "content": m.display_content or m.content,  # DISPLAY copy
            "spawn_id": m.spawn_id,
        }
        for m in msgs
    ]


async def _create_from_draft(draft: dict, differentiation: str | None = None):
    """Thin alias kept for backward-compat test imports.

    The real implementation lives in spawn_service.create_from_draft so that
    the REST create path (api/create.py) shares the same code without cyclic
    imports between ws/ and api/.
    """
    return await spawn_service.create_from_draft(draft, differentiation)


async def _last_spawn_output(spawn_id: int) -> str | None:
    """Reconstruct prior_output for a refinement: the spawn's latest assistant message."""
    from server.db.models import ChatMessage

    async with db_session.AsyncSessionLocal() as db:
        row = await db.execute(
            select(ChatMessage.content)
            .where(ChatMessage.spawn_id == spawn_id, ChatMessage.role == "assistant")
            .order_by(ChatMessage.id.desc())
            .limit(1)
        )
        val = row.scalar_one_or_none()
    return val


async def arslan_endpoint(ws: WebSocket, conversation_id: str) -> None:
    if not is_ws_token_valid(ws.query_params.get("token")):
        await ws.close(code=4001)
        return

    await ws.accept()
    await ws.send_json({"type": "history", "messages": await _history(conversation_id)})

    # Emit-sink: a queue drained concurrently with the orchestration coroutine so
    # frames (tool_call/tool_result/stream_*) reach the client live, in order.
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    def emit(ev: dict) -> None:
        queue.put_nowait(ev)

    async def _drain() -> None:
        while True:
            ev = await queue.get()
            if ev is None:
                return
            try:
                await ws.send_json(_to_frame(ev))
            except Exception:  # noqa: BLE001 — client gone; receive loop will see the disconnect
                return

    async def run_with_live_frames(coro: Coroutine[Any, Any, object]) -> None:
        sender = asyncio.create_task(_drain())
        try:
            await coro
        finally:
            queue.put_nowait(None)  # sentinel: flush remainder, stop sender
            await sender

    async def run_spawn(spawn_id: int, task_brief: str, **kw) -> None:
        await run_with_live_frames(
            arslan.dispatch_spawn(conversation_id, spawn_id, task_brief, emit, **kw)
        )

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")

            if msg_type in ("ping", "pong"):
                continue

            if msg_type == "resume":
                last_id = int(data.get("last_message_id", 0))
                for m in await _history(conversation_id):
                    if m["message_id"] > last_id:
                        await ws.send_json(protocol.message(m["message_id"], m["content"], m["role"]))
                continue

            if msg_type == "confirm_create":
                draft = data.get("draft") or {}
                task_brief = data.get("task_brief") or ""
                differentiation = data.get("differentiation") or None
                # Create-time dedup: a stale/edited draft may collide with an
                # existing spawn even if the suggest_create card showed none.
                # differentiation intentionally bypasses dedup; create_spawn_unique handles the name.
                if not differentiation:
                    overlap = spawn_service.find_overlap(draft, await spawn_service.load_all_spawns())
                    if overlap is not None:
                        await ws.send_json(
                            protocol.suggest_create(draft, task_brief=task_brief, overlaps=overlap)
                        )
                        continue
                spawn_id, spawn_name, equipment, intro = await _create_from_draft(draft, differentiation)
                await ws.send_json(protocol.spawn_created(spawn_id, spawn_name,
                                                          equipment=equipment, intro=intro))
                if task_brief.strip():
                    await run_spawn(spawn_id, task_brief)
                continue

            if msg_type == "route_to":
                raw_id = data.get("spawn_id")
                try:
                    spawn_id = int(raw_id)
                except (TypeError, ValueError):
                    await ws.send_json(protocol.error("INVALID_INPUT", "spawn_id required"))
                    continue
                task_brief = data.get("task_brief") or ""
                await run_spawn(spawn_id, task_brief)
                continue

            if msg_type == "confirm_direction":
                raw_id = data.get("spawn_id")
                try:
                    spawn_id = int(raw_id)
                except (TypeError, ValueError):
                    await ws.send_json(protocol.error("INVALID_INPUT", "spawn_id required"))
                    continue
                await run_with_live_frames(arslan.confirm_and_execute(conversation_id, spawn_id, emit))
                continue

            if msg_type == "redo":
                raw_id = data.get("spawn_id")
                try:
                    spawn_id = int(raw_id)
                except (TypeError, ValueError):
                    await ws.send_json(protocol.error("INVALID_INPUT", "spawn_id required"))
                    continue
                task_brief = data.get("task_brief") or ""
                await run_spawn(spawn_id, task_brief)
                continue

            if msg_type == "refine":
                raw_id = data.get("spawn_id")
                try:
                    spawn_id = int(raw_id)
                except (TypeError, ValueError):
                    await ws.send_json(protocol.error("INVALID_INPUT", "spawn_id required"))
                    continue
                task_brief = data.get("task_brief") or ""
                instruction = data.get("instruction") or ""
                prior = await _last_spawn_output(spawn_id)
                await run_spawn(spawn_id, task_brief, prior_output=prior, instruction=instruction)
                continue

            if msg_type == "refine_draft":
                description = data.get("description") or ""
                previous = data.get("previous_draft") or {}
                from server.services import spawn_drafter

                draft = await spawn_drafter.draft_from_text(description, previous=previous)
                await ws.send_json(
                    protocol.suggest_create(
                        draft,
                        task_brief=draft.get("task_brief"),
                        overlaps=draft.get("overlaps"),
                    )
                )
                continue

            if msg_type != "user_message":
                await ws.send_json(protocol.error("INVALID_INPUT", "Unknown message type"))
                continue

            await run_with_live_frames(
                arslan.handle_user_message(conversation_id, data.get("content", ""), emit)
            )
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
        return protocol.suggest_create(
            ev.get("draft") or {}, task_brief=ev.get("task_brief"), overlaps=ev.get("overlaps")
        )
    if t == "fact_saved":
        return protocol.fact_saved(ev.get("content", ""), bool(ev.get("sensitive")))
    if t == "tool_call":
        return protocol.tool_call(ev.get("tool", ""), ev.get("args_summary", ""))
    if t == "tool_result":
        return protocol.tool_result(ev.get("tool", ""), bool(ev.get("ok")), ev.get("summary", ""))
    if t == "escalation":
        return protocol.escalation(
            ev.get("spawn_id"), ev.get("spawn_name"), ev.get("kind", "data"), ev.get("need", "")
        )
    if t == "escalation_refused":
        return protocol.escalation_refused(ev.get("spawn_id"), ev.get("why", ""))
    if t == "escalation_resolved":
        return protocol.escalation_resolved(
            ev.get("spawn_id"), ev.get("how", ""), ev.get("detail", "")
        )
    if t == "orchestrator_action":
        return protocol.orchestrator_action(ev.get("tool", ""), ev.get("reason", ""))
    return ev  # stream_chunk / stream_end / error / spawn_meta already match the wire shape

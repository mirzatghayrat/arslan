"""WebSocket endpoint streaming chat with a spawn; persists messages; supports resume."""
from __future__ import annotations

import logging

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from server import security
from server.auth import is_ws_token_valid
from server.db import session as db_session
from server.db.models import ChatMessage, Spawn
from server.services import ingest, storage_intent
from server.ws import protocol

logger = logging.getLogger(__name__)


async def _load_spawn(spawn_id: int) -> Spawn | None:
    async with db_session.AsyncSessionLocal() as db:
        return await db.get(Spawn, spawn_id)


async def _history(spawn_id: int) -> list[ChatMessage]:
    async with db_session.AsyncSessionLocal() as db:
        rows = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.spawn_id == spawn_id, ChatMessage.archived == False)  # noqa: E712
            .order_by(ChatMessage.id)
        )
        return list(rows.scalars().all())


async def _save_message(spawn_id: int, role: str, content: str) -> int:
    async with db_session.AsyncSessionLocal() as db:
        msg = ChatMessage(spawn_id=spawn_id, role=role, content=content)
        db.add(msg)
        await db.commit()
        await db.refresh(msg)
        return msg.id


async def chat_endpoint(ws: WebSocket, spawn_id: int) -> None:
    # Reject a cross-site WebSocket open BEFORE accept (fail-closed).
    if not security.ws_origin_allowed(ws.headers.get("origin"), ws.headers.get("host")):
        await ws.close(code=4403)
        return
    token = ws.query_params.get("token")
    if not is_ws_token_valid(token):
        await ws.close(code=4001)
        return

    spawn = await _load_spawn(spawn_id)
    if spawn is None:
        await ws.accept()
        await ws.close(code=4004)
        return

    await ws.accept()

    # Send existing history so a fresh client can render the conversation.
    existing = await _history(spawn_id)
    await ws.send_json(
        {
            "type": "history",
            "messages": [
                {"message_id": m.id, "role": m.role, "content": m.content}
                for m in existing
            ],
        }
    )

    recent_material = ""
    recent_names: list[str] = []

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")

            if msg_type in ("ping", "pong"):
                continue

            if msg_type == "resume":
                last_id = int(data.get("last_message_id", 0))
                for m in await _history(spawn_id):
                    if m.id > last_id:
                        await ws.send_json(protocol.message(m.id, m.content, m.role))
                continue

            if msg_type != "user_message":
                await ws.send_json(protocol.error("INVALID_INPUT", "Unknown message type"))
                continue

            user_content = data.get("content", "")
            attached = (data.get("attached_context") or "").strip()
            if attached:
                recent_material = attached                       # hold for a later "记住"
                recent_names = data.get("attached_names") or ["附件"]

            # storage intent — only when we have held material
            if recent_material:
                try:
                    intent = await storage_intent.classify(user_content, recent_names, [spawn.name])
                except Exception as exc:  # noqa: BLE001
                    logger.warning("storage intent classify failed (non-fatal): %s", exc)
                    intent = None
                if intent is not None and intent.store:
                    try:
                        n = await ingest.ingest_text(
                            spawn_id, recent_names[0] if recent_names else "附件", recent_material
                        )
                    except Exception as exc:  # noqa: BLE001  (best-effort ingest)
                        logger.warning("attachment ingest failed (non-fatal): %s", exc)
                        await ws.send_json(protocol.error("INGEST_ERROR", str(exc), recoverable=True))
                        continue   # keep recent_material so the user can retry
                    recent_material = ""
                    recent_names = []
                    await _save_message(spawn_id, "user", user_content)
                    confirm = f"📎 已记入 {spawn.name} 的知识库 · {n} 块"
                    await _save_message(spawn_id, "assistant", confirm)
                    await ws.send_json(protocol.attachment_stored(spawn.name, n))
                    continue   # storage replaces the LLM turn

            await _save_message(spawn_id, "user", user_content)

            # Build history for the LLM from prior messages.
            history = [
                {"role": m.role, "content": m.content}
                for m in await _history(spawn_id)
            ][:-1]  # exclude the just-saved user message; passed as `user`

            llm_user = user_content
            if attached:
                llm_user = f"[附带材料]\n{attached}\n\n[用户消息]\n{user_content}"

            import asyncio

            from server.orchestrator import spawn_loop
            from server.orchestrator.dispatcher import build_spawn_system

            # current_turn ≈ this spawn's user-message count (direct chat has no conversation turn).
            current_turn = sum(1 for m in await _history(spawn_id) if m.role == "user")
            system, _wired = await build_spawn_system(
                spawn, retrieval_query=user_content, current_turn=current_turn,
                attached_context=(attached or None),
            )

            await ws.send_json(protocol.stream_start(0))
            queue: asyncio.Queue = asyncio.Queue()

            def _emit(ev: dict) -> None:
                queue.put_nowait(ev)

            def _on_chunk(piece: str) -> None:
                queue.put_nowait({"type": "stream_chunk", "content": piece})

            async def _drain() -> None:
                while True:
                    ev = await queue.get()
                    if ev is None:
                        return
                    t = ev.get("type")
                    if t == "stream_chunk":
                        await ws.send_json(protocol.stream_chunk(ev["content"]))
                    elif t == "tool_call":
                        await ws.send_json(protocol.tool_call(ev["tool"], ev.get("args_summary", "")))
                    elif t == "tool_result":
                        await ws.send_json(protocol.tool_result(
                            ev["tool"], bool(ev.get("ok")), ev.get("summary", ""), ev.get("artifact")))

            sender = asyncio.create_task(_drain())
            try:
                out = await spawn_loop.run(
                    spawn_id=spawn_id, system=system, user_content=llm_user, history=history,
                    current_turn=current_turn, emit=_emit, on_chunk=_on_chunk, allow_escalation=False,
                )
            except Exception as exc:  # noqa: BLE001
                queue.put_nowait(None)
                await sender
                await ws.send_json(protocol.error("LLM_ERROR", str(exc), recoverable=True))
                continue
            queue.put_nowait(None)
            await sender

            assistant_text = out.get("final") or ""
            msg_id = await _save_message(spawn_id, "assistant", assistant_text)
            await ws.send_json(protocol.stream_end(msg_id))
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001
        # Any non-disconnect failure: surface an error frame + clean close,
        # never a silent socket death (mirrors the build WS endpoint).
        try:
            await ws.send_json(
                protocol.error("INTERNAL_ERROR", str(exc), recoverable=True)
            )
            await ws.close(code=1011)
        except Exception:  # noqa: BLE001
            pass
        return

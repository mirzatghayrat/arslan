"""WebSocket endpoint streaming chat with a spawn; persists messages; supports resume."""
from __future__ import annotations

import logging

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from arslan.llm.adapter import LLMAdapter
from server.auth import is_ws_token_valid
from server.db import session as db_session
from server.db.models import ChatMessage, Spawn
from server.services.llm_factory import build_adapter
from server.ws import protocol

logger = logging.getLogger(__name__)


async def _load_spawn(spawn_id: int) -> Spawn | None:
    async with db_session.AsyncSessionLocal() as db:
        return await db.get(Spawn, spawn_id)


async def _history(spawn_id: int) -> list[ChatMessage]:
    async with db_session.AsyncSessionLocal() as db:
        rows = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.spawn_id == spawn_id)
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


async def _build_adapter() -> LLMAdapter:
    # Single source of truth for settings → adapter (incl. Tier-0 preset expansion).
    return await build_adapter()


async def chat_endpoint(ws: WebSocket, spawn_id: int) -> None:
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
    system_prompt = spawn.system_prompt or "You are a helpful assistant."

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
                from server.services import ingest as _ingest
                from server.services import storage_intent as _si
                try:
                    intent = await _si.classify(user_content, recent_names, [spawn.name])
                except Exception as exc:  # noqa: BLE001
                    logger.warning("storage intent classify failed (non-fatal): %s", exc)
                    intent = None
                if intent is not None and intent.store:
                    n = await _ingest.ingest_text(
                        spawn_id, recent_names[0] if recent_names else "附件", recent_material
                    )
                    recent_material = ""
                    recent_names = []
                    await ws.send_json(protocol.attachment_stored(spawn.name, n))
                    continue   # storage replaces the LLM turn

            await _save_message(spawn_id, "user", user_content)

            # Build history for the LLM from prior messages.
            history = [
                {"role": m.role, "content": m.content}
                for m in await _history(spawn_id)
            ][:-1]  # exclude the just-saved user message; passed as `user`

            # KB retrieval injected into the system prompt (best-effort, like dispatcher).
            kb_system = system_prompt
            try:
                from server.services import knowledge as _kb
                chunks = await _kb.retrieve(spawn_id, user_content)
                kb_system = system_prompt + _kb.knowledge_block(chunks)
            except Exception as exc:  # noqa: BLE001
                logger.warning("chat KB retrieve failed (non-fatal): %s", exc)

            llm_user = user_content
            if attached:
                llm_user = f"[附带材料]\n{attached}\n\n[用户消息]\n{user_content}"

            adapter = await _build_adapter()
            assistant_text = ""
            # Reserve the assistant message id by streaming first, persisting on end.
            await ws.send_json(protocol.stream_start(0))
            try:
                async for piece in adapter.chat_stream(
                    kb_system, llm_user, history=history
                ):
                    assistant_text += piece
                    await ws.send_json(protocol.stream_chunk(piece))
            except Exception as exc:  # noqa: BLE001
                await ws.send_json(
                    protocol.error("LLM_ERROR", str(exc), recoverable=True)
                )
                continue

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

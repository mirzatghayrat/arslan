"""WebSocket endpoint streaming chat with a spawn; persists messages; supports resume."""
from __future__ import annotations

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from arslan.llm.adapter import LLMAdapter
from server.auth import is_ws_token_valid
from server.db import session as db_session
from server.db.models import ChatMessage, Spawn
from server.services import settings_service
from server.ws import protocol


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
    async with db_session.AsyncSessionLocal() as db:
        cfg = await settings_service.get_settings(db)
        api_key = await settings_service.get_decrypted_api_key(db)
    provider = cfg.get("llm_provider") or "openai"
    model = cfg.get("llm_model") or "gpt-4o"
    base_url = cfg.get("llm_base_url") or ""
    return LLMAdapter(provider, model, api_key=api_key, base_url=base_url)


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
                {"id": m.id, "role": m.role, "content": m.content} for m in existing
            ],
        }
    )

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
            await _save_message(spawn_id, "user", user_content)

            # Build history for the LLM from prior messages.
            history = [
                {"role": m.role, "content": m.content}
                for m in await _history(spawn_id)
            ][:-1]  # exclude the just-saved user message; passed as `user`

            adapter = await _build_adapter()
            assistant_text = ""
            # Reserve the assistant message id by streaming first, persisting on end.
            await ws.send_json(protocol.stream_start(0))
            try:
                async for piece in adapter.chat_stream(
                    system_prompt, user_content, history=history
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

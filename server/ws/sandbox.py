"""Sandbox WS: ephemeral in-memory per-spawn tuning session that merges back to the
main orchestration thread on confirm. Transcript is NEVER persisted — only the merged
deliverable (to the main thread) and the distilled memory_facts survive."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from fastapi import WebSocket, WebSocketDisconnect

from server.auth import is_ws_token_valid
from server.db import session as db_session
from server.db.models import Spawn
from server.orchestrator import arslan as arslan_mod
from server.orchestrator import spawn_loop
from server.orchestrator.dispatcher import build_spawn_system
from server.services import distill_service, sandbox_service
from server.ws import protocol

logger = logging.getLogger(__name__)


async def _load_spawn(spawn_id: int) -> Spawn | None:
    async with db_session.AsyncSessionLocal() as db:
        return await db.get(Spawn, spawn_id)


def _signals(transcript: list[dict]) -> str:
    users = "\n".join(m["content"] for m in transcript if m["role"] == "user" and m["content"])
    outs = "\n".join(m["content"] for m in transcript if m["role"] == "assistant" and m["content"])
    return f"用户消息:\n{users}\n\n分身产出:\n{outs}"


async def sandbox_endpoint(ws: WebSocket, spawn_id: int) -> None:
    if not is_ws_token_valid(ws.query_params.get("token")):
        await ws.close(code=4001)
        return
    spawn = await _load_spawn(spawn_id)
    if spawn is None:
        await ws.accept()
        await ws.close(code=4004)
        return
    await ws.accept()
    await ws.send_json({"type": "history", "messages": []})  # always a fresh session

    transcript: list[dict] = []            # in-memory only
    opened_at = datetime.utcnow()

    try:
        while True:
            data = await ws.receive_json()
            mtype = data.get("type")

            if mtype in ("ping", "pong"):
                continue

            if mtype == "discard":
                await ws.send_json({"type": "discarded"})
                return

            if mtype == "confirm_merge":
                conversation_id = data.get("conversation_id") or "main"
                final = next((m["content"] for m in reversed(transcript) if m["role"] == "assistant"), "")
                if not final.strip():
                    await ws.send_json(protocol.error("INVALID_INPUT", "nothing to merge", recoverable=True))
                    continue
                summary = await sandbox_service.summarize_deliverable(spawn.name, final)
                elapsed = max(0.0, (datetime.utcnow() - opened_at).total_seconds())
                # Persist to the MAIN thread + record the speed-weighted accept verdict.
                # The ack frames it emits are useless on THIS (sandbox) socket, so swallow
                # them; the client reconstructs the main-thread card from the `merged`
                # payload below (the main arslan store isn't connected to this socket).
                new_id = await arslan_mod.confirm_sandbox_merge(
                    conversation_id, spawn_id, final, summary, elapsed, lambda e: None
                )
                if new_id is None:
                    # Spawn vanished mid-session (narrow race): don't emit a `merged`
                    # frame with a null id — the client would push a broken card.
                    await ws.send_json(protocol.error("INVALID_INPUT", "merge failed", recoverable=True))
                    continue
                try:
                    await distill_service.distill_from_signals(spawn_id, _signals(transcript))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("sandbox distill failed (non-fatal): %s", exc)
                display = f"**✓ {summary}**\n\n{final}" if summary else final
                await ws.send_json({
                    "type": "merged", "spawn_id": spawn_id, "message_id": new_id,
                    "content": display, "summary": summary, "spawn_name": spawn.name,
                })
                return

            if mtype != "user_message":
                await ws.send_json(protocol.error("INVALID_INPUT", "Unknown message type"))
                continue

            user_content = data.get("content", "")
            attached = (data.get("attached_context") or "").strip()
            transcript.append({"role": "user", "content": user_content})

            history = transcript[:-1]
            llm_user = user_content
            if attached:
                llm_user = f"[附带材料]\n{attached}\n\n[用户消息]\n{user_content}"
            current_turn = sum(1 for m in transcript if m["role"] == "user")
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
                transcript.pop()  # drop the user turn that never got a reply
                await ws.send_json(protocol.error("LLM_ERROR", str(exc), recoverable=True))
                continue
            queue.put_nowait(None)
            await sender

            assistant_text = out.get("final") or ""
            transcript.append({"role": "assistant", "content": assistant_text})
            await ws.send_json(protocol.stream_end(0))
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001
        try:
            await ws.send_json(protocol.error("INTERNAL_ERROR", str(exc), recoverable=True))
            await ws.close(code=1011)
        except Exception:  # noqa: BLE001
            pass
        return

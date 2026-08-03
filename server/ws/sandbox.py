"""Sandbox WS: ephemeral in-memory per-spawn tuning session that merges back to the
main orchestration thread on confirm. Transcript is NEVER persisted — only the merged
deliverable (to the main thread) and the distilled memory_facts survive."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from fastapi import WebSocket, WebSocketDisconnect

from server import security
from server.auth import is_ws_token_valid
from sqlalchemy import select

from server.db import session as db_session
from server.db.models import ArslanMessage, Spawn
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


#: How much of the main thread's last turn the sandbox may carry.
#:
#: 🔴 A character budget, not a message count, and that was a correction. In the
#: user's own database a message ranges from 52 characters (median) to 21,960
#: (max) — a factor of 420 — so "the last N turns" names a bound that varies by
#: three orders of magnitude. The TURN decides where to cut; this decides how
#: much. Without it a single screenshot-sized report would be re-sent on every
#: sandbox turn, since it lands in the per-turn system prompt.
MAIN_CONTEXT_BUDGET = 6000

#: Roles as they appear in `arslan_messages`. `spawn_summary` is included on
#: purpose: if another spawn produced something inside the turn being discussed,
#: that IS the context — leaving it out would show the question and hide half
#: the answer.
_SPEAKER = {"user": "用户", "arslan": "Arslan", "spawn_summary": "分身产出"}


async def main_thread_context(conversation_id: str) -> str:
    """The main thread's LAST TURN, framed as read-only background.

    A turn is one `user` message plus everything after it — user's ruling, and
    the right unit here: a spawn's deliverable already has its own refine path,
    so the sandbox only needs enough to answer conceptually about what is being
    discussed with Arslan right now.

    Returns "" when there is nothing to show. An empty frame would announce
    context and then present none, which is worse than silence.
    """
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ArslanMessage)
            .where(ArslanMessage.conversation_id == conversation_id)
            .order_by(ArslanMessage.id)
        )).scalars().all()
    if not rows:
        return ""

    # Walk back to the last `user` message; everything from there is one turn.
    start = next((i for i in range(len(rows) - 1, -1, -1) if rows[i].role == "user"), None)
    if start is None:
        return ""
    turn = rows[start:]

    lines: list[str] = []
    used = 0
    truncated = False
    for m in turn:
        body = (m.display_content or m.content or "").strip()
        if not body:
            continue
        speaker = _SPEAKER.get(m.role, m.role)
        room = MAIN_CONTEXT_BUDGET - used
        if room <= 0:
            truncated = True
            break
        if len(body) > room:
            body = body[:room] + " …"
            truncated = True
        used += len(body)
        lines.append(f"{speaker}: {body}")

    if not lines:
        return ""

    head = "[主对话背景 · 只读 · 不是你的任务 / main thread, read-only, NOT your task]"
    tail = "[背景结束 · 你要做的事在下面 / end of background]"
    note = "（部分内容已省略）" if truncated else None
    body_lines = ([note] if note else []) + lines
    return "\n".join([head, *body_lines, tail])


async def sandbox_endpoint(ws: WebSocket, spawn_id: int) -> None:
    # Reject a cross-site WebSocket open BEFORE accept (fail-closed).
    if not security.ws_origin_allowed(ws.headers.get("origin"), ws.headers.get("host")):
        await ws.close(code=4403)
        return
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
    # Fetched ONCE per session, not per turn: it is background, it does not
    # change while the sandbox is open, and re-reading it every turn would put a
    # varying block in the system prompt — which is what busts a prompt-cache
    # prefix (see the prefix-cache rule, research backlog R-025).
    main_ctx: str | None = None
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
            # The main thread's last turn, as read-only background. In the SYSTEM
            # prompt rather than the history: it is not a turn anyone took in
            # this sandbox, and putting it here keeps it stable across the
            # session instead of drifting through the message list.
            if main_ctx is None:
                cid = (data.get("conversation_id") or "").strip()
                main_ctx = await main_thread_context(cid) if cid else ""
            if main_ctx:
                system = f"{system}\n\n{main_ctx}"

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

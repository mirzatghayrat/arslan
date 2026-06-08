"""Layer 2: dispatch a clean task_brief to a spawn; persist display + memory separately."""
from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import ChatMessage, Spawn
from server.orchestrator import memory
from server.services.llm_factory import build_adapter

_SPAWN_HISTORY_LIMIT = 10  # recent spawn turns included for continuity


def _get_adapter():
    """Indirection so tests can stub adapter construction."""
    return build_adapter()


async def _load_spawn(spawn_id: int) -> Spawn | None:
    async with db_session.AsyncSessionLocal() as db:
        return await db.get(Spawn, spawn_id)


async def get_spawn_name(spawn_id: int) -> str | None:
    """Resolve a spawn's name (used to caption the routing frame before streaming)."""
    spawn = await _load_spawn(spawn_id)
    return spawn.name if spawn else None


async def _spawn_history(spawn_id: int) -> list[dict]:
    async with db_session.AsyncSessionLocal() as db:
        rows = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.spawn_id == spawn_id)
            .order_by(ChatMessage.id.desc())
            .limit(_SPAWN_HISTORY_LIMIT)
        )
        msgs = list(reversed(rows.scalars().all()))
    return [{"role": m.role, "content": m.content} for m in msgs]


async def dispatch(
    conversation_id: str,
    *,
    spawn_id: int,
    task_brief: str,
    on_chunk: Callable[[str], None] | None = None,
) -> dict:
    """Run the spawn on a clean task. Streams via on_chunk; returns
    {full_output, spawn_name, summary_message_id}. Raises on a missing spawn."""
    spawn = await _load_spawn(spawn_id)
    if spawn is None:
        raise ValueError(f"spawn {spawn_id} not found")

    facts = await memory.facts_text()
    system = (spawn.system_prompt or "You are a helpful assistant.")
    if facts:
        system = f"{system}\n\n{facts}"
    history = await _spawn_history(spawn_id)

    adapter = _get_adapter()
    a = await adapter if hasattr(adapter, "__await__") else adapter

    full = ""
    async for piece in a.chat_stream(system, task_brief, history=history):
        full += piece
        if on_chunk is not None:
            on_chunk(piece)

    # Scope 2: spawn's own memory — task_brief (user) + output (assistant)
    async with db_session.AsyncSessionLocal() as db:
        db.add(ChatMessage(spawn_id=spawn_id, role="user", content=task_brief))
        db.add(ChatMessage(spawn_id=spawn_id, role="assistant", content=full))
        await db.commit()

    # Scope 1: Arslan memory — DISPLAY (full) vs MEMORY (1-line, deterministic — no extra LLM call)
    summary = f"[{spawn.name}] {task_brief} -> delivered"
    summary_id = await memory.add_message(
        conversation_id,
        "spawn_summary",
        summary,
        display_content=full,
        spawn_id=spawn_id,
    )
    return {"full_output": full, "spawn_name": spawn.name, "summary_message_id": summary_id}

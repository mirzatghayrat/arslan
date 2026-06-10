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
    prior_output: str | None = None,
    instruction: str | None = None,
) -> dict:
    """Run the spawn on a clean task. Streams via on_chunk; returns
    {full_output, spawn_name, summary_message_id, assistant_message_id}.
    When prior_output+instruction are given, runs a refinement of a previous result."""
    spawn = await _load_spawn(spawn_id)
    if spawn is None:
        raise ValueError(f"spawn {spawn_id} not found")

    facts = await memory.facts_text()
    system = (spawn.system_prompt or "You are a helpful assistant.")
    system += (
        "\n\nUse only real or user-provided information. Do not invent, simulate, or fabricate "
        "data, statistics, or sources. If you lack the data needed, say so and ask the user to "
        "provide it, or clearly label any example as hypothetical."
    )
    if facts:
        system = f"{system}\n\n{facts}"
    history = await _spawn_history(spawn_id)

    if instruction:
        user_content = (
            f"{task_brief}\n\nYour previous result:\n{prior_output or ''}\n\n"
            f"Apply this refinement and return the full revised result:\n{instruction}"
        )
    else:
        user_content = task_brief

    adapter = _get_adapter()
    a = await adapter if hasattr(adapter, "__await__") else adapter

    full = ""
    async for piece in a.chat_stream(system, user_content, history=history):
        full += piece
        if on_chunk is not None:
            on_chunk(piece)

    # Scope 2: spawn's own memory — capture the assistant row id for feedback wiring.
    async with db_session.AsyncSessionLocal() as db:
        db.add(ChatMessage(spawn_id=spawn_id, role="user", content=user_content))
        assistant_row = ChatMessage(spawn_id=spawn_id, role="assistant", content=full)
        db.add(assistant_row)
        await db.commit()
        await db.refresh(assistant_row)
        assistant_message_id = assistant_row.id

    # Scope 1: Arslan memory — DISPLAY (full) vs MEMORY (1-line, deterministic — no extra LLM call)
    summary = f"[{spawn.name}] {task_brief} -> delivered"
    summary_id = await memory.add_message(
        conversation_id,
        "spawn_summary",
        summary,
        display_content=full,
        spawn_id=spawn_id,
    )
    return {
        "full_output": full,
        "spawn_name": spawn.name,
        "summary_message_id": summary_id,
        "assistant_message_id": assistant_message_id,
    }

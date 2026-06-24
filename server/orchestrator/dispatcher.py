"""Layer 2: dispatch a clean task_brief to a spawn; persist display + memory separately."""
from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy import select

logger = logging.getLogger(__name__)

from server.db import session as db_session
from server.db.models import ChatMessage, Spawn
from server.orchestrator import memory, spawn_loop
from server.registry import service as registry_service
from server.services.llm_factory import build_adapter

_SPAWN_HISTORY_LIMIT = 10  # recent spawn turns included for continuity

_PROPOSE_PREFIX = (
    "PROPOSE MODE: Do NOT produce the final deliverable yet. First propose a concrete "
    "direction for this task and ask 1-3 short clarifying questions, then ask the user to "
    "confirm before you execute. Keep it brief.\n\nTask:\n"
)

_EXECUTE_CONFIRMED_PREFIX = (
    "EXECUTE MODE: The user has CONFIRMED the direction you proposed. Deliver the complete, "
    "final result now. Do NOT ask further questions and do NOT re-propose — produce the "
    "deliverable.\n\nTask:\n"
)


def _frame_brief(task_brief: str, *, mode: str = "execute", proposed_direction: str | None = None) -> str:
    if mode == "propose":
        return f"{_PROPOSE_PREFIX}{task_brief}"
    if mode == "execute_confirmed":
        carried = f"\n\nThe direction you proposed (now confirmed):\n{proposed_direction}" if proposed_direction else ""
        return f"{_EXECUTE_CONFIRMED_PREFIX}{task_brief}{carried}"
    return task_brief


def _get_adapter():
    """Indirection so tests can stub adapter construction."""
    return build_adapter(role="execute")


async def _load_spawn(spawn_id: int) -> Spawn | None:
    async with db_session.AsyncSessionLocal() as db:
        return await db.get(Spawn, spawn_id)


async def get_spawn_name(spawn_id: int) -> str | None:
    """Resolve a spawn's name (used to caption the routing frame before streaming)."""
    spawn = await _load_spawn(spawn_id)
    return spawn.name if spawn else None


async def last_spawn_output(spawn_id: int) -> str | None:
    """The spawn's most recent assistant output (e.g. the direction it proposed)."""
    async with db_session.AsyncSessionLocal() as db:
        row = await db.execute(
            select(ChatMessage.content)
            .where(ChatMessage.spawn_id == spawn_id, ChatMessage.role == "assistant")
            .order_by(ChatMessage.id.desc())
            .limit(1)
        )
        return row.scalar_one_or_none()


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


def _equipment_block_from(equipment: dict, wired: list[dict]) -> str:
    """Build the equipment section given precomputed equipment + wired tool dicts.

    Design note: called from dispatch() which already holds both values (computed
    once) so we avoid a duplicate wired_tools_for_spawn query. Unequipped spawns
    never reach here — dispatch() skips the call when equipment is empty.
    """
    lines: list[str] = []
    wired_keys = {t["key"] for t in wired}
    for t in wired:
        lines.append(f"- TOOL {t['key']} (live): {t['description']}")
    for ts in equipment["toolsets"]:
        if ts["status"] != "wired" or ts["key"] not in wired_keys:
            lines.append(f"- {ts['name']} (not yet live)")
    for sk in equipment["skills"]:
        lines.append(f"- TECHNIQUE {sk['name']}: {sk['description']}")
    lines.append(
        "You have NO other tools. If you lack a capability or data, escalate a need "
        "(see protocol); never ask the user to run things and never pretend to have "
        "other tools."
    )
    return "\n\nYour equipment:\n" + "\n".join(lines)


async def dispatch(
    conversation_id: str,
    *,
    spawn_id: int,
    task_brief: str,
    on_chunk: Callable[[str], None] | None = None,
    on_event: Callable[[dict], None] | None = None,
    prior_output: str | None = None,
    instruction: str | None = None,
    allow_escalation: bool = True,
    mode: str = "execute",
    system_prompt_override: str | None = None,
    persist: bool = True,
    attached_context: str | None = None,
) -> dict:
    """Run the spawn on a clean task. Streams via on_chunk; returns
    {full_output, spawn_name, summary_message_id, assistant_message_id, escalation}.

    When prior_output+instruction are given, runs a refinement of a previous result.
    on_event receives tool_call/tool_result dicts from the loop (equipped spawns only).
    escalation is None for normal completions; a dict for escalating spawns.

    Design: current_turn and wired are computed once here and shared between the
    equipment block builder and the spawn_loop call, avoiding duplicate DB queries.
    Equipment is fetched first (cheap); wired is skipped entirely for unequipped
    spawns (zero-tool path uses legacy chat_stream, byte-identical to pre-loop).
    """
    spawn = await _load_spawn(spawn_id)
    if spawn is None:
        raise ValueError(f"spawn {spawn_id} not found")

    facts = await memory.facts_text()
    base_prompt = system_prompt_override if system_prompt_override is not None else (spawn.system_prompt or "You are a helpful assistant.")
    system = base_prompt
    system += (
        "\n\nUse only real or user-provided information. Do not invent, simulate, or fabricate "
        "data, statistics, or sources. If you lack the data needed, say so and ask the user to "
        "provide it, or clearly label any example as hypothetical."
    )
    if facts:
        system = f"{system}\n\n{facts}"

    # Tier-1 evolution reaches the running spawn here: learned rules as a suffix.
    from server.services import evolution_service

    suffix = evolution_service.prompt_suffix(spawn.name)
    if suffix:
        system = f"{system}\n\n{suffix}"

    # Knowledge-base grounding: inject task-relevant chunks (best-effort; never break dispatch).
    from server.services import knowledge as _knowledge
    try:
        _kb = await _knowledge.retrieve(spawn_id, task_brief)
        system += _knowledge.knowledge_block(_kb)
    except Exception as exc:  # noqa: BLE001
        logger.warning("knowledge retrieve failed (non-fatal): %s", exc)

    if attached_context:
        system += f"\n\n[用户附带的临时材料]\n{attached_context}"

    # Compute equipment once. For unequipped spawns (legacy path) skip wired query entirely.
    equipment = await registry_service.equipment_for_spawn(spawn_id)
    has_equipment = bool(equipment["toolsets"] or equipment["skills"])

    current_turn = await memory.user_turn_count(conversation_id)
    wired: list[dict] = []
    if has_equipment:
        wired = await registry_service.wired_tools_for_spawn(
            spawn_id, current_turn=current_turn
        )
        system += _equipment_block_from(equipment, wired)

    history = await _spawn_history(spawn_id)

    if instruction:
        user_content = (
            f"{task_brief}\n\nYour previous result:\n{prior_output or ''}\n\n"
            f"Apply this refinement and return the full revised result:\n{instruction}"
        )
    else:
        # In execute_confirmed mode, prior_output carries the spawn's proposed direction.
        user_content = _frame_brief(task_brief, mode=mode, proposed_direction=prior_output)

    full = ""
    escalation = None

    if wired:
        # Equipped path: bounded tool loop (JSON protocol, gate-per-call).
        out_loop = await spawn_loop.run(
            spawn_id=spawn_id,
            system=system,
            user_content=user_content,
            history=history,
            current_turn=current_turn,
            emit=(on_event or (lambda e: None)),
            on_chunk=(on_chunk or (lambda c: None)),
            allow_escalation=allow_escalation,
        )
        full = out_loop["final"] or ""
        escalation = out_loop["escalation"]
    else:
        # Legacy path: plain chat_stream (byte-identical to pre-loop behavior for
        # zero-wired-tool spawns, including spawns with only unwired/non-wired equipment).
        adapter = _get_adapter()
        a = await adapter if hasattr(adapter, "__await__") else adapter
        async for piece in a.chat_stream(system, user_content, history=history):
            full += piece
            if on_chunk is not None:
                on_chunk(piece)

    assistant_message_id = None
    summary_id = None
    if persist:
        # Scope 2: spawn's own memory — capture the assistant row id for feedback wiring.
        spawn_content = f"[escalation] {escalation['need']}" if escalation else full
        async with db_session.AsyncSessionLocal() as db:
            db.add(ChatMessage(spawn_id=spawn_id, role="user", content=user_content))
            assistant_row = ChatMessage(spawn_id=spawn_id, role="assistant", content=spawn_content)
            db.add(assistant_row)
            await db.commit()
            await db.refresh(assistant_row)
            assistant_message_id = assistant_row.id

        # Scope 1: Arslan memory — DISPLAY (full) vs MEMORY (1-line, deterministic — no extra LLM call)
        if escalation:
            summary = f"[{spawn.name}] escalated: {escalation['need']}"
        else:
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
        "escalation": escalation,
    }

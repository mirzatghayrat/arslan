"""WebSocket endpoint driving the spawn-build dialogue with resume support."""
from __future__ import annotations

# DEPRECATED (2026-06-10): The step-by-step build wizard is superseded by natural-language
# spawn creation (server/services/spawn_drafter.py + POST /api/v1/spawns). This module and
# arslan/core/dialogue.py are retained for now (deprecate-not-delete) and slated for removal
# in a dedicated dead-code audit. No new callers should use it.

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from arslan.core.dialogue import NODE_ORDER, DialogueEngine
from arslan.models import SpawnBlueprint
from server.auth import is_ws_token_valid
from server.db import session as db_session
from server.db.models import BuildSession, Spawn
from server.services import build_session_service as bss
from server.services import spawn_service
from server.ws import protocol


def _build_system_prompt(req) -> str:  # noqa: ANN001
    parts: list[str] = []
    if req.persona and req.persona.role:
        parts.append(f"You are {req.persona.role}.")
    if req.persona and req.persona.tone:
        parts.append(f"Tone: {req.persona.tone}.")
    if req.domain:
        parts.append(f"Domain focus: {req.domain.full_domain}.")
    if req.capabilities:
        parts.append(f"Core capabilities: {', '.join(req.capabilities)}.")
    return " ".join(parts) if parts else "You are a helpful AI assistant."


async def _load_or_create_engine(session_id: str) -> DialogueEngine:
    engine = DialogueEngine()
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(BuildSession, session_id)
        if row is not None:
            bss.restore_state(engine, row.state_json)
    return engine


async def _persist_state(session_id: str, engine: DialogueEngine) -> None:
    async with db_session.AsyncSessionLocal() as db:
        row = await db.get(BuildSession, session_id)
        snapshot = bss.serialize_state(engine.state)
        if row is None:
            db.add(BuildSession(session_id=session_id, state_json=snapshot))
        else:
            row.state_json = snapshot
        await db.commit()


async def _send_current_question(ws: WebSocket, engine: DialogueEngine) -> bool:
    """Send the next question. Returns False if the dialogue is finished."""
    question = engine.get_next_question()
    if question is None:
        return False
    await ws.send_json(
        protocol.question(
            question.node_id,
            question.text,
            question.options,
            question.multi_select,
            question.hint,
        )
    )
    return True


async def _finalize(session_id: str, engine: DialogueEngine) -> tuple[int, str]:
    """Persist the finished spawn to the DB and clean up the build session."""
    req = engine.state.requirements
    blueprint = SpawnBlueprint(
        requirements=req,
        tools=[],
        system_prompt=_build_system_prompt(req),
        workflow_steps=[],
        template_used=None,
        generation_level=1,
    )
    async with db_session.AsyncSessionLocal() as db:
        base_name = req.spawn_name or "unnamed-spawn"
        name = base_name
        suffix = 2
        while (
            await db.execute(select(Spawn.id).where(Spawn.name == name))
        ).first() is not None:
            name = f"{base_name}-{suffix}"
            suffix += 1
        spawn = await spawn_service.create_spawn(
            db,
            name=name,
            domain_category=req.domain.category if req.domain else "other",
            domain_subcategory=req.domain.subcategory if req.domain else None,
            capabilities=req.capabilities,
            persona_role=req.persona.role if req.persona else None,
            persona_tone=req.persona.tone if req.persona else None,
            system_prompt=blueprint.system_prompt,
            generation_level=1,
        )
        spawn_id, spawn_name = spawn.id, spawn.name
        row = await db.get(BuildSession, session_id)
        if row is not None:
            await db.delete(row)
            await db.commit()
    return spawn_id, spawn_name


async def build_endpoint(ws: WebSocket, session_id: str) -> None:
    token = ws.query_params.get("token")
    if not is_ws_token_valid(token):
        await ws.close(code=4001)
        return

    await ws.accept()
    engine = await _load_or_create_engine(session_id)

    # Send the initial/current question.
    if not await _send_current_question(ws, engine):
        spawn_id, name = await _finalize(session_id, engine)
        await ws.send_json(protocol.build_complete(spawn_id, name))
        await ws.close(code=1000)
        return

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")

            if msg_type == "ping":
                continue
            if msg_type == "pong":
                continue
            if msg_type == "cancel":
                await ws.close(code=1000)
                return
            if msg_type == "resume":
                await _send_current_question(ws, engine)
                continue
            if msg_type not in ("user_message", "select_option"):
                await ws.send_json(protocol.error("INVALID_INPUT", "Unknown message type"))
                continue

            # Convert the answer to the text the DialogueEngine expects.
            if msg_type == "select_option":
                values = data.get("values", [])
                user_text = " ".join(str(v) for v in values)
            else:
                user_text = data.get("content", "")

            engine.process_user_input(user_text)
            await _persist_state(session_id, engine)

            step = len(engine.state._filled)
            await ws.send_json(
                protocol.progress(step, len(NODE_ORDER), engine.state.current_node)
            )

            if engine.state.is_finished:
                spawn_id, name = await _finalize(session_id, engine)
                await ws.send_json(protocol.build_complete(spawn_id, name))
                await ws.close(code=1000)
                return

            await _send_current_question(ws, engine)
    except WebSocketDisconnect:
        # State is already persisted after each answer; nothing to do.
        return
    except Exception as exc:  # noqa: BLE001
        # Any non-disconnect failure: surface an error frame + clean close,
        # never a silent socket death. State is persisted per-answer, so the
        # client can reconnect and resume.
        try:
            await ws.send_json(
                protocol.error("INTERNAL_ERROR", str(exc), recoverable=True)
            )
            await ws.close(code=1011)
        except Exception:  # noqa: BLE001
            pass
        return

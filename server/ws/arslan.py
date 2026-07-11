"""WebSocket endpoint for the unified Arslan orchestrator conversation."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from server import security
from server.auth import is_ws_token_valid
from server.db import session as db_session
from server.db.models import ArslanMessage
from server.orchestrator import arslan, dispatcher, memory
from server.services import (
    distill_service,
    ingest,
    phase_service,
    roster_service,
    settings_service,
    spawn_service,
    storage_intent,
)
from server.ws import protocol

logger = logging.getLogger(__name__)


def _cmd_sig(command: str, argv: list) -> str:
    # signature = binary + subcommand (kept literal) + arg SHAPE of the rest
    # (flags kept, free values blanked). Keeping the FIRST non-flag token — the
    # git/gh subcommand, the risk-bearing token — is what stops "remember git
    # status" from auto-approving "git push".
    sig_parts: list[str] = []
    seen_subcommand = False
    for a in argv:
        if a.startswith("-"):
            sig_parts.append(a)            # flags kept verbatim
        elif not seen_subcommand:
            sig_parts.append(a)            # first non-flag token = subcommand, kept
            seen_subcommand = True
        else:
            sig_parts.append("·")          # later free values blanked
    return command + "\x1f" + "\x1f".join(sig_parts)


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
            # S3-M2: run linkage (set at finalize) so RunReplay entry points
            # survive a reload. Key always emitted; None when unlinked.
            "run_id": m.run_id,
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
    # Reject a cross-site WebSocket open BEFORE accept (fail-closed): a browser page
    # on another origin must not drive spawn dispatch / roster edits over this socket.
    if not security.ws_origin_allowed(ws.headers.get("origin"), ws.headers.get("host")):
        await ws.close(code=4403)
        return
    if not is_ws_token_valid(ws.query_params.get("token")):
        await ws.close(code=4001)
        return

    await ws.accept()
    await ws.send_json({"type": "history", "messages": await _history(conversation_id)})
    await ws.send_json(protocol.roster_update(await roster_service.list_roster(conversation_id)))

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

    async def run_with_confirm_frames(coro: Coroutine[Any, Any, object]) -> None:
        """Run a plain-message orchestration. run_command pauses mid-loop via the
        injected `confirm_command`, which OWNS ws.receive itself (see below) only
        while a command is pending — so there is never a blocked receiver to cancel,
        and the outer loop cleanly resumes receiving once orchestration finishes."""
        sender = asyncio.create_task(_drain())
        try:
            await coro
        finally:
            queue.put_nowait(None)
            await sender

    async def run_spawn(spawn_id: int, task_brief: str, **kw) -> None:
        await run_with_live_frames(
            arslan.dispatch_spawn(conversation_id, spawn_id, task_brief, emit, **kw)
        )

    async def run_routed(spawn_id: int, task_brief: str, needs_proposal: bool, **kw) -> None:
        """Dispatch via the shared propose-vs-execute path (same first response a
        roster-member route gives). Used when accepting an inline invite."""
        await run_with_live_frames(
            arslan.dispatch_routed(conversation_id, spawn_id, task_brief, needs_proposal, emit, **kw)
        )

    # Connection-level state for in-chat attach + storage intent (Task 4).
    recent_material = ""
    recent_names: list[str] = []
    awaiting_store: tuple[str, list[str]] | None = None

    # Per-connection run_command confirmation state (Task 6).
    import uuid

    session_cmd_allow: set[str] = set()  # command signatures auto-approved this session

    async def confirm_command(command: str, argv: list) -> bool:
        from server.services import command_policy, settings_service
        sig = _cmd_sig(command, argv)
        if sig in session_cmd_allow:
            return True
        # Confirmation policy: 'ask_risky' auto-runs LOW-risk (read-only) commands.
        risk = command_policy.classify(command, argv)
        async with db_session.AsyncSessionLocal() as db:
            policy = await settings_service.shell_confirm_policy(db)
        if policy == "ask_risky" and risk == "LOW":
            return True
        call_id = uuid.uuid4().hex
        emit(protocol.propose_run_command(call_id, command, argv, reason=f"risk: {risk}"))
        # Own ws.receive HERE, only while this one command is pending. The plain-message
        # orchestration coro that led here is blocked awaiting this call, so the outer
        # `while True: ws.receive_json()` loop is not receiving — there is exactly one
        # receiver. We loop until THIS call_id is answered; any other frame arriving
        # mid-confirmation gets a recoverable BUSY notice (ping/pong ignored). On the
        # matching confirm/cancel we return, and the outer loop resumes receiving.
        decision = {"approved": False}
        try:
            while True:
                try:
                    data = await asyncio.wait_for(ws.receive_json(), timeout=300)
                except TimeoutError:
                    decision = {"approved": False}
                    break
                t = data.get("type")
                if t in ("ping", "pong"):
                    continue
                if (t in ("confirm_run_command", "cancel_run_command")
                        and data.get("call_id") == call_id):
                    decision = {"approved": t == "confirm_run_command",
                                "remember": bool(data.get("remember"))}
                    break
                # Any other frame (including a confirm for an unknown/stale call_id) is
                # not actionable while we are paused — tell the client, keep waiting.
                await ws.send_json(protocol.error(
                    "BUSY", "An action is awaiting your confirmation.", recoverable=True))
        except WebSocketDisconnect:
            # Client vanished mid-confirmation: decline and re-raise so the outer
            # handler's disconnect path runs (clean socket teardown).
            raise
        # Never permanently auto-approve a HIGH-risk (e.g. network) command, even if
        # the user checked "remember" — those always require a fresh card.
        if decision.get("remember") and risk != "HIGH":
            session_cmd_allow.add(sig)
        return bool(decision.get("approved"))

    async def _spawn_names() -> list[str]:
        roster = await roster_service.list_roster(conversation_id)
        return [m.get("spawn_name") for m in roster if m.get("spawn_name")]

    async def _store_into(target_name: str, material: str, names: list[str]) -> bool:
        roster = await roster_service.list_roster(conversation_id)
        match = next((m for m in roster if m.get("spawn_name") == target_name), None)
        if match is None:
            return False
        try:
            n = await ingest.ingest_text(
                int(match["spawn_id"]), names[0] if names else "附件", material
            )
        except Exception as exc:  # noqa: BLE001
            await ws.send_json(protocol.error("INGEST_ERROR", str(exc), recoverable=True))
            return True  # handled (do not fall through to routing)
        await ws.send_json(protocol.attachment_stored(target_name, n))
        return True

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
                # HX-6/P2: advisory persona-vs-equipment delivery lint (fail-open, never blocks).
                from server.services import persona_lint
                capability_warnings = await persona_lint.lint_spawn(spawn_id)
                await ws.send_json(protocol.spawn_created(spawn_id, spawn_name,
                                                          equipment=equipment, intro=intro,
                                                          capability_warnings=capability_warnings))
                newly_joined = await roster_service.join(conversation_id, spawn_id, via="created")
                if newly_joined:
                    await ws.send_json(protocol.roster_event("joined", spawn_id, spawn_name))
                await ws.send_json(protocol.roster_update(await roster_service.list_roster(conversation_id)))
                if task_brief.strip():
                    await run_spawn(spawn_id, task_brief)
                continue

            if msg_type == "confirm_update":
                # P2 apply path (the ONLY one): persona/tone/capabilities via
                # apply_conversational_update (regenerates system_prompt), equipment via
                # replace_user_equipment — every key re-validated at the Layer-2 choke.
                from server.registry import service as registry_service
                from server.registry.service import NotAssignableError
                raw_id = data.get("spawn_id")
                try:
                    spawn_id = int(raw_id)
                except (TypeError, ValueError):
                    await ws.send_json(protocol.error("INVALID_INPUT", "spawn_id required"))
                    continue
                changes = data.get("changes") or {}
                eq = await registry_service.equipment_for_spawn(spawn_id)
                _user_managed = lambda items: [  # noqa: E731
                    i["key"] for i in items
                    if i.get("grant") == "permanent" and i.get("granted_by") in ("create", "user")
                ]
                ts = _user_managed(eq["toolsets"])
                sk = _user_managed(eq["skills"])
                ts = [k for k in ts if k not in set(changes.get("remove_toolsets") or [])]
                sk = [k for k in sk if k not in set(changes.get("remove_skills") or [])]
                ts += [k for k in (changes.get("add_toolsets") or []) if k not in ts]
                sk += [k for k in (changes.get("add_skills") or []) if k not in sk]
                try:
                    async with db_session.AsyncSessionLocal() as db:
                        spawn = await spawn_service.apply_conversational_update(db, spawn_id, changes)
                        if spawn is None:
                            await ws.send_json(protocol.error("INVALID_INPUT", "unknown spawn"))
                            continue
                        await registry_service.replace_user_equipment(db, spawn_id, ts, sk)
                except NotAssignableError as exc:
                    await ws.send_json(protocol.error("NOT_ASSIGNABLE", str(exc), recoverable=True))
                    continue
                fresh = await registry_service.equipment_for_spawn(spawn_id)
                await ws.send_json(protocol.spawn_updated(spawn_id, spawn.name,
                                                          applied=changes, equipment=fresh))
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

            if msg_type == "accept_deliverable":
                raw_id = data.get("spawn_id")
                try:
                    spawn_id = int(raw_id)
                except (TypeError, ValueError):
                    await ws.send_json(protocol.error("INVALID_INPUT", "spawn_id required"))
                    continue
                raw_mid = data.get("message_id")
                try:
                    message_id = int(raw_mid) if raw_mid is not None else None
                except (TypeError, ValueError):
                    message_id = None
                await run_with_live_frames(
                    arslan.record_deliverable_verdict(conversation_id, spawn_id, "accept", message_id, emit)
                )
                continue

            if msg_type == "discard":
                raw_id = data.get("spawn_id")
                try:
                    spawn_id = int(raw_id)
                except (TypeError, ValueError):
                    await ws.send_json(protocol.error("INVALID_INPUT", "spawn_id required"))
                    continue
                raw_mid = data.get("message_id")
                try:
                    message_id = int(raw_mid) if raw_mid is not None else None
                except (TypeError, ValueError):
                    message_id = None
                await run_with_live_frames(
                    arslan.record_deliverable_verdict(conversation_id, spawn_id, "discard", message_id, emit)
                )
                continue

            if msg_type == "finalize_refinement":
                raw_id = data.get("spawn_id")
                try:
                    spawn_id = int(raw_id)
                except (TypeError, ValueError):
                    await ws.send_json(protocol.error("INVALID_INPUT", "spawn_id required"))
                    continue
                raw_mid = data.get("message_id")
                try:
                    original_message_id = int(raw_mid) if raw_mid is not None else None
                except (TypeError, ValueError):
                    original_message_id = None
                content = (data.get("content") or "").strip()
                if not content:
                    await ws.send_json(protocol.error("INVALID_INPUT", "content required"))
                    continue
                await run_with_live_frames(
                    arslan.finalize_refinement(conversation_id, spawn_id, original_message_id, content, emit)
                )
                continue

            if msg_type == "roster_invite":
                raw_id = data.get("spawn_id")
                try:
                    spawn_id = int(raw_id)
                except (TypeError, ValueError):
                    await ws.send_json(protocol.error("INVALID_INPUT", "spawn_id required"))
                    continue
                # A pending inline invite (`inviting` phase) means the user just Accepted
                # an Arslan-proposed invite. Dispatch via the SHARED propose-vs-execute path
                # (`dispatch_routed`), re-making the same decision a roster-member route would
                # have — propose-mode when the parked `needs_proposal` is set, else execute.
                # The join notice + response stream come from `_dispatch_spawn` underneath.
                # A manual invite from the Ledger has no pending phase → just join.
                pending_invite = await phase_service.get_pending_invite(conversation_id)
                if pending_invite is not None and pending_invite.get("spawn_id") == spawn_id:
                    await phase_service.clear(conversation_id)
                    # Recruiting invite (delegation cell 6): Arslan already answered the
                    # task doer-first, so Accept ONLY enrolls the spawn + posts the recruit
                    # note — it must NOT re-dispatch the answered task (Bug 1 fix). An
                    # ordinary (UNanswered) park still dispatches below (S0-2 not regressed).
                    if pending_invite.get("answered"):
                        await run_with_live_frames(
                            arslan._accept_recruit(conversation_id, spawn_id, emit)
                        )
                        continue
                    await run_routed(
                        spawn_id,
                        pending_invite.get("task_brief") or "",
                        bool(pending_invite.get("needs_proposal")),
                        user_message=pending_invite.get("user_message") or "",
                        # Arslan already spoke its brief before the card — don't repeat it.
                        announce=not bool(pending_invite.get("announced")),
                    )
                    continue
                newly_joined = await roster_service.join(conversation_id, spawn_id, via="invited")
                if newly_joined:
                    spawn_name = await dispatcher.get_spawn_name(spawn_id)
                    await ws.send_json(protocol.roster_event("joined", spawn_id, spawn_name))
                await ws.send_json(protocol.roster_update(await roster_service.list_roster(conversation_id)))
                continue

            if msg_type == "dismiss_invite":
                # The user Dismissed an Arslan-proposed inline invite card. Clear the
                # parked `inviting` phase so no dispatch happens; Arslan can answer
                # directly on the next turn.
                await phase_service.clear(conversation_id)
                continue

            if msg_type == "roster_kick":
                raw_id = data.get("spawn_id")
                try:
                    spawn_id = int(raw_id)
                except (TypeError, ValueError):
                    await ws.send_json(protocol.error("INVALID_INPUT", "spawn_id required"))
                    continue
                # Resolve name before kicking so we can name the notice.
                kick_spawn_name = await dispatcher.get_spawn_name(spawn_id)
                was_removed = await roster_service.kick(conversation_id, spawn_id)
                if was_removed:
                    await ws.send_json(protocol.roster_event("left", spawn_id, kick_spawn_name))
                await ws.send_json(protocol.roster_update(await roster_service.list_roster(conversation_id)))
                continue

            if msg_type == "roster_reset":
                # A fresh app session resumed this conversation: the roster is session
                # context, so clear it (the conversation's message history persists; spawn
                # personas live in the Ledger). The user re-pulls whoever they want this session.
                await roster_service.clear(conversation_id)
                await ws.send_json(protocol.roster_update(await roster_service.list_roster(conversation_id)))
                continue

            if msg_type == "session_ended":
                old_cid = data.get("conversation_id")
                if old_cid:
                    # Best-effort: an optional feature must never suppress the ack or close the socket.
                    try:
                        async with db_session.AsyncSessionLocal() as _s:
                            enabled = await settings_service.distill_enabled(_s)
                        if enabled:
                            asyncio.create_task(distill_service.distill_session(str(old_cid)))
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("session_ended distill trigger failed (non-fatal): %s", exc)
                    # Roster is session-ephemeral: end of session clears membership (after the
                    # distill above captures anything worth keeping). Resuming later starts empty.
                    try:
                        await roster_service.clear(str(old_cid))
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("session_ended roster clear failed (non-fatal): %s", exc)
                await ws.send_json({"type": "session_ended_ack", "conversation_id": old_cid})
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

            content = data.get("content", "")
            attached = (data.get("attached_context") or "").strip()
            if attached:
                recent_material = attached
                recent_names = data.get("attached_names") or ["附件"]

            # Reflow: a prior turn asked "记给哪个分身?" — resolve the target now.
            if awaiting_store is not None:
                material, names = awaiting_store
                try:
                    intent = await storage_intent.classify(content, names, await _spawn_names())
                except Exception:  # noqa: BLE001
                    intent = None
                if (intent is not None and intent.store and intent.target
                        and await _store_into(intent.target, material, names)):
                    awaiting_store = None
                    recent_material = ""
                    recent_names = []
                    continue
                awaiting_store = None   # give up after one try → fall through to normal handling
                recent_material = ""
                recent_names = []

            # Fresh storage intent (only when material is held)
            elif recent_material:
                try:
                    intent = await storage_intent.classify(content, recent_names, await _spawn_names())
                except Exception:  # noqa: BLE001
                    intent = None
                if intent is not None and intent.store:
                    if intent.target and await _store_into(intent.target, recent_material, recent_names):
                        recent_material = ""
                        recent_names = []
                        continue
                    # store intent but no resolvable target → ask which spawn (conversational)
                    awaiting_store = (recent_material, recent_names)
                    names = await _spawn_names()
                    question = (
                        f"这份材料记给哪个分身?在线的有:{', '.join(names) or '(暂无在线分身)'}"
                    )
                    # Send directly via ws.send_json: emit() only enqueues for the
                    # run_with_live_frames drainer, which is not running on this path.
                    await ws.send_json(protocol.stream_start_src("arslan"))
                    await ws.send_json(protocol.stream_chunk(question))
                    msg_id = await memory.add_message(conversation_id, "arslan", question)
                    await ws.send_json(protocol.stream_end(msg_id))
                    continue

            await run_with_confirm_frames(
                arslan.handle_user_message(conversation_id, content, emit,
                                           attached_context=attached or None,
                                           confirm_command=confirm_command)
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
        return protocol.routing(ev.get("spawn_id"), ev.get("spawn_name"),
                                announcement=ev.get("announcement"))
    if t == "stream_start":
        # run_id must ride through the rebuild — it is the client's cancel handle (S3-M1).
        return protocol.stream_start_src(ev.get("source", "arslan"), ev.get("spawn_id"),
                                         run_id=ev.get("run_id"))
    if t == "suggest_create":
        return protocol.suggest_create(
            ev.get("draft") or {}, task_brief=ev.get("task_brief"), overlaps=ev.get("overlaps")
        )
    if t == "fact_saved":
        return protocol.fact_saved(ev.get("content", ""), bool(ev.get("sensitive")))
    if t == "tool_call":
        return protocol.tool_call(ev.get("tool", ""), ev.get("args_summary", ""))
    if t == "tool_result":
        return protocol.tool_result(ev.get("tool", ""), bool(ev.get("ok")),
                                    ev.get("summary", ""), ev.get("artifact"))
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
    if t == "roster_event":
        return protocol.roster_event(ev.get("action", ""), ev.get("spawn_id"), ev.get("spawn_name"))
    if t == "roster_update":
        return protocol.roster_update(ev.get("members", []))
    return ev  # stream_chunk / stream_end / error / spawn_meta already match the wire shape

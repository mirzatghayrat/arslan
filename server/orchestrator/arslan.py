"""The orchestration loop for one user turn (transport-agnostic; emits event dicts)."""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable
from datetime import datetime

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import ArslanMessage
from server.orchestrator import dispatcher, memory, router
from server.orchestrator.json_protocol import parse_json_object
from server.orchestrator.untrusted import GUARD_NOTE, wrap_external
from server.services import evolution_service, phase_service, spawn_service
from server.services.llm_factory import build_adapter

logger = logging.getLogger(__name__)

EventSink = Callable[[dict], None]

# Elapsed-seconds sentinel used when the deliverable message has no timestamp.
# Treated as "slow" by speed_weight in evolution leveling.
_MISSING_ELAPSED_SECONDS = 999.0

_ARSLAN_SYSTEM = (
    "You are Arslan, a warm, concise meta-agent who helps the user and coordinates a team "
    "of specialist spawns. Answer directly and helpfully."
)

# Grounding guard: the model must describe only spawns/tools that actually exist, and must
# not mistake the user's interests (the facts block) for its own capabilities. Without this,
# a greeting like "哈喽" induced fabricated teammates/tools (e.g. invented spawn names).
_ANTI_FABRICATION = (
    "\n\nStay grounded — do NOT fabricate:\n"
    "- Your ACTUAL team is listed under \"Your team\" below. Those are the ONLY specialist "
    "spawns and tools you have. Never invent or name spawns, teammates, tools, or capabilities "
    "that are not listed there.\n"
    "- Any \"Known facts about the user\" describe the USER's interests and needs — they are NOT "
    "your own capabilities. Never present them as services you offer.\n"
    "- If asked what you can do, lead with the real specialists under \"Your team\" (by their "
    "domain). You may add that you can also help directly for general questions, but do NOT turn "
    "the user's listed interests into a menu of named services. If the team is empty, say you can "
    "help directly and invite the user to describe their need — do not make up a roster."
)


async def _team_roster() -> str:
    """A concise, user-facing list of the real spawns, to ground Arslan's self-description."""
    spawns = await spawn_service.load_all_spawns()
    if not spawns:
        return "(no spawns yet — you have no specialist team)"
    lines = []
    for s in spawns:
        domain = s.domain_category + (f".{s.domain_subcategory}" if s.domain_subcategory else "")
        role = (s.persona_role or "").strip()
        lines.append(f"- {s.name} ({domain})" + (f" — {role}" if role else ""))
    return "\n".join(lines)

_CLARIFY_ADDENDUM = (
    "\n\nThe user's request is under-specified. Ask 2-4 short, specific clarifying questions "
    "(topic, angle, format/output, and the data source if relevant), then propose a concrete "
    "direction and ask them to confirm (e.g. \"I'll research X with angle Y as a Z — sound right?\"). "
    "Do not produce the deliverable yet."
)


async def _answer_stream(system: str, user: str, history=None) -> AsyncIterator[str]:  # noqa: ANN001
    """Stream a direct Arslan reply. Separate fn so tests can stub it."""
    adapter = await build_adapter()
    async for piece in adapter.chat_stream(system, user, history=history):
        yield piece


_CLASSIFY_SYSTEM = (
    "Given a pending proposed direction and the user's reply, classify the user's intent. "
    "Reply with ONE JSON object and nothing else: {\"kind\": \"confirm\" | \"refine\" | \"new\"}. "
    "- confirm: the user approves or accepts the proposal (e.g. '好的', 'go', 'do it', 'sounds good', '就这样'). "
    "- refine: the user adjusts or modifies the direction (e.g. 'make it shorter', 'change X to Y', 'add more detail'). "
    "- new: the user has an unrelated request that does not pertain to the pending proposal."
)


async def _build_classify_adapter():
    """Indirection so tests can stub adapter construction."""
    return await build_adapter()


async def _classify_followup(user_message: str, direction: str) -> str:
    """Classify the user's reply to a pending proposal: 'confirm', 'refine', or 'new'.

    Returns 'new' on any parse failure or unexpected value.
    """
    prompt = f"Pending direction: {direction}\n\nUser's reply: {user_message}"
    adapter = await _build_classify_adapter()
    try:
        resp = await adapter.chat(system=_CLASSIFY_SYSTEM, user=prompt)
        parsed = parse_json_object(resp.content or "")
        kind = (parsed or {}).get("kind")
        if kind in ("confirm", "refine", "new"):
            return kind
    except Exception as exc:  # noqa: BLE001
        logger.warning("_classify_followup failed, defaulting to 'new': %s", exc)
    return "new"


async def handle_user_message(conversation_id: str, user_message: str, emit: EventSink) -> None:
    """Process one user turn end-to-end, emitting event dicts for the transport layer."""
    # 1. persist the user turn
    await memory.add_message(conversation_id, "user", user_message)

    # 1b. if a proposal is pending, classify the reply before routing
    pending = await phase_service.get_pending(conversation_id)
    if pending and pending["phase"] == "proposing":
        kind = await _classify_followup(user_message, pending["direction"])
        if kind == "confirm":
            await confirm_and_execute(conversation_id, pending["spawn_id"], emit)
            await memory.maybe_compact(conversation_id)
            return
        if kind == "refine":
            # task_brief stays the base direction; instruction carries the user's refinement.
            await _dispatch_spawn(
                conversation_id,
                pending["spawn_id"],
                pending["direction"],
                emit,
                mode="propose",
                prior_output=None,
                instruction=user_message,
            )
            await memory.maybe_compact(conversation_id)
            return
        # kind == "new" → clear the stale pending phase and fall through to normal routing
        await phase_service.clear(conversation_id, pending["spawn_id"])

    # 2. route (one decision call; also returns new_facts)
    result = await router.route(conversation_id, user_message)

    # 3. persist + announce extracted facts (transparency note)
    if result.new_facts:
        created = await memory.save_facts(result.new_facts)
        for fact in created:
            emit({"type": "fact_saved", "content": fact.content, "sensitive": fact.sensitive})

    # 4. handle the action
    if result.action == "route" and result.spawn_id is not None:
        await _handle_route(conversation_id, result, emit)
    elif result.action == "suggest_create":
        draft = result.suggested_spawn or {}
        overlap = spawn_service.find_overlap(draft, await spawn_service.load_all_spawns())
        if overlap is not None:
            # deterministic detection wins; keep the LLM's differentiation axes if it supplied any
            llm_axes = (result.overlaps or {}).get("axes") if isinstance(result.overlaps, dict) else None
            overlap = {**overlap, "axes": llm_axes or overlap.get("axes") or []}
        emit({
            "type": "suggest_create",
            "draft": draft,
            "task_brief": result.task_brief,
            "overlaps": overlap if overlap is not None else result.overlaps,
        })
    elif result.action == "clarify":
        await _handle_answer(conversation_id, user_message, emit, extra_system=_CLARIFY_ADDENDUM)
    else:  # answer (incl. fallback)
        await _handle_answer(conversation_id, user_message, emit)

    # 5. compact the working thread if it grew too long
    await memory.maybe_compact(conversation_id)


async def _handle_answer(
    conversation_id: str, user_message: str, emit: EventSink, *, extra_system: str = ""
) -> None:
    ctx = await memory.assemble_working_context(conversation_id)
    facts = await memory.facts_text()
    roster = await _team_roster()
    system = (
        _ARSLAN_SYSTEM + extra_system + _ANTI_FABRICATION
        + f"\n\nYour team:\n{roster}"
        + (f"\n\n{facts}" if facts else "")
    )
    if ctx["summary"]:
        system += f"\n\nConversation summary so far:\n{ctx['summary']}"

    emit({"type": "stream_start", "source": "arslan"})
    full = ""
    try:
        async for piece in _answer_stream(system, user_message, history=ctx["history"][:-1]):
            full += piece
            emit({"type": "stream_chunk", "content": piece})
    except Exception as exc:  # noqa: BLE001
        emit({"type": "error", "code": "LLM_ERROR", "message": str(exc), "recoverable": True})
        return
    msg_id = await memory.add_message(conversation_id, "arslan", full)
    emit({"type": "stream_end", "message_id": msg_id})


async def _handle_route(conversation_id, result, emit: EventSink) -> None:  # noqa: ANN001
    if getattr(result, "needs_proposal", False):
        spawn_name = await dispatcher.get_spawn_name(result.spawn_id)
        await phase_service.set_proposing(conversation_id, result.spawn_id, result.task_brief or "")
        emit({"type": "proposal", "spawn_id": result.spawn_id, "spawn_name": spawn_name})
        await _dispatch_spawn(conversation_id, result.spawn_id, result.task_brief or "", emit, mode="propose")
    else:
        await _dispatch_spawn(conversation_id, result.spawn_id, result.task_brief or "", emit)


def _arslan_fetch_executor():
    """Indirection so tests can stub Arslan's own fetch tool."""
    from server.registry.executors import EXECUTORS

    return EXECUTORS["web_search"]


async def _match_safe_toolset(need: str) -> str | None:
    """Keyword-match a capability need against the safe menu (deterministic v1)."""
    from server.registry import service as registry_service

    menu = await registry_service.safe_menu()
    need_l = need.lower()
    for t in menu["toolsets"]:
        words = [w for w in (t["name"].lower().split() + t["key"].split("_")) if len(w) > 3]
        if any(w in need_l for w in words):
            return t["key"]
    return None


async def _handle_escalation(  # noqa: ANN001
    conversation_id, spawn_id, spawn_name, task_brief, esc, emit: EventSink
) -> None:
    """Spec §3.2: refused actions stop here; allowed needs get satisfied and
    the spawn is re-dispatched ONCE with escalation disabled (depth-1)."""
    from server.orchestrator import escalation as esc_guard
    from server.registry import service as registry_service

    emit({"type": "escalation", "spawn_id": spawn_id, "spawn_name": spawn_name,
          "kind": esc.get("kind", "data"), "need": esc.get("need", "")})

    verdict = await esc_guard.classify(esc)
    if not verdict["allowed"]:
        emit({"type": "escalation_refused", "spawn_id": spawn_id, "why": verdict["why"]})
        emit({"type": "stream_end", "message_id": None})
        return

    granted = False
    if esc.get("kind") == "capability":
        match = await _match_safe_toolset(esc.get("need", ""))
        if match is not None:
            # Skip the grant if the spawn already holds this toolset — the real need
            # is unsatisfied and would silently die under depth-1. Fall through to fetch.
            eq = await registry_service.equipment_for_spawn(spawn_id)
            already_held = {t["key"] for t in eq["toolsets"]}
            if match not in already_held:
                current_turn = await memory.user_turn_count(conversation_id)
                await registry_service.grant_temporary(spawn_id, match, current_turn=current_turn)
                emit({"type": "escalation_resolved", "spawn_id": spawn_id,
                      "how": "granted", "detail": match})
                granted = True

    data_block = ""
    if not granted:
        emit({"type": "orchestrator_action", "tool": "web_search",
              "reason": f"fetching what {spawn_name} needs: {esc.get('need', '')}"})
        try:
            result = await _arslan_fetch_executor().execute({"query": esc.get("need", "")})
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error": str(exc)}
        if result.get("ok"):
            # data_block carries untrusted web content into the spawn brief (prompt-injection
            # surface). Mitigations now in place: wrap_external() frames it data-only AND strips
            # forged delimiters; SSRF redirect re-checking guards the fetch (executors.py). The
            # permission tier remains the strongest backstop.
            raw = json.dumps(result.get("results", []), ensure_ascii=False)[:6000]
            data_block = (
                f"\n\n{GUARD_NOTE}\n\n"
                "Arslan provides this data for your need "
                f"({esc.get('need', '')}):\n{wrap_external(raw)}"
            )
            emit({"type": "escalation_resolved", "spawn_id": spawn_id,
                  "how": "data_provided", "detail": esc.get("need", "")})
        else:
            emit({"type": "escalation_resolved", "spawn_id": spawn_id,
                  "how": "unresolved", "detail": str(result.get("error", ""))})

    out = await dispatcher.dispatch(
        conversation_id,
        spawn_id=spawn_id,
        task_brief=task_brief + data_block,
        on_chunk=lambda c: emit({"type": "stream_chunk", "content": c}),
        on_event=emit,
        allow_escalation=False,
    )
    emit({
        "type": "spawn_meta",
        "arslan_message_id": out["summary_message_id"],
        "spawn_id": spawn_id,
        "assistant_message_id": out["assistant_message_id"],
        "task_brief": task_brief,
    })
    emit({"type": "stream_end", "message_id": out["summary_message_id"]})


async def _dispatch_spawn(  # noqa: ANN001
    conversation_id,
    spawn_id,
    task_brief,
    emit: EventSink,
    *,
    prior_output: str | None = None,
    instruction: str | None = None,
    mode: str = "execute",
) -> None:
    """Run one spawn turn: routing -> stream_start -> chunks -> spawn_meta -> stream_end.

    Reusable for both initial routing and refinements (via prior_output/instruction).
    """
    # Resolve the spawn name first so the routing caption is complete before streaming.
    spawn_name = await dispatcher.get_spawn_name(spawn_id)
    emit({"type": "routing", "spawn_id": spawn_id, "spawn_name": spawn_name})
    emit({"type": "stream_start", "source": "spawn", "spawn_id": spawn_id})
    try:
        out = await dispatcher.dispatch(
            conversation_id,
            spawn_id=spawn_id,
            task_brief=task_brief,
            on_chunk=lambda c: emit({"type": "stream_chunk", "content": c}),
            on_event=emit,
            prior_output=prior_output,
            instruction=instruction,
            mode=mode,
        )
    except Exception as exc:  # noqa: BLE001
        emit({"type": "error", "code": "SPAWN_ERROR", "message": str(exc), "recoverable": True})
        return

    if out.get("escalation"):
        await _handle_escalation(
            conversation_id, spawn_id, spawn_name, task_brief, out["escalation"], emit
        )
        return

    emit({
        "type": "spawn_meta",
        "arslan_message_id": out["summary_message_id"],
        "spawn_id": spawn_id,
        "assistant_message_id": out["assistant_message_id"],
        "task_brief": task_brief,
    })
    emit({"type": "stream_end", "message_id": out["summary_message_id"]})


async def confirm_and_execute(conversation_id: str, spawn_id: int, emit: EventSink) -> None:
    """User confirmed a pending proposal — run the spawn in execute mode on the stored direction."""
    pending = await phase_service.get_pending(conversation_id)
    direction = (pending or {}).get("direction", "")
    await phase_service.clear(conversation_id, spawn_id)
    await _dispatch_spawn(conversation_id, spawn_id, direction, emit, mode="execute")


async def record_deliverable_verdict(
    conversation_id: str,
    spawn_id: int,
    action: str,
    message_id: int | None,
    emit: EventSink,
) -> None:
    """Record an accept/discard verdict for a deliverable message as a leveling signal.

    Resolves the spawn name, fetches the deliverable message, computes elapsed time,
    finds the prior user message, then calls evolution_service.record_verdict.
    Emits a verdict_recorded ack regardless of any leveling failure.
    """
    # Resolve spawn name
    spawn_name = await dispatcher.get_spawn_name(spawn_id)
    if spawn_name is None:
        logger.warning("record_deliverable_verdict: unknown spawn_id=%s", spawn_id)
        emit({"type": "error", "code": "INVALID_INPUT", "message": "unknown spawn", "recoverable": True})
        return

    # Fetch the deliverable message and compute elapsed seconds
    agent_output = ""
    elapsed_seconds = _MISSING_ELAPSED_SECONDS
    if message_id is not None:
        async with db_session.AsyncSessionLocal() as db:
            row = await db.execute(
                select(ArslanMessage).where(ArslanMessage.id == message_id)
            )
            msg = row.scalar_one_or_none()
        if msg is not None:
            agent_output = msg.display_content or msg.content or ""
            if msg.timestamp is not None:
                raw = (datetime.utcnow() - msg.timestamp).total_seconds()
                elapsed_seconds = max(0.0, raw)

    # Find the most recent prior user message in this conversation
    user_input = ""
    async with db_session.AsyncSessionLocal() as db:
        q = select(ArslanMessage).where(
            ArslanMessage.conversation_id == conversation_id,
            ArslanMessage.role == "user",
        )
        if message_id is not None:
            q = q.where(ArslanMessage.id < message_id)
        q = q.order_by(ArslanMessage.id.desc()).limit(1)
        row2 = await db.execute(q)
        prior = row2.scalar_one_or_none()
    if prior is not None:
        user_input = prior.content or ""

    # Record the verdict (defensive — a leveling failure must not break the socket)
    try:
        evolution_service.record_verdict(
            spawn_name,
            session_id=conversation_id,
            user_input=user_input,
            agent_output=agent_output,
            action=action,
            elapsed_seconds=elapsed_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("record_verdict failed (non-fatal): %s", exc)

    # Ack to the client
    emit({"type": "verdict_recorded", "spawn_id": spawn_id, "action": action})


# Public alias for reuse from other orchestration entry points (e.g. refinements).
dispatch_spawn = _dispatch_spawn

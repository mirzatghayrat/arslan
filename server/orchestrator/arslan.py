"""The orchestration loop for one user turn (transport-agnostic; emits event dicts)."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable

from server.orchestrator import dispatcher, memory, router
from server.orchestrator.untrusted import GUARD_NOTE, wrap_external
from server.services import spawn_service
from server.services.llm_factory import build_adapter

EventSink = Callable[[dict], None]

_ARSLAN_SYSTEM = (
    "You are Arslan, a warm, concise meta-agent who helps the user and coordinates a team "
    "of specialist spawns. Answer directly and helpfully."
)

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


async def handle_user_message(conversation_id: str, user_message: str, emit: EventSink) -> None:
    """Process one user turn end-to-end, emitting event dicts for the transport layer."""
    # 1. persist the user turn
    await memory.add_message(conversation_id, "user", user_message)

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
    system = _ARSLAN_SYSTEM + extra_system + (f"\n\n{facts}" if facts else "")
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
            # NOTE: data_block carries untrusted web content into the spawn brief (prompt-injection surface). must-fix-before-public-release: heavier mitigations (injection-signature stripping, SSRF redirect re-checking) are deferred.
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


# Public alias for reuse from other orchestration entry points (e.g. refinements).
dispatch_spawn = _dispatch_spawn

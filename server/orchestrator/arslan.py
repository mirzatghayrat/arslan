"""The orchestration loop for one user turn (transport-agnostic; emits event dicts)."""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import ArslanMessage, Feedback
from server.orchestrator import dispatcher, memory, router, tool_loop
from server.orchestrator.json_protocol import parse_json_object
from server.orchestrator.untrusted import GUARD_NOTE, wrap_external
from server.ws import protocol
from arslan.llm import usage_sink
from server.services import (
    equipment_service,
    evolution_service,
    phase_service,
    roster_service,
    run_recorder,
    spawn_service,
)
from server.services.llm_factory import build_adapter

logger = logging.getLogger(__name__)

EventSink = Callable[[dict], None]

# Elapsed-seconds sentinel used when the deliverable message has no timestamp.
# Treated as "slow" by speed_weight in evolution leveling.
_MISSING_ELAPSED_SECONDS = 999.0

_ARSLAN_SYSTEM = (
    "You are Arslan, a warm, sharp, genuinely human-feeling meta-agent who talks WITH the user and "
    "coordinates a team of specialist spawns behind the scenes. "
    "Match the user's register. When they're just chatting or being casual, be casual and human right "
    "back — short, relaxed, a little personality and warmth, the occasional emoji is fine, and vary "
    "your openers. When they bring a real task, get crisp and well-structured. Never answer simple "
    "small-talk with numbered lists, and if they say something like 'let's keep it light', actually "
    "keep it light instead of pivoting to a checklist. Always reply in the user's language. "
    "Introduce yourself as Arslan once when greeting or when asked — do NOT prefix every message with "
    "'I am Arslan' / '我是 Arslan', and never use servile, waiter-like openers (e.g. '随时为您服务', "
    "'at your service', 'how may I help you today'). "
    "Identity lock: you ALWAYS speak as Arslan. Earlier turns in this conversation may have been written "
    "by one of your specialist spawns (a teammate) — never adopt a teammate's name or first-person "
    "identity; you are Arslan, not any of your spawns. "
    "Don't invent facts, current events, or conversation topics you have no real basis for; if you don't "
    "actually know what's new or what the user has been up to, just ask instead of fabricating."
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

# Binds "unsure about something current" → "search", NOT → "ask / fabricate". Without this,
# the model narrates "let me search" (or invents) instead of emitting the tool call. Only added
# on Arslan's answer path, where web_search/web_extract are actually available.
_WEB_TOOL_GUIDANCE = (
    "\n\nGoing online — you CAN search the web (web_search) and fetch a page's text (web_extract):\n"
    "- When the user asks about anything current, real-time, or recent that you cannot be certain of "
    "from memory — latest news, prices or markets, a product's newest version, recent events, "
    "someone's current status — you MUST actually CALL web_search (emit the tool call). Even when you "
    "think you know, if the question is about 'right now', search to verify.\n"
    "- Use search INSTEAD of fabricating and INSTEAD of just asking the user or telling them to look it "
    "up themselves.\n"
    "- ACT, don't narrate: NEVER end your turn with a promise to search ('我去搜一下' / 'let me search' / "
    "'我直接搜一下') — in THIS reply you either emit the web_search tool call OR answer directly. A "
    "promise to search without the tool call does nothing and leaves the user waiting.\n"
    "- Note: you do NOT need web_search for the current date/time — it is given to you below. web_search "
    "returns web pages, not a live clock, so don't use it to fetch the exact current minute.\n"
    "- If the search returns nothing useful, or reports it is not configured, say so plainly and answer "
    "with only what you reliably know — never invent a result."
)


def _now_line() -> str:
    """Current server time injected into Arslan's prompt so date/time questions need no search."""
    now = datetime.utcnow()
    return (
        f"\n\nCurrent date/time (server clock, UTC): {now:%Y-%m-%d %H:%M} ({now:%A}). "
        "Use this directly for 'today' / 'now' / the current date; convert to the user's timezone "
        "when asked (e.g. Beijing = UTC+8). Do NOT search the web for the current date/time."
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

def _draft_is_sufficient(draft: dict, task_brief: str | None) -> bool:
    """A proposal needs enough to draft a capable spawn: a domain, at least one
    capability, and a concrete task to run. Otherwise Arslan clarifies first."""
    has_domain = bool((draft.get("domain") or "").strip())
    has_caps = bool(draft.get("capabilities"))
    has_task = bool((task_brief or "").strip())
    return has_domain and has_caps and has_task


_CLARIFY_ADDENDUM = (
    "\n\nThe user's request is under-specified. Ask 2-4 short, specific clarifying questions "
    "(topic, angle, format/output, and the data source if relevant), then propose a concrete "
    "direction and ask them to confirm (e.g. \"I'll research X with angle Y as a Z — sound right?\"). "
    "Do not produce the deliverable yet."
)


_CLASSIFY_SYSTEM = (
    "Given a pending proposed direction and the user's reply, classify the user's intent. "
    "Reply with ONE JSON object and nothing else: {\"kind\": \"confirm\" | \"refine\" | \"new\"}. "
    "- confirm: the user approves or accepts the proposal (e.g. '好的', 'go', 'do it', 'sounds good', '就这样'). "
    "- refine: the user adjusts or modifies the direction (e.g. 'make it shorter', 'change X to Y', 'add more detail'). "
    "- new: the user has an unrelated request that does not pertain to the pending proposal."
)


async def _build_classify_adapter():
    """Indirection so tests can stub adapter construction."""
    return await build_adapter(role="converse")


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


async def handle_user_message(
    conversation_id: str,
    user_message: str,
    emit: EventSink,
    *,
    attached_context: str | None = None,
) -> None:
    """Process one user turn end-to-end, emitting event dicts for the transport layer."""
    with usage_sink.collecting():
        # 1. persist the user turn
        await memory.add_message(conversation_id, "user", user_message)

        # 1b. if a proposal is pending, classify the reply before routing
        pending = await phase_service.get_pending(conversation_id)
        if pending and pending["phase"] == "proposing":
            # _classify_followup calls the LLM — guard it so an LLM error surfaces as
            # an in-chat error frame instead of crashing the WebSocket.
            try:
                kind = await _classify_followup(user_message, pending["direction"])
            except Exception as exc:  # noqa: BLE001
                logger.warning("_classify_followup raised (surfacing as error): %s", exc)
                emit({"type": "error", "code": "LLM_ERROR", "message": str(exc), "recoverable": True})
                return
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
                    user_message=user_message,
                )
                await memory.maybe_compact(conversation_id)
                return
            # kind == "new" → clear the stale pending phase and fall through to normal routing
            await phase_service.clear(conversation_id, pending["spawn_id"])

        # 1c. clarifying-create phase (B4): while Arslan is gathering an under-specified
        # create request, the follow-up answer must keep clarifying (Arslan's voice) — it
        # must NOT be routed/dispatched to an existing spawn (routing leaks "请以X的身份"
        # identity-bleed into the answer layer). We still route() below, but if the router
        # wants to route to an existing spawn we OVERRIDE it to the clarify path. A
        # sufficient suggest_create (the user finally gave enough) is allowed and clears
        # the phase; answer/clarify proceed normally. Proposing takes precedence (handled
        # above and returns), so the two phases are never both live here.
        clarifying = bool(pending and pending["phase"] == "clarifying")

        # 2. route (one decision call; also returns new_facts).  Guard it so an LLM
        # error (e.g. timeout, auth failure) surfaces as a recoverable in-chat error
        # frame instead of propagating out of run_with_live_frames and closing the WS.
        try:
            t0 = datetime.utcnow()
            result = await router.route(conversation_id, user_message)
            route_ms = int((datetime.utcnow() - t0).total_seconds() * 1000)
        except Exception as exc:  # noqa: BLE001
            logger.warning("router.route raised (surfacing as error): %s", exc)
            emit({"type": "error", "code": "LLM_ERROR", "message": str(exc), "recoverable": True})
            return

        # 3. persist + announce extracted facts (transparency note)
        if result.new_facts:
            created = await memory.save_facts(result.new_facts)
            for fact in created:
                emit({"type": "fact_saved", "content": fact.content, "sensitive": fact.sensitive})

        # B4: while clarifying a create, suppress routing to an existing spawn —
        # keep clarifying in Arslan's voice instead of leaking spawn identity.
        # Invariant: the clarifying phase persists ONLY while the router keeps
        # producing an insufficient create-downgrade; clear it on every other
        # terminal outcome. Here the user wants a DIFFERENT spawn — divert THIS
        # turn (no bleed), but clear so the next route dispatches normally.
        if clarifying and result.action == "route":
            await phase_service.clear_clarifying(conversation_id)
            await _handle_answer(conversation_id, user_message, emit,
                                 extra_system=_CLARIFY_ADDENDUM,
                                 attached_context=attached_context)
            await memory.maybe_compact(conversation_id)
            return

        # 4. handle the action
        if result.action == "route" and result.spawn_id is not None:
            await _handle_route(conversation_id, result, emit, user_message=user_message,
                                route_ms=route_ms, attached_context=attached_context)
        elif result.action == "suggest_create":
            draft = result.suggested_spawn or {}
            if not _draft_is_sufficient(draft, result.task_brief):
                # Gather first — Arslan asks for the missing piece in its own voice,
                # rather than proposing a thin/premature spawn. B4 pins a "clarifying"
                # phase here so the follow-up keeps gathering (not routes to an existing
                # spawn) until the user supplies enough or changes subject.
                await phase_service.set_clarifying(conversation_id)
                await _handle_answer(conversation_id, user_message, emit,
                                     extra_system=_CLARIFY_ADDENDUM,
                                     attached_context=attached_context)
                await memory.maybe_compact(conversation_id)
                return
            # Sufficient draft: the user gave enough — clear any clarifying phase and
            # proceed to the proposal (routing/proposing resumes normally).
            if clarifying:
                await phase_service.clear_clarifying(conversation_id)
            # Enrich the draft with real equipment via the same L1 mapping (curate),
            # best-effort: a failure must never block the suggestion. setdefault keeps
            # any equipment a future drafter path may already have supplied.
            need = " ".join(filter(None, [
                draft.get("name"), draft.get("domain"), draft.get("persona_role"),
                ", ".join(draft.get("capabilities") or []),
            ]))
            try:
                eq = await equipment_service.curate(need) if need.strip() else {}
            except Exception as exc:  # noqa: BLE001
                logger.warning("suggest_create equipment enrichment failed: %s", exc)
                eq = {}
            draft.setdefault("tools", eq.get("toolsets") or [])
            draft.setdefault("skills", eq.get("skills") or [])
            draft.setdefault("mcps", eq.get("mcps") or [])
            draft.setdefault("gaps", eq.get("gaps") or [])
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
            # Router no longer sees create-intent — release any clarifying phase.
            if clarifying:
                await phase_service.clear_clarifying(conversation_id)
            await _handle_answer(conversation_id, user_message, emit, extra_system=_CLARIFY_ADDENDUM,
                                 attached_context=attached_context)
        else:  # answer (incl. fallback)
            # Router no longer sees create-intent — release any clarifying phase.
            if clarifying:
                await phase_service.clear_clarifying(conversation_id)
            await _handle_answer(conversation_id, user_message, emit, attached_context=attached_context)

        # 5. compact the working thread if it grew too long
        await memory.maybe_compact(conversation_id)


async def _handle_answer(
    conversation_id: str, user_message: str, emit: EventSink, *, extra_system: str = "",
    attached_context: str | None = None,
) -> None:
    ctx = await memory.assemble_working_context(conversation_id)
    facts = await memory.facts_text()
    roster = await _team_roster()
    system = (
        _ARSLAN_SYSTEM + extra_system + _ANTI_FABRICATION + _WEB_TOOL_GUIDANCE + _now_line()
        + f"\n\nYour team:\n{roster}"
        + (f"\n\n{facts}" if facts else "")
    )
    if ctx["summary"]:
        system += f"\n\nConversation summary so far:\n{ctx['summary']}"

    llm_user = user_message
    if attached_context:
        llm_user = f"[附带材料]\n{attached_context}\n\n[用户消息]\n{user_message}"

    emit({"type": "stream_start", "source": "arslan"})
    try:
        result = await tool_loop.run(
            system=system,
            user_content=llm_user,
            history=ctx["history"][:-1],
            emit=emit,
            on_chunk=lambda c: emit({"type": "stream_chunk", "content": c}),
            resolve_tools=_arslan_tools,
            allow_escalation=False,
        )
    except Exception as exc:  # noqa: BLE001
        emit({"type": "error", "code": "LLM_ERROR", "message": str(exc), "recoverable": True})
        return
    full = result.get("final") or ""
    msg_id = await memory.add_message(conversation_id, "arslan", full)
    emit({"type": "stream_end", "message_id": msg_id})


async def _handle_route(conversation_id, result, emit: EventSink, *,  # noqa: ANN001
                        user_message: str = "", route_ms: int | None = None,
                        attached_context: str | None = None) -> None:
    if getattr(result, "needs_proposal", False):
        spawn_name = await dispatcher.get_spawn_name(result.spawn_id)
        await phase_service.set_proposing(conversation_id, result.spawn_id, result.task_brief or "")
        emit({"type": "proposal", "spawn_id": result.spawn_id, "spawn_name": spawn_name})
        await _dispatch_spawn(conversation_id, result.spawn_id, result.task_brief or "", emit,
                              mode="propose", user_message=user_message, route_ms=route_ms,
                              attached_context=attached_context)
    else:
        await _dispatch_spawn(conversation_id, result.spawn_id, result.task_brief or "", emit,
                              user_message=user_message, route_ms=route_ms,
                              attached_context=attached_context)


async def propose_invite(
    conversation_id: str, *, spawn_id: int, reason: str, emit: EventSink
) -> None:
    """Propose bringing an existing spawn into the conversation (B5).

    Emits a `propose_invite` frame and joins NOTHING. The frontend renders a
    confirmation card; on confirm it sends the existing `roster_invite {spawn_id}`
    frame, which is the single, idempotent join path. Keeping the join out of this
    step is the whole point — "邀请无确认" is fixed by deferring the join to the
    user's explicit confirmation.
    """
    emit(protocol.propose_invite(spawn_id, reason))


def _arslan_fetch_executor():
    """Indirection so tests can stub Arslan's own fetch tool."""
    from server.registry.executors import EXECUTORS

    return EXECUTORS["web_search"]


async def _arslan_tools() -> list[dict]:
    """Arslan's host-level safe toolset: web + chart (no spawn wiring)."""
    from server.registry.executors import EXECUTORS

    desc = {
        "web_search": "Search the web for fresh/factual info; returns titles/urls/snippets.",
        "web_extract": "Fetch a URL and return its main text (SSRF-guarded).",
        "render_chart": "Render a line/bar/pie chart from structured data; the user sees the chart.",
    }
    tools = [{"key": k, "description": desc[k]} for k in ("web_search", "web_extract", "render_chart") if k in EXECUTORS]
    # Host-allowed MCP tools: human-wired AND explicitly host_enabled (default off).
    from sqlalchemy import select

    from server.db import session as db_session
    from server.db.models import Tool
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Tool).where(Tool.toolset_key.like("mcp_%"),
                               Tool.status == "wired", Tool.host_enabled.is_(True))
        )).scalars().all()
    tools += [{"key": t.key, "description": t.description} for t in rows]
    return tools


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
    conversation_id, spawn_id, spawn_name, task_brief, esc, emit: EventSink, *, run_id: int | None = None
) -> dict | None:
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
        return None

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
        "spawn_name": spawn_name,
        "assistant_message_id": out["assistant_message_id"],
        "task_brief": task_brief,
        "run_id": run_id,
    })
    emit({"type": "stream_end", "message_id": out["summary_message_id"]})
    return out


async def _dispatch_spawn(  # noqa: ANN001
    conversation_id,
    spawn_id,
    task_brief,
    emit: EventSink,
    *,
    prior_output: str | None = None,
    instruction: str | None = None,
    mode: str = "execute",
    user_message: str = "",
    route_ms: int | None = None,
    attached_context: str | None = None,
) -> None:
    """Run one spawn turn, recording it as a Run for replay + evaluation."""
    spawn_name = await dispatcher.get_spawn_name(spawn_id)
    recorder = await run_recorder.RunRecorder.start(
        conversation_id=conversation_id, spawn_id=spawn_id, spawn_name=spawn_name,
        user_message=user_message or task_brief, route_ms=route_ms,
    )
    tee = recorder.tee(emit)

    newly_joined = await roster_service.join(conversation_id, spawn_id, via="routed")
    if newly_joined:
        tee({"type": "roster_event", "action": "joined", "spawn_id": spawn_id, "spawn_name": spawn_name})
    tee({"type": "roster_update", "members": await roster_service.list_roster(conversation_id)})
    tee({"type": "routing", "spawn_id": spawn_id, "spawn_name": spawn_name})
    tee({"type": "stream_start", "source": "spawn", "spawn_id": spawn_id})
    try:
        out = await dispatcher.dispatch(
            conversation_id, spawn_id=spawn_id, task_brief=task_brief,
            on_chunk=lambda c: tee({"type": "stream_chunk", "content": c}),
            on_event=tee, prior_output=prior_output, instruction=instruction, mode=mode,
            attached_context=attached_context,
        )
    except Exception as exc:  # noqa: BLE001
        tee({"type": "error", "code": "SPAWN_ERROR", "message": str(exc), "recoverable": True})
        await recorder.finalize(summary_message_id=None, full_output="")
        return

    if out.get("escalation"):
        esc_out = await _handle_escalation(
            conversation_id, spawn_id, spawn_name, task_brief, out["escalation"], tee,
            run_id=recorder.run_id,
        )
        final = esc_out or out
        await recorder.finalize(
            summary_message_id=final.get("summary_message_id"),
            full_output=final.get("full_output", ""),
        )
        return

    await recorder.finalize(
        summary_message_id=out["summary_message_id"], full_output=out["full_output"],
    )
    tee({
        "type": "spawn_meta", "arslan_message_id": out["summary_message_id"],
        "spawn_id": spawn_id, "spawn_name": spawn_name,
        "assistant_message_id": out["assistant_message_id"],
        "task_brief": task_brief, "run_id": recorder.run_id,
    })
    tee({"type": "stream_end", "message_id": out["summary_message_id"]})


async def confirm_and_execute(conversation_id: str, spawn_id: int, emit: EventSink) -> None:
    """User confirmed a pending proposal — execute, carrying the spawn's proposed direction.

    The stored ``direction`` is the original task brief; the spawn's own proposed direction
    (its last propose-mode output) is fetched and carried via ``execute_confirmed`` framing so
    the spawn delivers the final result instead of re-asking clarifying questions.
    """
    pending = await phase_service.get_pending(conversation_id)
    direction = (pending or {}).get("direction", "")
    proposed = await dispatcher.last_spawn_output(spawn_id)
    await phase_service.clear(conversation_id, spawn_id)
    await _dispatch_spawn(
        conversation_id, spawn_id, direction, emit,
        mode="execute_confirmed", prior_output=proposed,
    )


async def record_deliverable_verdict(
    conversation_id: str,
    spawn_id: int,
    action: str,
    message_id: int | None,
    emit: EventSink,
    *,
    elapsed_override: float | None = None,
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
    if elapsed_override is not None:
        elapsed_seconds = max(0.0, float(elapsed_override))
    if message_id is not None:
        async with db_session.AsyncSessionLocal() as db:
            row = await db.execute(
                select(ArslanMessage).where(ArslanMessage.id == message_id)
            )
            msg = row.scalar_one_or_none()
        if msg is not None:
            agent_output = msg.display_content or msg.content or ""
            if elapsed_override is None and msg.timestamp is not None:
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

    # Also persist a per-conversation Feedback row (keyed by the REAL conversation_id, not
    # the degenerate `spawn-{id}` key) so session-end distillation can read 👍/👎 as a
    # signal. Best-effort — must never break the verdict ack.
    try:
        feedback_action = "thumbs_up" if action == "accept" else "thumbs_down"
        async with db_session.AsyncSessionLocal() as db:
            db.add(Feedback(
                spawn_id=spawn_id,
                session_id=conversation_id,
                message_id=message_id,
                user_action=feedback_action,
                quality_signal=evolution_service.quality_signal_for(feedback_action),
            ))
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("verdict Feedback persist failed (non-fatal): %s", exc)

    # Ack to the client
    emit({"type": "verdict_recorded", "spawn_id": spawn_id, "action": action})


async def finalize_refinement(
    conversation_id: str,
    spawn_id: int,
    original_message_id: int | None,
    content: str,
    emit: EventSink,
) -> None:
    """Persist a refined spawn deliverable into the orchestrator conversation and
    record it as an accepted verdict. Content is the spawn's own refined output
    (from its direct-chat), posted back to the main thread by the user."""
    spawn_name = await dispatcher.get_spawn_name(spawn_id)
    if spawn_name is None:
        emit({"type": "error", "code": "INVALID_INPUT", "message": "unknown spawn", "recoverable": True})
        return
    new_id = await memory.add_message(
        conversation_id, "spawn_summary", content, display_content=content, spawn_id=spawn_id
    )
    emit({
        "type": "deliverable_finalized", "spawn_id": spawn_id, "message_id": new_id,
        "content": content, "refined_from": original_message_id, "spawn_name": spawn_name,
    })
    # Record an accept signal against the finalized deliverable (reuses evolution path;
    # its verdict_recorded ack marks the just-appended item accepted in the UI).
    await record_deliverable_verdict(conversation_id, spawn_id, "accept", new_id, emit)


async def confirm_sandbox_merge(
    conversation_id: str,
    spawn_id: int,
    content: str,
    summary: str,
    elapsed_seconds: float,
    emit: EventSink,
) -> int | None:
    """Merge a sandbox session's final deliverable into the main orchestration thread:
    append a spawn_summary card (display_content = TL;DR caption + full content), emit
    deliverable_finalized(+summary), and record a speed-weighted accept verdict.
    Returns the new message id, or None if the spawn is unknown."""
    spawn_name = await dispatcher.get_spawn_name(spawn_id)
    if spawn_name is None:
        emit({"type": "error", "code": "INVALID_INPUT", "message": "unknown spawn", "recoverable": True})
        return None
    display = f"**✓ {summary}**\n\n{content}" if summary else content
    new_id = await memory.add_message(
        conversation_id, "spawn_summary", content, display_content=display, spawn_id=spawn_id
    )
    emit({
        "type": "deliverable_finalized", "spawn_id": spawn_id, "message_id": new_id,
        "content": content, "summary": summary, "refined_from": None, "spawn_name": spawn_name,
    })
    await record_deliverable_verdict(
        conversation_id, spawn_id, "accept", new_id, emit, elapsed_override=elapsed_seconds
    )
    return new_id


# Public alias for reuse from other orchestration entry points (e.g. refinements).
dispatch_spawn = _dispatch_spawn

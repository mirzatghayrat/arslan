"""The orchestration loop for one user turn (transport-agnostic; emits event dicts)."""
from __future__ import annotations

import asyncio
import json
import logging
import re as _re
import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select

from server.orchestrator import vision_errors
from server.services import ocr_fallback
from server.db import session as db_session
from server.db.models import ArslanMessage, Feedback
from server.orchestrator import (
    confirm_lexicon,
    dispatcher,
    memory,
    promise_guard,
    router,
    run_trace,
    tool_loop,
)
from server.orchestrator.json_protocol import parse_json_object
from server.orchestrator.tool_caller import ToolCaller
from server.orchestrator.untrusted import GUARD_NOTE, wrap_external
from server.ws import protocol
from arslan.llm import prices, usage_sink
from arslan.llm.cached_system import build_cached_system
from server.registry import service as registry_service
from server.services import (
    distill_service,
    equipment_service,
    evolution_service,
    phase_service,
    roster_service,
    run_recorder,
    run_registry,
    spawn_drafter,
    spawn_match_service,
    spawn_service,
    staffing_gather,
    usage_ledger,
)
from server.services.llm_factory import build_adapter

logger = logging.getLogger(__name__)

EventSink = Callable[[dict], None]

# Elapsed-seconds sentinel used when the deliverable message has no timestamp.
# Treated as "slow" by speed_weight in evolution leveling.
_MISSING_ELAPSED_SECONDS = 999.0

# Auto-continue budget: how many extra rounds Arslan may automatically run per user
# turn when a round ends with a 【阶段性发现】/[Findings so far] digest (tool budget
# exhausted but evidence carried forward). Threaded as a per-dispatch parameter —
# NEVER module-global mutable state (concurrent conversations must not share it).
MAX_AUTO_CONTINUES = 2

# Markers written by tool_loop._fallback_with_digest. Their presence means the round
# made real progress but ran out of tool budget — safe (and worth it) to auto-continue.
# The bare no-evidence fallback carries NO marker and must never auto-continue
# (zero progress → looping would just burn tokens).
_DIGEST_MARKERS = ("【阶段性发现】", "[Findings so far]")


def _has_findings_digest(text: str) -> bool:
    t = text or ""
    return any(m in t for m in _DIGEST_MARKERS)


def _is_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in (text or ""))


# Deterministic second-stage alias groups: when the task brief mentions any token of a
# group AND another real spawn's domain/name/capabilities mention any token of the SAME
# group, that spawn is a plausible next stage (e.g. 生成PPT → the deck/presentation
# spawn). Purely lexical — no extra LLM call, zero fabrication risk.
_STAGE_ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("ppt", "pptx", "deck", "slide", "slides", "presentation", "幻灯", "演示"),
    ("chart", "图表", "可视化", "visualization", "visualisation"),
)


def _spawn_terms(s) -> str:  # noqa: ANN001
    """Lower-cased searchable text for one spawn (name + domain + capabilities)."""
    fields = [
        getattr(s, "name", "") or "",
        getattr(s, "domain_category", "") or "",
        getattr(s, "domain_subcategory", "") or "",
        *(getattr(s, "capabilities", None) or []),
    ]
    return " ".join(str(f) for f in fields).lower()


def _find_second_stage(task_brief: str, spawns: list, primary_id: int, roster_ids: set[int]):  # noqa: ANN001
    """The one other REAL spawn the task clearly implies as a follow-up stage, or None.
    Conversation-roster members are preferred over the rest of the registry."""
    brief_l = (task_brief or "").lower()
    candidates = sorted(
        (s for s in spawns if getattr(s, "id", None) != primary_id),
        key=lambda s: (0 if getattr(s, "id", None) in roster_ids else 1, getattr(s, "id", 0)),
    )
    for s in candidates:
        terms = _spawn_terms(s)
        for group in _STAGE_ALIAS_GROUPS:
            if any(tok in brief_l for tok in group) and any(tok in terms for tok in group):
                return s
    return None


async def _route_announcement(
    conversation_id: str, spawn_id: int, spawn_name: str, task_brief: str
) -> str:
    """Deterministic routing brief shown when Arslan hands a task to a spawn:
    one sentence restating the need (the router's task_brief), then one line per
    involved spawn as an @-mention. Every mentioned name comes from the REAL spawn
    registry/roster — nothing is invented, and no extra LLM call is made."""
    cjk = _is_cjk(task_brief) or _is_cjk(spawn_name)
    lines: list[str] = []
    need = (task_brief or "").strip()
    if need:
        lines.append(need)

    primary_role = ""
    second = None
    try:
        spawns = await spawn_service.load_all_spawns()
        roster = await roster_service.list_roster(conversation_id)
        roster_ids = {int(m["spawn_id"]) for m in roster if m.get("spawn_id") is not None}
        primary = next((s for s in spawns if getattr(s, "id", None) == spawn_id), None)
        primary_role = (getattr(primary, "persona_role", None) or "").strip()
        second = _find_second_stage(task_brief or "", spawns, spawn_id, roster_ids)
    except Exception as exc:  # noqa: BLE001 — enrichment is best-effort; the primary line never fails
        logger.warning("route announcement enrichment failed (non-fatal): %s", exc)

    own = primary_role or ("执行这项任务" if cjk else "handle this task")
    lines.append(f"@{spawn_name} — 负责:{own}" if cjk else f"@{spawn_name} — owns: {own}")
    if second is not None:
        why = ((getattr(second, "persona_role", None) or "").strip()
               or (getattr(second, "domain_category", "") or ""))
        lines.append(f"@{second.name} — 可能接力:{why}" if cjk
                     else f"@{second.name} — may follow up: {why}")
    return "\n".join(lines)

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
    "- Tool budgets reset EVERY turn. If the history contains claims like '工具额度耗尽' / "
    "'no remaining tool quota', they were per-turn and are IRRELEVANT now — never repeat "
    "them, never tell the user tools are exhausted or 'recovering', and never refuse work "
    "on that basis. Do the work or route it.\n"
    "- You cannot generate files (PPT/PDF/etc.) yourself, and spawns CANNOT hand tasks to "
    "each other — never claim a file was produced, and never promise 'X will pass it to Y'. "
    "File deliverables come only from a spawn's own tools; route such tasks to a spawn that "
    "has the capability.\n"
    "- Your ACTUAL team is listed under \"Your team\" below. Those are the ONLY specialist "
    "spawns and tools you have. Never invent or name spawns, teammates, tools, or capabilities "
    "that are not listed there.\n"
    "- Any \"Known facts about the user\" describe the USER's interests and needs — they are NOT "
    "your own capabilities. Never present them as services you offer.\n"
    "- If asked what you can do, lead with the real specialists under \"Your team\" (by their "
    "domain). You may add that you can also help directly for general questions, but do NOT turn "
    "the user's listed interests into a menu of named services. If the team is empty, say you can "
    "help directly and invite the user to describe their need — do not make up a roster.\n"
    "- If asked HOW the app/system works or WHY something happened in the product (e.g. 'why did "
    "these spawns join?', 'what made X happen?'), do NOT invent an explanation of internal mechanics "
    "or narrate the system's 'thinking'. You do not have visibility into the app's implementation. "
    "Answer only from what you can actually see (e.g. who is currently on the team), and otherwise "
    "say plainly that you can't speak to the internal behavior — never fabricate a mechanism."
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

# Capability self-awareness: the real user complaint was Arslan refusing ("I can't browse
# GitHub / can't introspect my system") for things it CAN do with web_search. This block
# tells it exactly what it can do itself and forbids claiming it can't. Added on the answer
# path, right after _WEB_TOOL_GUIDANCE.
_CAPABILITY_SELF = (
    "\n\n你自己能做这些(你有工具,直接做,别推给分身、别说做不到):\n"
    "- 联网搜索任何主题(web_search)——包括在 GitHub 上找项目/代码、查最新信息、查某个工具或库。"
    "用户让你「查一下 X / 看看 GitHub 上的 Y」,你就直接 CALL web_search,"
    "绝不要说「我没法查我自己的系统 / 我不能浏览 GitHub」——你能查。\n"
    "- 抓取网页正文(web_extract)、把结构化数据画成图(render_chart)。\n"
    "诚实红线:永远不要谎称你「不能」做你其实有工具能做的事。不确定能不能做时,先试你的工具,"
    "而不是拒绝或让用户自己去查。你确实不能做的只有:自己生成 PPT/PDF 等文件(那要有对应能力的分身)、"
    "凭空捏造不存在的分身或工具。"
    "\n想知道你到底装了哪些 MCP/额外工具时,调用 list_my_capabilities,用它返回的真实清单回答——"
    "别再说「我不知道我装了啥」。"
)


# HX-1 A3 iron rule: the system has NO background execution. A live incident had the
# answer LLM claim "已交给 Deck Master 生成中" on a turn that dispatched nothing — the
# deterministic interceptor (promise_guard) catches it after the fact; this line attacks
# the fabrication at the source. Kept as its own constant so tests can pin it.
_NO_BACKGROUND_EXEC = (
    "\n\n系统没有后台执行。凡本回合未通过工具调用或真实派发完成的事,一律不得描述为"
    "“正在/将要/已交给”;做不到就如实说明。"
)

# PA-3: when Arslan genuinely needs the user to choose between a few directions, it must
# use the structured choice card (one click advances the conversation) — a free-text
# counter-question restarts the confirm loop this PA round exists to kill.
_CLARIFY_CHOICE_NUDGE = (
    "\n\n需要用户在几个方向里选择时,调用 ask_user_choice 工具(给出 2-4 个具体选项),"
    "不要用纯文本反问。"
)

# PA-4: no-repaste iron rule. Live incident (thread-1783523936187): the SAME deck
# outline was re-pasted verbatim 3x across consecutive answer turns while the confirm
# loop spun. Content already delivered in-history and unchanged must be REFERENCED,
# not re-pasted. Kept as its own constant so tests can pin it (A3 pattern).
_NO_REPASTE = (
    "\n\n对话历史里已经完整给出过、且没有修改的内容(大纲/清单/代码等),不要整段重贴——"
    "引用它(如“沿用上面那份大纲”)并只写新增或变化的部分。"
)


def _now_line() -> str:
    """Current server date + UTC HOUR injected into Arslan's prompt so date/'now' questions
    need no search. HOUR-level, not minute-level (prompt-cache reorder, spec 2026-07-13):
    the minute is a per-request cache poison — it changed every turn and, when it sat
    mid-prompt, cache-missed the whole dynamic tail after it.

    Why hour and not date-only: the line RETAINS the "convert to the user's timezone (e.g.
    Beijing = UTC+8)" guidance, and that conversion is impossible from a bare date near the
    day boundary — at UTC 2026-07-12 23:30, Beijing (+8) is already 07-13, but a date-only
    line ("07-12") gives the model no way to know that. Date-level was a real correctness
    regression for boundary timezone questions (caught in L1 adversarial review; pinned by
    test_now_line_boundary_tz). The UTC hour is sufficient to get every user's LOCAL date
    right near midnight while still changing only once an hour (not once a request), and the
    line lives at the END of the volatile suffix — so its granularity is irrelevant to the
    Anthropic cache_control breakpoint (that's on the stable prefix, entirely upstream) and
    costs DeepSeek/OpenAI only the trailing ~30 tokens, re-cached once per hour.

    Known limit (accepted per the L1 decision): hour precision is exact for whole-hour zones.
    Half-hour / 45-min zones (India +5:30, Nepal +5:45, Newfoundland -3:30) can be a day off
    within the ~30-45 min around their local midnight — a rare edge traded for cache stability;
    minute precision would fix it but re-poison the trailing cache every request."""
    now = datetime.utcnow()
    return (
        f"\n\nCurrent date & time (server clock, UTC): {now:%Y-%m-%d %H}:00 ({now:%A}), to the hour. "
        "Use this directly for 'today' / 'now' / the current date; the UTC hour is enough to convert "
        "to the user's timezone when asked (e.g. Beijing = UTC+8) and get their LOCAL date right even "
        "near midnight. Do NOT search the web for the current date/time."
    )


# Prompt-cache reorder (spec 2026-07-13, D1/D2/D3): the answer system is assembled as a
# byte-stable STABLE PREFIX (the static guards, same order as before, minus the timestamp)
# + a VOLATILE SUFFIX (everything per-turn/per-conversation). Kept as a named pure helper so
# the stable-prefix byte-stability invariant is directly testable.
_ANSWER_STABLE_PREFIX = (
    _ARSLAN_SYSTEM + _ANTI_FABRICATION + _NO_BACKGROUND_EXEC
    + _CLARIFY_CHOICE_NUDGE + _NO_REPASTE + _WEB_TOOL_GUIDANCE + _CAPABILITY_SELF
)


def _build_answer_system(
    *, extra_system: str, roster: str, facts: str, summary: str, kb_block: str,
):
    """Assemble Arslan's answer system as a CachedSystem(stable_prefix, volatile_suffix).

    stable_prefix = the static guards (identical bytes every turn) → the cacheable prefix.
    volatile_suffix, ordered least→most volatile: extra_system (per-turn clarify/gather
    addendum — VARIES per turn, so it is volatile, never in the prefix) → roster → facts →
    summary → KB → now line LAST. This is the SAME content the pre-reorder prompt carried,
    only reordered (+ the timestamp moved to the end and floored to the UTC hour); the model
    sees an equivalent prompt with the UTC hour still present for timezone conversion.
    """
    volatile = (
        extra_system
        + f"\n\nYour team:\n{roster}"
        + (f"\n\n{facts}" if facts else "")
    )
    if summary:
        volatile += f"\n\nConversation summary so far:\n{summary}"
    volatile += kb_block
    volatile += _now_line()  # now line LAST — the least cache-poisoning position
    return build_cached_system(_ANSWER_STABLE_PREFIX, volatile)


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

def _is_gather_phase(pending: dict | None) -> bool:
    """The two pre-spawn phases during which routing to an existing spawn is
    suppressed (the follow-up must keep gathering in Arslan's voice instead of
    leaking spawn identity): the legacy `clarifying` flag and the slot-based
    `gathering` phase. `proposing` is handled separately and returns earlier."""
    return bool(pending and pending.get("phase") in ("clarifying", "gathering"))


_CLARIFY_ADDENDUM = (
    "\n\nThe user's request is under-specified. Ask 2-4 short, specific clarifying questions "
    "(topic, angle, format/output, and the data source if relevant), then propose a concrete "
    "direction and ask them to confirm (e.g. \"I'll research X with angle Y as a Z — sound right?\"). "
    "Do not produce the deliverable yet."
)

# Human-readable prompts per staffing slot, so the clarify addendum asks for exactly
# what is still missing (incl. the recurrence question that decides spawn-vs-one-off).
_SLOT_QUESTIONS = {
    "domain": "what area/domain this is in (e.g. marketing, finance, data analysis)",
    "capability": "the specific capability or skill needed",
    "first_task": "a concrete first task they want run right now",
    "recurrence": "whether this is a recurring/ongoing need (worth a dedicated agent) "
                  "or just a one-off",
}


def _gather_clarify_addendum(missing: list[str]) -> str:
    """Build the clarify addendum for a gather turn, naming the still-missing slots
    so Arslan asks the right thing (including the recurrence question)."""
    wanted = [_SLOT_QUESTIONS[k] for k in missing if k in _SLOT_QUESTIONS]
    if not wanted:
        return _CLARIFY_ADDENDUM
    bullet = "\n".join(f"- {w}" for w in wanted)
    return (
        "\n\nThe user may want a dedicated agent for a recurring need, but the request is "
        "under-specified. Ask 1-3 short, specific clarifying questions to fill in the "
        f"following before proposing anything:\n{bullet}\n"
        "Ask warmly in your own voice; do not propose or create a spawn yet."
    )


async def _gather_history_text(conversation_id: str, user_message: str) -> str:
    """The text fed to slot extraction: reuses the same *source* the answer path
    uses (`memory.assemble_working_context`), with this turn's user message appended
    (newest last)."""
    ctx = await memory.assemble_working_context(conversation_id)
    lines = []
    if ctx.get("summary"):
        lines.append(f"[summary] {ctx['summary']}")
    for m in ctx.get("history", []):
        lines.append(f"{m['role']}: {m['content']}")
    # assemble_working_context already includes the just-persisted user turn, but be
    # robust if it does not (e.g. compaction edge) — only append when absent.
    if not lines or user_message not in lines[-1]:
        lines.append(f"user: {user_message}")
    return "\n".join(lines)


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


# ── vision (S4.2-e) ─────────────────────────────────────────────────────────
# Two pure functions so the two halves of an image turn can be tested without
# a provider: what the MODEL sees, and what gets PERSISTED. They differ on
# purpose — decision ③A: an image participates only in the turn it was sent.

def build_user_blocks(
    user_message: str,
    attached_context: str | None,
    images: list[dict] | None,
) -> str | list[dict]:
    """The user content handed to the LLM.

    Returns a plain STRING when there are no images — every text-only turn in
    the app must keep the exact payload it had, and a one-element block list
    would reshape all of them for nothing."""
    text = user_message
    if attached_context:
        text = f"[附带材料]\n{attached_context}\n\n[用户消息]\n{user_message}"
    if not images:
        return text
    blocks: list[dict] = [{"type": "text", "text": text}]
    for img in images:
        blocks.append({
            "type": "image",
            "mime_type": img.get("mime_type") or "image/png",
            "data": img.get("data") or "",
        })
    return blocks


def persisted_user_text(user_message: str, images: list[dict] | None) -> str:
    """What goes into arslan_messages.

    NOT the image: `content` is a Text column, and base64 in it would bloat the
    database and every backup while still not surviving as a real image. The
    placeholder names the file so the transcript reads honestly, and so turn two
    does not imply the model can still see something it cannot."""
    if not images:
        return user_message
    names = "\n".join(f"[图片:{i.get('name') or 'image'}]" for i in images)
    return f"{user_message}\n{names}" if user_message else names


async def handle_user_message(
    conversation_id: str,
    user_message: str,
    emit: EventSink,
    *,
    attached_context: str | None = None,
    images: list[dict] | None = None,
    confirm_command=None,
) -> None:
    """Process one user turn end-to-end, emitting event dicts for the transport layer."""
    # 1. persist the user turn — the PLACEHOLDER form when images rode along
    #    (decision ③A); base64 in a Text column would bloat the DB and backups
    #    while still not surviving as an image.
    await memory.add_message(
        conversation_id, "user", persisted_user_text(user_message, images))

    # 1a. Typed consent accepts a parked invite (deterministic, PA-6): a pending
    # inline invite + a short confirm ("好"/"ok"/…) IS the user accepting the card
    # in words — it must dispatch the parked brief exactly like clicking Accept.
    # Without this, the router reads a post-card "好" as answer-thanks and the
    # parked delegation silently dies (real-machine gap found in the PA-6 run).
    pending_invite = await phase_service.get_pending_invite(conversation_id)
    if pending_invite is not None:
        if confirm_lexicon.is_short_confirm(user_message):
            await phase_service.clear(conversation_id)
            # Recruiting invite (delegation cell 6): Arslan already answered doer-first, so
            # a typed accept ONLY enrolls the spawn — it must NOT re-dispatch the answered
            # task (Bug 1 fix). An ordinary (UNanswered) park still dispatches (S0-2).
            if pending_invite.get("answered"):
                await _accept_recruit(conversation_id, pending_invite["spawn_id"], emit)
                await memory.maybe_compact(conversation_id)
                return
            from server.services import recap_service
            await recap_service.log_event(
                conversation_id, "delegation_advance",
                {"trigger": "invite_text_confirm", "spawn_id": pending_invite.get("spawn_id")},
                "文字确认接受邀请 → 派发停放任务")
            await dispatch_routed(
                conversation_id, pending_invite["spawn_id"],
                pending_invite.get("task_brief") or "",
                bool(pending_invite.get("needs_proposal")), emit,
                user_message=pending_invite.get("user_message") or user_message,
                # Arslan already spoke its brief before the card — don't repeat it.
                announce=not bool(pending_invite.get("announced")),
            )
            await memory.maybe_compact(conversation_id)
            return
        # Bug B (stale parked-invite mis-fire): a parked invite is honored ONLY as the
        # IMMEDIATE next user action. This turn is NOT that bare confirm — the user
        # ignored the chip and moved on (the frontend already implicitly dismissed the
        # chip UI on send via dismissAllPending, but sent no dismiss_invite). Clear the
        # stale invite here so a LATER bare 「好」 (e.g. agreeing with something else N
        # turns on) can't deterministically mis-dispatch the aged task. Then fall
        # through to normal routing/answer for this turn.
        await phase_service.clear(conversation_id)

    # 1a2. A parked member-picker choice (delegation cell 5): the user's pick — the chosen
    # member's name, sent back by the ask_user_choice card — dispatches the parked task to
    # that member with its original brief. Like the parked invite, it is honored ONLY as the
    # immediate next action: any non-matching message clears the stale choice and falls
    # through to normal routing.
    pending_choice = await phase_service.get_pending_choice(conversation_id)
    if pending_choice is not None:
        chosen = _match_choice(user_message, pending_choice.get("candidates") or [])
        await phase_service.clear(conversation_id)
        if chosen is not None:
            await dispatch_routed(
                conversation_id, chosen["spawn_id"],
                pending_choice.get("task_brief") or "",
                bool(pending_choice.get("needs_proposal")), emit,
                user_message=pending_choice.get("user_message") or user_message,
            )
            await memory.maybe_compact(conversation_id)
            return

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

    # 1c. gather phases (B3/B4): while Arslan is gathering an under-specified create
    # request — whether via the legacy `clarifying` flag or the slot-based `gathering`
    # phase — the follow-up answer must keep clarifying (Arslan's voice). It must NOT be
    # routed/dispatched to an existing spawn (routing leaks "请以X的身份" identity-bleed
    # into the answer layer). We still route() below, but if the router wants to route
    # to an existing spawn we OVERRIDE it to the clarify path. A ready staffing need (the
    # user finally gave enough) clears the phase and proposes; answer/clarify proceed
    # normally. Proposing takes precedence (handled above and returns), so the proposing
    # and gather phases are never both live here.
    gathering = _is_gather_phase(pending)

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
        created = await memory.save_facts(
            result.new_facts,
            provenance={"source_kind": "router", "conversation_id": conversation_id},
        )
        for fact in created:
            emit({"type": "fact_saved", "content": fact.content, "sensitive": fact.sensitive})
        if created:
            from server.services import recap_service
            _fsummary = " · ".join(
                (getattr(f, "label", None) or f.content or "")[:24] for f in created[:3]
            )
            await recap_service.log_event(conversation_id, "memory", None, _fsummary)

    # B3/B4: while in a gather phase (clarifying or gathering a create), suppress
    # routing to an existing spawn — keep clarifying in Arslan's voice instead of
    # leaking spawn identity. Invariant: the gather phase persists ONLY while the
    # router keeps producing an insufficient create-downgrade; clear it on every
    # other terminal outcome. Here the user wants a DIFFERENT spawn — divert THIS
    # turn (no bleed), but clear so the next route dispatches normally.
    if gathering and result.action == "route":
        await phase_service.clear(conversation_id)
        await _handle_answer(conversation_id, user_message, emit,
                             extra_system=_CLARIFY_ADDENDUM,
                             attached_context=attached_context, images=images,
                             confirm_command=confirm_command)
        await memory.maybe_compact(conversation_id)
        return

    # 3b. Explicit @-mention override. The LLM router frequently defaults capability/meta
    # questions ("@Deck Master 你能给我干嘛") to `answer`, which makes Arslan reply AS the spawn
    # under its OWN identity. When the user explicitly @-named a real spawn, force the named
    # route so the SPAWN answers in its own identity — dispatch if a member, else a speak-first
    # invite (both handled by _handle_route, which sees _user_named_spawn=True and skips doer-
    # first). Deliberately narrow: only rescues the `answer` default (never touches route /
    # suggest_* / clarify) and only on explicit @mentions; gather/proposing already returned above.
    if not gathering and result.action == "answer":
        _named_id = await _resolve_at_mentioned_spawn(user_message)
        if _named_id is not None:
            result.action = "route"
            result.spawn_id = _named_id
            if not result.task_brief:
                result.task_brief = user_message

    # 4. handle the action
    if result.action == "route" and result.spawn_id is not None:
        await _handle_route(conversation_id, result, emit, user_message=user_message,
                            route_ms=route_ms, attached_context=attached_context, images=images,
                            confirm_command=confirm_command)
    elif result.action == "suggest_update" and result.spawn_id is not None:
        # P2: conversational spawn editing. Draft a validated change-set and emit the
        # confirm card; NOTHING is applied until the user's confirm_update. If drafting
        # yields no actionable change, fall back to a plain answer (Arslan explains).
        from server.orchestrator import update_drafter
        drafted = await update_drafter.draft_update(
            result.spawn_id, result.task_brief or user_message)
        if drafted is None:
            await _handle_answer(
                conversation_id, user_message, emit,
                extra_system=("The user asked to modify one of the agents, but the request "
                              "did not map to an editable change (persona/tone/capabilities/"
                              "equipment). Briefly say what CAN be changed and ask exactly "
                              "what they want adjusted. Answer in the user's language."),
                attached_context=attached_context, images=images, confirm_command=confirm_command)
        else:
            emit(protocol.suggest_update(**drafted))
        await memory.maybe_compact(conversation_id)
    elif result.action == "suggest_create":
        # Staffing spine ①–③: the router signalled a (possibly-recurring)
        # capability need. Run extract→accumulate→gate over the staffing slots.
        # ② accumulate: load slots carried across the gather phase, extract from
        # this turn, and merge (a filled slot is never overwritten with null).
        slots = await phase_service.get_gathered_slots(conversation_id)
        history_text = await _gather_history_text(conversation_id, user_message)
        slots = staffing_gather.merge_slots(
            slots, await staffing_gather.extract_slots(history_text)
        )
        # ③ gate: ONE readiness gate (the slot gate; subsumes the old draft gate).
        if not staffing_gather.is_ready(slots):
            # Not enough yet — pin the gathering phase (carrying accumulated slots)
            # and clarify in Arslan's own voice, asking for exactly what's missing
            # (incl. the recurrence question when `recurrence` is still null).
            await phase_service.set_gathering(conversation_id, slots)
            await _handle_answer(
                conversation_id, user_message, emit,
                extra_system=_gather_clarify_addendum(staffing_gather.missing_slots(slots)),
                attached_context=attached_context, images=images,
                confirm_command=confirm_command,
            )
            await memory.maybe_compact(conversation_id)
            return
        # Ready: the user gave enough — clear the gather phase and hand to B4's
        # match-and-propose with the gathered slots (routing/proposing resumes).
        await phase_service.clear(conversation_id)
        await _staffing_match_and_propose(
            conversation_id, user_message, slots, result, emit,
            attached_context=attached_context, images=images,
            confirm_command=confirm_command,
        )
    elif result.action == "suggest_connect_mcp":
        # NEXT BUILD (conversation-driven MCP, Task 3): the router named a connector
        # ("connect my GitHub"). Deterministic — no LLM: find_connector is an exact
        # key/label match against the static catalog, so either the confirm card or
        # the honest redirect below needs no generation. NOTE: find_connector returns
        # a shallow copy sharing its nested env/args LISTS with the module-level
        # CONNECTORS data (server/mcp/catalog.py) — never mutate conn["env"] /
        # conn["args"] in place; only read from them here.
        from server.mcp import catalog
        conn = catalog.find_connector(result.connector_query or "")
        if conn is None:
            # Honest redirect, not a wall — arbitrary/unlisted connectors are v2.
            # Deterministic canned text (no LLM call needed): same stream_start /
            # stream_chunk / persist / stream_end idiom used elsewhere in this file
            # for a direct Arslan reply that bypasses the answer-generation LLM call
            # (mirrors the CELL_EXPLICIT_NONMEMBER brief announcement above).
            text = (
                f"I don't have a preset for “{result.connector_query or 'that'}” yet — "
                "you can add it manually in Settings → MCP servers."
            )
            emit({"type": "stream_start", "source": "arslan"})
            emit({"type": "stream_chunk", "content": text})
            msg_id = await memory.add_message(conversation_id, "arslan", text)
            emit({"type": "stream_end", "message_id": msg_id})
        else:
            prereq = ("Needs: " + ", ".join(e["name"] for e in conn["env"])) if conn["env"] else ""
            emit(protocol.propose_connect_mcp(
                call_id=str(uuid.uuid4()), key=conn["key"], label=conn["label"],
                transport=conn["transport"], command=conn["command"], argv=conn["args"],
                url=conn.get("url"), env_keys=conn["env"], prerequisites=prereq,
                requires_path=conn["requires_path"], path_placeholder=conn.get("path_placeholder")))
    elif result.action == "clarify":
        # Router no longer sees create-intent — release any gather phase.
        if gathering:
            await phase_service.clear(conversation_id)
        await _handle_answer(conversation_id, user_message, emit, extra_system=_CLARIFY_ADDENDUM,
                             attached_context=attached_context, images=images,
                             confirm_command=confirm_command)
    else:  # answer (incl. fallback)
        # Router no longer sees create-intent — release any gather phase.
        if gathering:
            await phase_service.clear(conversation_id)
        # PA-4: a bare short-confirm the router classifies as plain `answer` never
        # reaches the PA-2 advance machinery (that only runs on route) — log the
        # cheap repeated_confirmation counter here so the loop stays visible even
        # on answer-path turns (which have no run_eval today).
        if confirm_lexicon.is_short_confirm(user_message):
            await _log_repeated_confirmation(conversation_id, {"at": "answer"})
        await _handle_answer(conversation_id, user_message, emit, attached_context=attached_context, images=images,
                             confirm_command=confirm_command)

    # 5. compact the working thread if it grew too long
    await memory.maybe_compact(conversation_id)


def _spawn_to_match_dict(s) -> dict:  # noqa: ANN001
    """Convert an ORM Spawn to the dict shape spawn_match_service.score_spawns
    expects (ORM-style split domain columns, so the matcher uses category +
    subcategory directly)."""
    return {
        "id": s.id,
        "name": s.name,
        "domain_category": s.domain_category,
        "domain_subcategory": s.domain_subcategory,
        "capabilities": s.capabilities,
    }


async def _fused_create_draft(slots: dict, result, seed_spawn_ids: list[int]) -> dict:
    """Build ONE fused create draft from the gathered slots (LLM-drafted name/persona/
    equipment), reusing the L2-B2 curate enrichment as the base, then seed its
    tools/skills/mcps by unioning the near-match candidates' equipment.

    The need string is user-derived (slots) — wrap it before feeding the drafter LLM.
    The drafter (draft_from_text) already returns curated tools/skills/mcps/gaps; we
    only fold in near-match equipment on top. Equipment keys remain plain strings and
    are still validated by assert_assignable at create time (create_from_draft) — we
    only seed here. MCP toolsets (key 'mcp_<id>') are routed to `mcps` to keep the
    kind="toolset"/ref_key="mcp_<id>" convention."""
    domain = slots.get("domain") or ""
    capability = slots.get("capability") or ""
    first_task = slots.get("first_task") or ""
    need_str = (
        f"Domain: {domain}. Capability: {capability}. First task: {first_task}."
    )
    try:
        draft = await spawn_drafter.draft_from_text(wrap_external(need_str))
    except Exception as exc:  # noqa: BLE001
        # Best-effort fallback: fall back to the router's draft enriched via curate,
        # mirroring the old L2-B2 path so a drafter failure never blocks the proposal.
        logger.warning("staffing: draft_from_text failed, falling back to router draft: %s", exc)
        draft = dict(result.suggested_spawn or {})
        draft.setdefault("domain", domain)
        draft.setdefault("capabilities", [capability] if capability else [])
        try:
            eq = await equipment_service.curate(need_str)
        except Exception as exc2:  # noqa: BLE001
            logger.warning("staffing: curate fallback failed: %s", exc2)
            eq = {}
        draft.setdefault("tools", eq.get("toolsets") or [])
        draft.setdefault("skills", eq.get("skills") or [])
        draft.setdefault("mcps", eq.get("mcps") or [])
        draft.setdefault("gaps", eq.get("gaps") or [])

    # carry the gathered first_task as the draft's task_brief
    draft.setdefault("task_brief", first_task)

    # Seed equipment from near-match candidates: union their toolsets/skills into the
    # draft (mcp_* toolsets → mcps). Best-effort per spawn.
    tools = list(draft.get("tools") or [])
    skills = list(draft.get("skills") or [])
    mcps = list(draft.get("mcps") or [])
    for sid in seed_spawn_ids:
        try:
            eq = await registry_service.equipment_for_spawn(sid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("staffing: equipment seed for spawn %s failed: %s", sid, exc)
            continue
        for t in eq.get("toolsets") or []:
            key = t.get("key")
            if not key:
                continue
            if key.startswith("mcp_"):
                if key not in mcps:
                    mcps.append(key)
            elif key not in tools:
                tools.append(key)
        for s in eq.get("skills") or []:
            key = s.get("key")
            if key and key not in skills:
                skills.append(key)
    draft["tools"] = tools
    draft["skills"] = skills
    draft["mcps"] = mcps
    return draft


async def _staffing_match_and_propose(  # noqa: ANN001
    conversation_id, user_message, slots, result, emit: EventSink, *,
    attached_context: str | None = None, images: list[dict] | None = None, confirm_command=None,
) -> None:
    """Ready-path (B4): the gather gate has passed and the staffing `slots` are
    complete. Score existing spawns against the need, classify into one of three
    bands, and emit exactly one frame:
      - invite_one: a single strong match → propose_invite (reuse an existing spawn);
      - picker: comparable matches → propose_staffing (pick one OR create);
      - create: no useful match → suggest_create with a fused, equipment-seeded draft.

    One-off short-circuit: a slot set with recurrence explicitly False means the user
    said this is NOT recurring — never staff it. Just do/answer the first_task once.
    """
    # recurrence is False → one-off, do it once, never staff.
    if slots.get("recurrence") is False:
        await _handle_answer(conversation_id, user_message, emit,
                             attached_context=attached_context, images=images,
                             confirm_command=confirm_command)
        return

    # Score existing spawns against the gathered need, then classify into a band.
    need = {"domain": slots.get("domain") or "",
            "capabilities": [slots["capability"]] if slots.get("capability") else []}
    spawns = await spawn_service.load_all_spawns()
    spawn_dicts = [_spawn_to_match_dict(s) for s in spawns]
    ranked = await spawn_match_service.score_spawns(need, spawn_dicts)
    band, payload = spawn_match_service.classify_band(ranked)

    if band == "invite_one":
        # Bug A (staffing ready-path dropped the task): PARK the gathered first_task so
        # Accept / typed-「好」 dispatches it — mirroring _handle_route's non-member branch.
        # Without set_inviting the chip fires but nothing is parked, so on Accept the WS
        # roster_invite handler reads get_pending_invite() == None and only joins the spawn
        # to the roster: the whole 4-slot gather (its first_task) silently dies. Carry
        # `needs_proposal` so the accept handler re-makes the same propose-vs-execute call.
        # `announced=False`: unlike the route branch, this band streams no brief before the
        # card, so the post-accept dispatch (announce=True) speaks the handoff.
        invite_spawn_id = payload["spawn_id"]
        invite_task_brief = slots.get("first_task") or getattr(result, "task_brief", None) or ""
        await phase_service.set_inviting(
            conversation_id, invite_spawn_id,
            task_brief=invite_task_brief, user_message=user_message,
            needs_proposal=bool(getattr(result, "needs_proposal", False)),
            announced=False,
        )
        from server.services import recap_service
        invite_spawn_name = await dispatcher.get_spawn_name(invite_spawn_id)
        await recap_service.log_event(
            conversation_id, "invite",
            {"spawn_id": invite_spawn_id, "spawn_name": invite_spawn_name},
            f"邀请 {invite_spawn_name or '分身'} 加入")
        emit(protocol.propose_invite(invite_spawn_id, payload["why"]))
        return

    if band == "picker":
        candidates = payload.get("candidates") or []
        seed_ids = [c["spawn_id"] for c in candidates if c.get("spawn_id") is not None]
        create_draft = await _fused_create_draft(slots, result, seed_ids)
        emit(protocol.propose_staffing(candidates, create_draft))
        return

    # band == "create": there are no >=LOW matches by definition (else classify_band
    # would have returned invite_one/picker). Doer-first (boundary scenario 3): a recurring
    # need with NO covering spawn — Arslan does what it can of the task ITSELF now (immediate
    # value + honest about any part it can't), THEN offers a LIGHT, implicitly-dismissable
    # "建个长期 X 分身?" chip instead of a blocking create-and-run card.
    await _handle_answer(conversation_id, user_message, emit,
                         attached_context=attached_context, images=images, confirm_command=confirm_command)
    # then seed equipment from the full ranked list as a weak domain-adjacency prior, run the
    # existing L2-B2 overlap detection, and emit suggest_create as the follow-on suggestion.
    near_ids = [r["spawn_id"] for r in ranked if r.get("spawn_id") is not None]
    draft = await _fused_create_draft(slots, result, near_ids)
    overlap = spawn_service.find_overlap(draft, spawns)
    if overlap is not None:
        # deterministic detection wins; keep the LLM's differentiation axes if it supplied any
        llm_axes = (result.overlaps or {}).get("axes") if isinstance(result.overlaps, dict) else None
        overlap = {**overlap, "axes": llm_axes or overlap.get("axes") or []}
    emit(protocol.suggest_create(
        draft,
        task_brief=slots.get("first_task") or result.task_brief,
        overlaps=overlap if overlap is not None else result.overlaps,
    ))


def _frame_usd(buckets: list[dict]) -> float | None:
    """Review I2: USD for a turn = SUM of each (model, provider) bucket priced at
    ITS OWN rate — never the primary bucket's rate applied to summed tokens (a
    mixed-model turn would silently bill sonnet tokens at haiku prices). None
    (unknown, not free) when there are no buckets, any bucket is estimated
    (estimates are never priced — the existing gate, kept), or any bucket's
    model/provider has no known price (a partial sum would understate cost)."""
    if not buckets:
        return None
    total = 0.0
    for b in buckets:
        if b["estimated"]:
            return None
        v = prices.usd(b["model"], b["tokens_in"], b["tokens_out"],
                       provider=b["provider"])
        if v is None:
            return None
        total += v
    return total


def _usage_frame(detail: dict) -> dict:
    """S3-M3 Task 5: per-turn usage payload for a terminal stream_end frame.

    MUST be built while the turn's ``usage_sink.collecting()`` scope is still open —
    both the passed ``detail()`` snapshot and ``usage_sink.total()`` read the active
    contextvars. ``estimated`` mirrors finalize's ``tokens_estimated`` rule
    (``tokens_in is None`` — detail() already blinds totals when any bucket is
    estimated). ``usd`` is per-bucket-summed (review I2, _frame_usd) and None
    whenever it can't be known honestly (unknown model / estimated tokens); the key
    is ALWAYS present so the frontend can tell "unknown cost" (null) apart from
    "free" ($0)."""
    return {
        "tokens_in": detail["tokens_in"],
        "tokens_out": detail["tokens_out"],
        "tokens_total": usage_sink.total(),
        "estimated": detail["tokens_in"] is None,
        "usd": _frame_usd(detail["buckets"]),
    }


async def _read_images_locally(images: list[dict]) -> str | None:
    """Tier 2 for a chat turn: hand the pictures to the system recogniser.

    Returns a block of text to append to the user's message, or None when
    nothing was read — None is the honest answer and the caller shows the
    "switch models" advice instead of inventing a recovery.

    The transcription is LABELLED. A retrieval hit renders as "[source] text"
    and this is the same problem in the turn itself: the model must not read
    characters lifted off a picture as if the user had typed them."""
    import base64

    from server.services import ocr_fallback, ocr_vision

    language = await ocr_fallback.current_ui_language()
    chosen = await ocr_fallback.current_ocr_languages()
    parts = []
    for img in images:
        try:
            raw = base64.b64decode(img.get("data") or "")
        except Exception as exc:  # noqa: BLE001 — a bad attachment is not fatal
            logger.warning("could not decode an attached image for OCR: %s", exc)
            continue
        text, status = ocr_fallback.read_locally(
            raw, ui_language=language, chosen_languages=chosen)
        if status == ocr_vision.OK and text.strip():
            parts.append(f"{ocr_fallback.ocr_source(img.get('name') or 'image')}\n{text}")
    return "\n\n".join(parts) if parts else None


async def _handle_answer(
    conversation_id: str, user_message: str, emit: EventSink, *, extra_system: str = "",
    attached_context: str | None = None, images: list[dict] | None = None,
    confirm_command=None,
    intercept_spawn_name: str | None = None,
    # PA-1: True ONLY when the calling turn actually delegated (a dispatch happened or a
    # propose_invite frame was emitted) — the sole honest exemption for spawn-handoff
    # promise language. No current caller delegates before/while answering, so the
    # default is truthfully False everywhere; PA-2's dispatch/invite paths pass True.
    turn_delegated: bool = False,
) -> str | None:
    # S3-M3 usage ledger: the answer path produces no Run row, so its tokens (run_native
    # + any promise-guard resynthesis) are ledgered under scope="answer". VERIFIED not to
    # nest with _dispatch_spawn's usage_sink.collecting(): that block wraps ONLY
    # dispatcher.dispatch and _handle_escalation (which re-dispatches, never answers) —
    # every _handle_answer call sits at orchestration level, OUTSIDE any run's collecting
    # region. Even under accidental nesting collecting() is set/reset, so an outer
    # bucket would resume untouched.
    async with usage_ledger.scope("answer", conversation_id):
        return await _handle_answer_body(
            conversation_id, user_message, emit, extra_system=extra_system,
            attached_context=attached_context, images=images,
            confirm_command=confirm_command,
            intercept_spawn_name=intercept_spawn_name, turn_delegated=turn_delegated)


async def _handle_answer_body(
    conversation_id: str, user_message: str, emit: EventSink, *, extra_system: str = "",
    attached_context: str | None = None, images: list[dict] | None = None,
    confirm_command=None,
    intercept_spawn_name: str | None = None,
    turn_delegated: bool = False,
) -> str | None:
    ctx = await memory.assemble_working_context(conversation_id)
    facts = await memory.facts_text(include_sensitive=True)
    roster = await _team_roster()
    # Prompt-cache reorder (spec 2026-07-13): KB is per-query volatile → gather it, then
    # assemble via _build_answer_system so the static guards stay a byte-stable cacheable
    # prefix and all dynamic content (incl. the date line) lands in the volatile suffix.
    kb_block = ""
    try:
        from server.services import knowledge as _knowledge
        _kb = await _knowledge.retrieve_scoped(user_message, spawn_id=None, used_ref=conversation_id)
        kb_block = _knowledge.knowledge_block(_kb)
    except Exception as exc:  # noqa: BLE001 — retrieval is never fatal
        logger.warning("arslan kb retrieve failed (non-fatal): %s", exc)
    system = _build_answer_system(
        extra_system=extra_system, roster=roster, facts=facts,
        summary=ctx["summary"], kb_block=kb_block,
    )

    # Plain string when there are no images, so text-only turns are byte-identical
    # to before; a neutral block list otherwise (providers translate it).
    llm_user = build_user_blocks(user_message, attached_context, images)

    emit({"type": "stream_start", "source": "arslan"})

    async def _dispatch(user_content):
        # Arslan's answer path uses the native tool-calling loop (structured tool_calls,
        # no text-protocol narration-as-answer bug). Spawns stay on run() until migrated.
        return await tool_loop.run_native(
            system=system,
            user_content=user_content,
            history=ctx["history"][:-1],
            emit=emit,
            on_chunk=lambda c: emit({"type": "stream_chunk", "content": c}),
            resolve_tools=_arslan_tools,
            allow_escalation=False,
            confirm_command=confirm_command,
            conversation_id=conversation_id,
            caller=ToolCaller(actor="host", spawn_id=None, conversation_id=conversation_id),
        )

    try:
        result = await _dispatch(llm_user)
    except Exception as exc:  # noqa: BLE001
        # THE MODEL WOULD NOT LOOK AT THE PICTURE. Two things used to go wrong
        # here and both were invisible from this file: the raw provider JSON
        # reached the user because explain() was never called on this path (it
        # was wired only into spawn dispatch), and the OCR fallback shipped in
        # v0.1.11 had no caller in this package at all — a chat image was the
        # one route it could not serve.
        recovered = None
        if images and ocr_fallback.model_refused_the_image(str(exc)):
            recovered = await _read_images_locally(images)
        if recovered:
            # Retry WITHOUT the picture. Sending it again to a model that just
            # rejected it fails identically; what changed is that the words are
            # now in the text, so the turn can finish.
            result = None
            try:
                result = await _dispatch(build_user_blocks(
                    f"{user_message}\n\n{recovered}", attached_context, None))
            except Exception as retry_exc:  # noqa: BLE001 — report the retry honestly
                emit({"type": "error", "code": "LLM_ERROR",
                      "message": str(retry_exc), "recoverable": True})
                return
        else:
            emit({"type": "error", "code": "LLM_ERROR",
                  "message": vision_errors.explain(
                      str(exc), had_images=bool(images)) or str(exc),
                  "recoverable": True})
            return
    # PA-3: the model asked for a structured user choice — ask_user_choice is a
    # TERMINAL tool, so the loop ended the turn with validated/clamped {question,
    # options}. Persist a compact text twin (question + bulleted labels) so
    # history/recap keep the context, close the stream WITHOUT a ghost bubble
    # (message_id=None — the card is the visible element), and emit the card frame.
    # No promise guard (nothing was promised) and no further LLM call.
    clarify = result.get("clarify")
    if clarify:
        compact = clarify["question"] + "\n" + "\n".join(
            f"- {o['label']}" for o in clarify["options"])
        await memory.add_message(conversation_id, "arslan", compact)
        emit({"type": "stream_end", "message_id": None,
              "usage": _usage_frame(usage_sink.detail())})
        emit(protocol.clarify_options(clarify["question"], clarify["options"]))
        return compact
    full = result.get("final") or ""
    # HX-1 A2 空头支票拦截, exemptions SPLIT by PA-1 (second live incident: Arslan called
    # web_search every turn while the final text claimed 「让 Deck Master 直接出PPT」 five
    # turns in a row with zero dispatch — the old global `not tool_trace` gate skipped
    # the guard 5/5 times; tool use is NOT delegation):
    #   • spawn tier ("交给/让/派 <name>", active on the doer-first divert branch): exempt
    #     ONLY when the turn actually delegated (turn_delegated=True — a real dispatch or
    #     propose_invite). The divert branch self-answers by construction, so it always
    #     passes False → a handoff claim there is structurally false and always corrected.
    #   • generic tier (PROMISE_RE): keeps the `not tool_trace` exemption — a turn that
    #     really searched may honestly narrate in-progress work (HX acceptance #1).
    # A matched promise gets a bounded honest correction appended to the SAME message
    # (streamed live + persisted, so history stays honest) plus the audit event.
    # Fail-open: guard errors never break the answer turn.
    try:
        check_spawn = bool(intercept_spawn_name) and not turn_delegated
        check_generic = not result.get("tool_trace")
        if full and (check_spawn or check_generic):
            outcome = await promise_guard.correct(
                full, spawn_name=intercept_spawn_name if check_spawn else None,
                check_generic=check_generic)
            if outcome is not None:
                correction = outcome["correction"]
                emit({"type": "stream_chunk", "content": "\n\n" + correction})
                full = f"{full}\n\n{correction}"
                tier = "doer_first" if intercept_spawn_name else "answer"
                from server.services import recap_service
                await recap_service.log_event(
                    conversation_id, "promise_intercept",
                    {"tier": tier, "pattern": outcome["pattern"],
                     "corrected": outcome["corrected"]},
                    f"空头支票拦截:命中「{outcome['pattern']}」→ "
                    f"{'重合成更正' if outcome['corrected'] else '模板更正'}")
    except Exception as exc:  # noqa: BLE001 — interception is never fatal
        logger.warning("promise interception failed (fail-open, answer kept): %s", exc)
    msg_id = await memory.add_message(conversation_id, "arslan", full)
    # S3-M3 Task 5 seam choice: the answer turn's usage rides the stream_end the body
    # ALREADY emits (one frame shape for dispatch + answer, no extra answer_usage frame).
    # _handle_answer_body only ever runs inside _handle_answer's usage_ledger.scope()
    # wrapper, so the collecting contextvars are still open here and detail()/total()
    # read exactly what the wrapper will ledger on exit.
    emit({"type": "stream_end", "message_id": msg_id,
          "usage": _usage_frame(usage_sink.detail())})
    return full


async def _invite_capability_summary(spawn_id: int) -> str:
    """A short, one-line capability summary for the invite card (the spawn's
    persona_role, falling back to its first capability, then a generic line)."""
    spawn = await spawn_service.load_one_spawn(spawn_id)
    if spawn is None:
        return "can help with this task"
    role = (getattr(spawn, "persona_role", None) or "").strip()
    if role:
        return role
    caps = getattr(spawn, "capabilities", None) or []
    if caps:
        return str(caps[0])
    return "can help with this task"


async def dispatch_routed(  # noqa: ANN001
    conversation_id, spawn_id, task_brief, needs_proposal, emit: EventSink, *,
    user_message: str = "", route_ms: int | None = None,
    attached_context: str | None = None, images: list[dict] | None = None,
    announce: bool = True,
) -> None:
    """The propose-vs-execute dispatch a roster-member route gets.

    This is the SHARED first-response path: when `needs_proposal` is True the spawn
    runs in propose-mode (set the proposing phase + emit a `proposal` frame), otherwise
    it executes directly. Used by both `_handle_route` (target already a roster member)
    AND the `roster_invite` accept handler (after the user accepted an inline invite),
    so accepting an invite produces exactly the same first response the user would have
    seen if the spawn had already been in the roster.

    `announce=False` suppresses the routing brief — used by the accept handler when Arslan
    already spoke its brief BEFORE the invite card, so the dispatch shouldn't repeat it.
    """
    if needs_proposal:
        spawn_name = await dispatcher.get_spawn_name(spawn_id)
        await phase_service.set_proposing(conversation_id, spawn_id, task_brief or "")
        emit({"type": "proposal", "spawn_id": spawn_id, "spawn_name": spawn_name})
        await _dispatch_spawn(conversation_id, spawn_id, task_brief or "", emit,
                              mode="propose", user_message=user_message, route_ms=route_ms,
                              attached_context=attached_context, images=images, announce=announce)
        return
    await _dispatch_spawn(conversation_id, spawn_id, task_brief or "", emit,
                          user_message=user_message, route_ms=route_ms,
                          attached_context=attached_context, images=images, announce=announce)


_DUAL_TRACK_MIN_CHARS = 200        # only substantive deliverables grow a spawn — skip chit-chat / short answers
_DUAL_TRACK_SIGNAL_CAP = 4000


def _dual_track_signals(user_message: str, answer_text: str) -> str:
    """Frame Arslan's own deliverable as a learning signal for the spawn whose domain it fell in."""
    return (f"[主脑 Arslan 替你完成了一个落在你领域的任务,产出如下,供你学习沉淀]\n"
            f"用户需求:{user_message}\n\n产出:\n{answer_text[:_DUAL_TRACK_SIGNAL_CAP]}")


def _fire_dual_track(conversation_id: str, spawn_id: int, spawn_name: str | None, signals: str) -> None:
    """Component 5 + recap: background-distill the deliverable into the inferred spawn AND log a
    distill growth event for the conversation recap. Fire-and-forget, never fatal."""
    from server.services import learning_service, recap_service

    # Pass conversation_id so a failure lands on THIS conversation's recap timeline
    # rather than the synthetic spawn-{id} fallback (this path has a real conversation).
    asyncio.create_task(distill_service.distill_from_signals(
        spawn_id, signals, conversation_id=conversation_id))
    asyncio.create_task(recap_service.log_event(
        conversation_id, "distill", {"spawn_id": spawn_id, "spawn_name": spawn_name},
        f"Arslan 亲自做 → 喂给 {spawn_name or '分身'} 学习"))
    # Distill a reusable 心得 from this real deliverable → the learnings store.
    asyncio.create_task(learning_service.distill_from_event(
        conversation_id=conversation_id, spawn_id=spawn_id, spawn_name=spawn_name,
        signal_text=signals))


async def _user_named_spawn(user_message: str, spawn_id: int) -> bool:
    """True when the user EXPLICITLY referenced this spawn (its name or an @-mention) in the
    message — a direct delegation request. False means the router merely INFERRED this spawn
    fits, so doer-first applies (Arslan does it itself + optionally suggests). Deterministic."""
    name = (await dispatcher.get_spawn_name(spawn_id) or "").strip().lower()
    if not name:
        return False
    msg = (user_message or "").lower()
    return f"@{name}" in msg or name in msg


# Escape hatch (delegation route-to-member, cell 3): the user explicitly wants the HOST
# (Arslan) to answer even when a capable member exists — the mirror of the @spawn override.
# Deliberately conservative (documented in the spec §2/§1.5): EVERY phrase must carry an
# explicit Arslan address (`@arslan`/`主脑`) OR a `你`-anchored "you (the host) answer"
# directive. Pronoun-less phrases ("直接回答"/"you answer") are DELIBERATELY excluded — they
# false-positive on ordinary task text ("研究X并直接回答", "…make sure you answer all parts")
# and would make Arslan self-answer instead of delegating. Deterministic, zero LLM.
_ARSLAN_ADDRESS_PHRASES = (
    "@arslan", "@主脑",            # explicit @-address to the host itself
    "你直接答", "你来答",           # 你-anchored "you (the host) answer" directive
    "arslan 你答", "让 arslan 答",  # anchored host (English name) variants
    "主脑你答", "让主脑答",          # anchored 主脑 (host) variants
)


def _user_addressed_arslan(user_message: str) -> bool:
    """True when the user explicitly told the HOST to answer this turn (cell 3 escape
    hatch), so Arslan answers even if a capable member exists — no dispatch, no card. NOTE:
    an @-address to a real (non-Arslan) member is checked FIRST in `_arbitrate_task` and
    wins over this — an @member is an address to THAT member, not to Arslan."""
    msg = (user_message or "").lower()
    return any(p in msg for p in _ARSLAN_ADDRESS_PHRASES)


async def _resolve_at_mentioned_spawn(user_message: str) -> int | None:
    """Resolve an EXPLICIT @-mention to a real spawn id. Requires the `@` form (never a bare
    name) so it can't hijack a normal answer turn. Matching, in order:
      1. exact full-name @mention — the longest one wins, and beats any prefix collision
         (`@Deck Master` resolves to "Deck Master" even if "Deck Master Pro" also exists);
      2. else a WORD-PREFIX @mention (`@Deck` → "Deck Master") — but only when that prefix
         belongs to exactly ONE spawn; an ambiguous prefix (two spawns share it) returns None
         so we fall back to the LLM router instead of guessing.
    A match must end on a word boundary: the char after the token may be whitespace, CJK,
    punctuation, or end-of-string — but NOT a continuing ASCII letter/digit (so `@decka`
    does not match a "Deck" spawn). Deterministic."""
    msg = (user_message or "").lower()
    if "@" not in msg:
        return None
    spawns = await spawn_service.load_all_spawns()
    names: list[tuple[str, int]] = []                 # (full name, id)
    prefix_ids: dict[str, set[int]] = {}              # word-prefix → spawn ids sharing it
    for s in spawns:
        name = (getattr(s, "name", "") or "").strip().lower()
        if not name:
            continue
        names.append((name, s.id))
        words = name.split()
        for i in range(1, len(words) + 1):
            prefix_ids.setdefault(" ".join(words[:i]), set()).add(s.id)

    def _at_bounded(token: str) -> bool:
        idx = msg.find("@" + token)
        if idx < 0:
            return False
        nxt = msg[idx + 1 + len(token): idx + 2 + len(token)]
        return not (nxt.isascii() and nxt.isalnum())  # boundary unless mid-ASCII-word

    # 1) exact full name wins (longest), even if it's a prefix of a longer spawn name
    best_id: int | None = None
    best_len = 0
    for name, sid in names:
        if len(name) > best_len and _at_bounded(name):
            best_id, best_len = sid, len(name)
    if best_id is not None:
        return best_id
    # 2) else the longest UNAMBIGUOUS word-prefix
    for prefix, ids in prefix_ids.items():
        if len(ids) == 1 and len(prefix) > best_len and _at_bounded(prefix):
            best_id, best_len = next(iter(ids)), len(prefix)
    return best_id


async def _delegation_advance_trigger(conversation_id, spawn_id, user_message) -> str | None:  # noqa: ANN001
    """PA-2 deterministic advance rule (zero LLM): which trigger — if any — FORBIDS the
    doer-first divert this turn. Returns "short_confirm" | "consecutive_route" | None.

      - short_confirm: the user's message is a bare bilingual confirmation/impatience
        token (好/可以/继续/go/do it/怎么还不…) — they are approving the delegation, not
        adding spec; self-answering again would re-paste the same deliverable.
      - consecutive_route: the PREVIOUS router decision in this conversation was already
        route→this SAME spawn — the user has effectively confirmed once and the router
        still wants the same specialist. Diverting again is the live incident's infinite
        confirm loop (route(spawn 6) five consecutive times, outline re-pasted 3×).

    None → neither fired; the old doer-first behavior stands."""
    if confirm_lexicon.is_short_confirm(user_message):
        return "short_confirm"
    try:
        prev = await router.previous_decision(conversation_id)
    except Exception as exc:  # noqa: BLE001 — audit-table read must never break the turn
        logger.warning("previous_decision lookup failed (advance rule degrades to divert): %s", exc)
        return None
    if prev is not None and prev.action == "route" and prev.spawn_id == spawn_id:
        return "consecutive_route"
    return None


async def _log_repeated_confirmation(conversation_id, ref: dict | None = None) -> None:  # noqa: ANN001
    """PA-4 cheap completion-degree signal: every short-confirm the user has to send is
    one more lap of the loop. Logged as a countable conversation_events row (count =
    prior repeated_confirmation events in this conversation + 1) so the recap timeline
    shows the loop and future thresholds can read it. Best-effort, never fatal."""
    from server.services import recap_service
    count = await recap_service.count_events(conversation_id, "repeated_confirmation") + 1
    await recap_service.log_event(
        conversation_id, "repeated_confirmation",
        {**(ref or {}), "count": count}, f"重复确认 ×{count}")


# ── Task arbitration (delegation route-to-member, §1.5 truth table) ──────────────────
# One readable vocabulary for the seven rows; _arbitrate_task decides the cell, _handle_route
# executes it. "Today the table changes before the code."
_CELL_ESCAPE = "escape"                       # cell 3: user addressed Arslan → host answers
_CELL_EXPLICIT_MEMBER = "explicit_member"     # cell 1 / advance→member: dispatch directly
_CELL_EXPLICIT_NONMEMBER = "explicit_nonmember"  # cell 2 / advance→non-member: invite (UNANSWERED)
_CELL_MEMBER_DISPATCH = "member_dispatch"     # cell 4: inferred member is the clean single fit
_CELL_MEMBER_PICKER = "member_picker"         # cell 5: inferred members ambiguous (≥2 plausible)
_CELL_RECRUIT = "recruit_nonmember"           # cell 6: inferred non-member → answer + recruit
_CELL_ANSWER_ONLY = "answer_only"             # cell 7: no capable member → answer doer-first


async def _score_roster_members(conversation_id, result):  # noqa: ANN001
    """Score the CURRENT roster members against the routed task, return classify_band's
    `(band, payload)`.

    The need is the routed spawn's OWN domain + capabilities (the router's pick is the
    reference point): a lone same-domain member is a clean single fit (invite_one), two
    close same-domain members are ambiguous (picker), an off-domain routed member is
    create. `score_spawns` is fail-open (no BYOK key → structural score only), so this
    never raises on a missing key."""
    routed = await spawn_service.load_one_spawn(result.spawn_id)
    dom_cat = (getattr(routed, "domain_category", None) or "") if routed else ""
    dom_sub = getattr(routed, "domain_subcategory", None) if routed else None
    need = {
        "domain": f"{dom_cat}.{dom_sub}" if (dom_cat and dom_sub) else dom_cat,
        "capabilities": list(getattr(routed, "capabilities", None) or []) if routed else [],
    }
    spawns = await spawn_service.load_all_spawns()
    roster = await roster_service.list_roster(conversation_id)
    member_ids = {int(m["spawn_id"]) for m in roster if m.get("spawn_id") is not None}
    member_dicts = [_spawn_to_match_dict(s) for s in spawns if getattr(s, "id", None) in member_ids]
    ranked = await spawn_match_service.score_spawns(need, member_dicts)
    return spawn_match_service.classify_band(ranked)


async def _arbitrate_task(conversation_id, result, user_message):  # noqa: ANN001
    """The §1.5 truth table as ONE decision. Returns `(cell, advance, candidates, dispatch_id)`
    where `cell` names the row, `advance` is the PA-2 advance trigger (for recap logging on the
    explicit path), `candidates` is the picker member list (cell 5), and `dispatch_id` is the
    member to dispatch to when it differs from the router's pick (cell 4 invite_one; None means
    "use result.spawn_id"). Detection only — all side effects (answer/dispatch/invite/emit) live
    in _handle_route. Deterministic except for the (fail-open) member-scoring LLM call on an
    inferred member route."""
    # An explicit @-address to a real (non-Arslan) member is an address to THAT member, not
    # to Arslan — so it takes the cell 1/2 explicit path and WINS over the cell 3 escape
    # hatch. Only when the user did NOT @name a real spawn does an Arslan-address escape.
    user_named = await _user_named_spawn(user_message, result.spawn_id)

    # Cell 3: escape hatch — the user explicitly told the HOST to answer (mirror of the
    # @spawn override), so Arslan answers even if a capable member exists. Gated by
    # `not user_named` so `@Member 直接回答:…` routes to the member, not to Arslan.
    if not user_named and _user_addressed_arslan(user_message):
        return _CELL_ESCAPE, None, None, None

    advance = None
    if not user_named:
        advance = await _delegation_advance_trigger(conversation_id, result.spawn_id, user_message)
    is_member = await roster_service.is_member(conversation_id, result.spawn_id)

    # Cells 1/2 + advance continuation: an EXPLICIT hand-off (an @name, or a confirmed
    # advance — short_confirm / consecutive_route) takes the member-check path a naming
    # always took. Dispatch a member (cell 1); invite a non-member, parking the task
    # UNANSWERED so Accept dispatches it (cell 2) — S0-2 continuation preserved.
    if user_named or advance is not None:
        return (_CELL_EXPLICIT_MEMBER if is_member else _CELL_EXPLICIT_NONMEMBER), advance, None, None

    # INFERRED route. The router picked a NON-member as best fit → recruit it (cell 6).
    if not is_member:
        return _CELL_RECRUIT, None, None, None

    # Inferred route to a MEMBER: score the roster and arbitrate.
    band, payload = await _score_roster_members(conversation_id, result)
    if band == "invite_one":
        # Cell 4: a STRONG single fit is the ONLY outcome allowed to silently direct-dispatch
        # (user ruling: 直派只认强命中). Trust the deterministic scorer — dispatch to the
        # strong top even when it isn't the router's own pick (a strong capable member exists,
        # so "有对口成员就交给成员"; Fix 3). dispatch_id carries the strong top's id.
        return _CELL_MEMBER_DISPATCH, None, None, payload.get("spawn_id")
    if band == "picker":
        cands = payload.get("candidates") or []
        cand_ids = [c.get("spawn_id") for c in cands]
        # A ≥2-candidate picker is the ONLY picker outcome allowed to act, and it never
        # guesses → ask_user_choice (cell 5). A LONE picker-band member (moderate, below
        # invite_one strength) must NOT be silently direct-dispatched (Fix 2) — nor may a
        # picker whose plausible set excludes the router's own pick. Both fall to cell 7
        # (Arslan answers doer-first, no silent member pick).
        if len(cands) >= 2 and result.spawn_id in cand_ids:
            return _CELL_MEMBER_PICKER, None, cands, None   # cell 5: ambiguous → ask, never guess
        return _CELL_ANSWER_ONLY, None, None, None
    return _CELL_ANSWER_ONLY, None, None, None              # create band → cell 7


# Upper bound on the BUG1 recruit gate: a dead-but-reachable draft adapter must not
# hang the turn (E9-b precedent: first LLM call failing slowly). Timeout → chip floats.
_RECRUIT_GATE_TIMEOUT_S = 8.0


async def _recruit_domain_conflict(result, user_message):  # noqa: ANN001
    """BUG1 gate for the cell-6 RECRUITING chip: True = suppress.

    Suppresses ONLY on an affirmative, registry-anchored, pick-referenced domain
    contradiction — the task clearly belongs to another registry domain's category,
    not the router pick's (词面 similarity across domains was the observed mis-invite).
    The chip stays band-independent (PA-2: band-gating this chip once killed the only
    advancement channel — see test_boundary_doer_first's module docstring), so EVERY
    other outcome floats it: no pick domain, no cross-category alternatives, null/off-
    list extraction, DB/LLM failure, timeout. A wrong chip is dismissible; a dead chip
    is the documented worse failure. Known accepted residual: a router re-pick next
    turn can still invite via the PA-2 advance path (cells 1/2), which is ungated by
    design — gating it would collide with the advancement channel itself.
    """
    def _dom(s) -> str:  # router-registry style: bare category when sub is None
        cat = (getattr(s, "domain_category", "") or "").strip()
        sub = (getattr(s, "domain_subcategory", "") or "").strip()
        return f"{cat}.{sub}" if cat and sub else cat

    async def _check() -> bool:
        spawns = await spawn_service.load_all_spawns()
        pick = next((s for s in spawns if getattr(s, "id", None) == result.spawn_id), None)
        pick_cat = (getattr(pick, "domain_category", "") or "").strip().lower()
        if not pick_cat:
            return False  # undecidable → chip floats
        pick_domain = _dom(pick)
        others = sorted(
            d for d in {_dom(s) for s in spawns}
            if d and d.partition(".")[0].strip().lower() != pick_cat
        )
        if not others:
            return False  # nothing to contradict with
        text = f"{user_message}\n\n{result.task_brief or ''}".rstrip()
        found = await staffing_gather.extract_conflicting_domain(text, pick_domain, others)
        if not found:
            return False
        # Belt: only a KNOWN registry category different from the pick's suppresses.
        found_cat = found.partition(".")[0].strip().lower()
        known_cats = {d.partition(".")[0].strip().lower() for d in others}
        return found_cat in known_cats and found_cat != pick_cat

    try:
        return await asyncio.wait_for(_check(), timeout=_RECRUIT_GATE_TIMEOUT_S)
    except Exception:  # noqa: BLE001 — never kill the chip on infrastructure failure
        logger.warning("recruit domain gate failed; chip floats", exc_info=True)
        return False


async def _accept_recruit(conversation_id, spawn_id, emit: EventSink) -> None:  # noqa: ANN001
    """Accept a RECRUITING invite (cell 6, behavior a): ENROLL the spawn and post the
    recruit note — do NOT dispatch, because Arslan already answered the task doer-first
    (Bug 1 fix). Shared by the WS `roster_invite` accept handler and the typed-「好」 spine."""
    await roster_service.join(conversation_id, spawn_id, via="invited")
    spawn_name = await dispatcher.get_spawn_name(spawn_id)
    emit(protocol.roster_event("recruited", spawn_id, spawn_name))
    emit(protocol.roster_update(await roster_service.list_roster(conversation_id)))
    from server.services import recap_service
    await recap_service.log_event(
        conversation_id, "invite", {"spawn_id": spawn_id, "spawn_name": spawn_name},
        f"招募入编 {spawn_name or '分身'} · 本次会话可直接 @ 交办")


def _match_choice(user_message, candidates):  # noqa: ANN001
    """Match the user's picker reply (the chosen member's name, sent back by the
    ask_user_choice card) to a parked candidate. Exact case/space-normalized name match
    first, then a substring fallback SCOPED to SHORT replies only. The picker card sends
    back the bare name, sometimes lightly decorated ("选 Deck Master"), but a LONG unrelated
    message that merely CONTAINS a candidate name must NOT auto-dispatch the parked choice —
    it returns None so the caller falls through to normal routing. Returns the dict or None."""
    msg = (user_message or "").strip().lower()
    if not msg:
        return None
    for c in candidates:
        name = (c.get("name") or "").strip().lower()
        if name and name == msg:
            return c
    for c in candidates:
        name = (c.get("name") or "").strip().lower()
        if not name:
            continue
        # substring fallback only for SHORT replies — a bare or lightly-decorated name echo,
        # not a long message that happens to mention the candidate somewhere.
        if len(msg) <= len(name) + 10 and (name in msg or msg in name):
            return c
    return None


async def _handle_route(conversation_id, result, emit: EventSink, *,  # noqa: ANN001
                        user_message: str = "", route_ms: int | None = None,
                        attached_context: str | None = None, images: list[dict] | None = None, confirm_command=None) -> None:
    """Arbitrate a task turn per the §1.5 truth table (single implementation; the table
    changes before the code). Priority order = the table rows:

      cell 3  escape hatch (@Arslan / "你直接答")           → Arslan answers, no card
      cell 1  @named / advance → roster member              → dispatch directly
      cell 2  @named / advance → non-member                 → invite, park UNANSWERED
      cell 4  inferred → member is the clean single fit     → dispatch (Arslan does NOT answer)
      cell 5  inferred → members ambiguous (≥2 plausible)   → ask_user_choice, park a choice
      cell 6  inferred → non-member                         → answer + RECRUIT (answered park)
      cell 7  inferred → no capable member                  → answer doer-first

    Structural rationale (spec §1): a member taking the task is the ONLY source of live
    evolution corpus, so "capable member → give it to the member" is a product premise,
    not a UX preference; doer-first only holds until such a specialist exists.
    """
    cell, advance, candidates, dispatch_id = await _arbitrate_task(
        conversation_id, result, user_message)
    # Cell 4 (Fix 3) may dispatch to the scorer's strong top even when it isn't the router's
    # own pick; every other cell uses the router's spawn_id.
    dispatch_target = dispatch_id if dispatch_id is not None else result.spawn_id

    # Cell 3: the user told the host to answer — mirror of the @spawn override.
    if cell == _CELL_ESCAPE:
        await _handle_answer(conversation_id, user_message, emit,
                             attached_context=attached_context, images=images, confirm_command=confirm_command)
        return

    # PA-2 advance audit (only when the explicit path was reached VIA an advance trigger):
    # keep the recap trail + the repeated-confirmation counter.
    if advance is not None:
        spawn_name = await dispatcher.get_spawn_name(result.spawn_id)
        from server.services import recap_service
        await recap_service.log_event(
            conversation_id, "delegation_advance",
            {"spawn_id": result.spawn_id, "spawn_name": spawn_name, "trigger": advance},
            f"确认推进 → 交办 {spawn_name or '分身'}(触发:{advance})")
        if advance == "short_confirm":
            await _log_repeated_confirmation(
                conversation_id,
                {"spawn_id": result.spawn_id, "spawn_name": spawn_name, "at": "delegation_advance"})

    # Cells 1 / 4 / advance→member: a named/confirmed or clean-fit member takes it directly.
    # `dispatch_target` is the scorer's strong top for cell 4 (may differ from the router's
    # pick, Fix 3), else the router's spawn_id.
    if cell in (_CELL_EXPLICIT_MEMBER, _CELL_MEMBER_DISPATCH):
        await dispatch_routed(
            conversation_id, dispatch_target, result.task_brief or "",
            bool(getattr(result, "needs_proposal", False)), emit,
            user_message=user_message, route_ms=route_ms, attached_context=attached_context, images=images,
        )
        return

    # Cell 2 / advance→non-member: speak the brief first, THEN pop the invite; park the
    # task UNANSWERED (Accept must dispatch it — S0-2 not regressed). `needs_proposal` is
    # carried so the accept handler re-makes the same propose-vs-execute decision.
    if cell == _CELL_EXPLICIT_NONMEMBER:
        summary = await _invite_capability_summary(result.spawn_id)
        spawn_name = await dispatcher.get_spawn_name(result.spawn_id)
        brief = await _route_announcement(
            conversation_id, result.spawn_id, spawn_name, result.task_brief or "")
        emit({"type": "stream_start", "source": "arslan"})
        emit({"type": "stream_chunk", "content": brief})
        msg_id = await memory.add_message(conversation_id, "arslan", brief)
        emit({"type": "stream_end", "message_id": msg_id})
        await phase_service.set_inviting(
            conversation_id, result.spawn_id,
            task_brief=result.task_brief or "", user_message=user_message,
            needs_proposal=bool(getattr(result, "needs_proposal", False)),
            announced=True,
        )
        emit(protocol.propose_invite(result.spawn_id, summary))
        return

    # Cell 5: the inferred route is ambiguous across ≥2 roster members — NEVER silently
    # pick. Emit an ask_user_choice card (reuse the PA-3 clarify_options frame) and park a
    # choice; the user's pick dispatches the parked task to the chosen member.
    if cell == _CELL_MEMBER_PICKER:
        cands = candidates or []
        cjk = _is_cjk(user_message)
        question = "这个任务交给谁来做?" if cjk else "Who should take this on?"
        options = [{"label": c.get("name") or f"#{c.get('spawn_id')}",
                    "hint": (c.get("why") or "")} for c in cands]
        await phase_service.set_choosing(
            conversation_id, candidates=cands,
            task_brief=result.task_brief or "", user_message=user_message,
            needs_proposal=bool(getattr(result, "needs_proposal", False)))
        emit(protocol.clarify_options(question, options))
        return

    # Cells 6 / 7: doer-first — Arslan does the task ITSELF (no capable member has it).
    # It KNOWS the inferred spawn's name, so the promise interceptor inside _handle_answer
    # gets the high-precision "交给/让/派 <name>" pattern; turn_delegated=False by
    # construction (no dispatch this turn) so any such claim is always intercepted (PA-1/HX-1).
    _guard_spawn_name = await dispatcher.get_spawn_name(result.spawn_id)
    answer_text = await _handle_answer(
        conversation_id, user_message, emit,
        attached_context=attached_context, images=images, confirm_command=confirm_command,
        intercept_spawn_name=_guard_spawn_name, turn_delegated=False)

    # BUG1 gate (cell 6 only): suppress the RECRUITING chip on an affirmative,
    # registry-anchored domain contradiction. Runs AFTER the answer streamed, so it
    # delays only the chip, never the reply. Every failure mode floats the chip.
    recruit_suppressed = (
        cell == _CELL_RECRUIT and await _recruit_domain_conflict(result, user_message)
    )

    # Dual-track growth (boundary component 5): feed Arslan's own deliverable to the
    # inferred spawn in the background so it learns without having acted — but not when
    # the gate just concluded the spawn is wrong-domain (feeding the deliverable would
    # grow the WRONG spawn's well).
    if (answer_text and len(answer_text.strip()) >= _DUAL_TRACK_MIN_CHARS
            and not recruit_suppressed):
        _fire_dual_track(conversation_id, result.spawn_id, _guard_spawn_name,
                         _dual_track_signals(user_message, answer_text))

    # Cell 6: the router picked a NON-member as best fit → RECRUITING invite. The park
    # carries answered=True so Accept ONLY enrolls (session-scoped roster; the user can
    # then @ it directly) and does NOT re-dispatch the task Arslan already answered
    # (Bug 1 fix). Cell 7 (no capable member) stops at the doer-first answer — the
    # suggest_create staffing spine is the `suggest_create` router action, untouched.
    if cell == _CELL_RECRUIT:
        if recruit_suppressed:
            logger.info(
                "recruit chip suppressed (cell 6): task domain contradicts pick %s (%s)",
                result.spawn_id, _guard_spawn_name)
            return
        reason = (f"让「{_guard_spawn_name}」接手更专业?" if _is_cjk(user_message)
                  else f"Let {_guard_spawn_name} take this for more depth?")
        await phase_service.set_inviting(
            conversation_id, result.spawn_id,
            task_brief=result.task_brief or "", user_message=user_message,
            needs_proposal=bool(getattr(result, "needs_proposal", False)),
            announced=True, answered=True)
        from server.services import recap_service
        await recap_service.log_event(
            conversation_id, "invite", {"spawn_id": result.spawn_id, "spawn_name": _guard_spawn_name},
            f"招募邀请 {_guard_spawn_name or '分身'} 加入")
        emit(protocol.propose_invite(result.spawn_id, reason))


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
    """Arslan's host-level safe toolset: web + chart + second-brain recall/remember
    (no spawn wiring)."""
    from server.registry.executors import EXECUTORS

    desc = {
        "web_search": "Search the web for fresh/factual info; returns titles/urls/snippets.",
        "web_extract": "Fetch a URL and return its main text (SSRF-guarded).",
        "render_chart": "Render a line/bar/pie chart from structured data; the user sees the chart.",
        "recall": "Search the user's second brain (facts, learnings, notes) for relevant "
                  "context before answering.",
        "remember": "Write to the user's second brain: append a fact/learning/note worth "
                    "remembering later.",
    }
    tools = [{"key": k, "description": desc[k]}
             for k in ("web_search", "web_extract", "render_chart", "recall", "remember")
             if k in EXECUTORS]
    # PA-3: structured clarification — a TERMINAL tool (no executor; the tool loop ends
    # the turn and _handle_answer emits the clarify_options card). Registered here so
    # Arslan's answer path can offer real choice buttons instead of a text counter-question.
    tools.append({"key": "ask_user_choice",
                  "description": "Ask the user to pick ONE of 2-4 concrete directions when you "
                                 "genuinely cannot proceed without their choice. args: {question, "
                                 "options: [{label, hint?}] (2-4 options)}. The user answers with "
                                 "one click — NEVER ask a multiple-choice question in plain text."})
    if "list_my_capabilities" in EXECUTORS:
        tools.append({"key": "list_my_capabilities",
                      "description": "List your OWN usable capabilities (built-in tools + installed "
                                     "MCP servers). Call this ONCE when the user asks what you can do / "
                                     "what tools or MCPs you have, then answer from its result in a "
                                     "short friendly summary — never paste the raw JSON back."})
    from sqlalchemy import select

    from server.db import session as db_session
    from server.db.models import Tool

    # Orchestrator-only shell: exposed to Arslan ONLY when the user opted in (default off).
    from server.services import settings_service
    async with db_session.AsyncSessionLocal() as db:
        if await settings_service.shell_enabled(db):
            tools.append({"key": "run_command",
                          "description": "Run a whitelisted shell command (git/gh/ffmpeg/pandoc). "
                                         "Each command requires the user's per-command confirmation. "
                                         "argv is a list; no pipes/redirects/shell operators."})
    # Host-allowed MCP tools: human-wired AND explicitly host_enabled (default off).
    async with db_session.AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Tool).where(Tool.toolset_key.like("mcp_%"),
                               Tool.status == "wired", Tool.host_enabled.is_(True))
        )).scalars().all()
    # Carry input_schema through so `_native_tool_schemas` (in run_native) hands the model the
    # real JSON Schema captured at MCP discovery — instead of a permissive {} it must guess against.
    tools += [{"key": t.key, "description": t.description, "input_schema": t.input_schema or {}}
              for t in rows]
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
        run_id=run_id,
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
    # S3-M3 Task 5: _handle_escalation is only called from inside _dispatch_spawn's
    # usage_sink.collecting() scope, so the run's usage (dispatch + this re-dispatch)
    # is readable here — same frame shape as the main dispatch stream_end.
    emit({"type": "stream_end", "message_id": out["summary_message_id"],
          "usage": _usage_frame(usage_sink.detail()),
          **({"artifact": out["artifact"]} if out.get("artifact") else {})})
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
    attached_context: str | None = None, images: list[dict] | None = None,
    announce: bool = True,
    _auto_continues: int = MAX_AUTO_CONTINUES,
    _continuation: bool = False,
) -> None:
    """Run one spawn turn, recording it as a Run for replay + evaluation.

    _auto_continues: remaining automatic re-dispatches for THIS user turn (threaded
    through the recursion — no shared/module state). When a round ends with a
    findings digest and budget remains, the same spawn is re-dispatched on the same
    direction; the digest message is already in its history, so the next round
    builds on the evidence instead of the user having to type 继续.

    _continuation: True only on those auto-continue re-dispatches (E1). The recorder
    marks the Run so the judge scores completion against this round's incremental
    goal — a middle round judged against the FULL request skews completion down."""
    spawn_name = await dispatcher.get_spawn_name(spawn_id)
    if spawn_name is None:
        # The spawn no longer exists (deleted mid-conversation, or a stale id from any
        # entry point). Bail BEFORE RunRecorder.start() — recording a Run with a
        # dangling spawn_id would raise sqlite3.IntegrityError (FK constraint) and
        # crash the turn. Surface a recoverable in-chat error instead.
        logger.warning("_dispatch_spawn: spawn_id=%s not found — skipping dispatch", spawn_id)
        emit({"type": "error", "code": "SPAWN_NOT_FOUND",
              "message": "That assistant is no longer available.", "recoverable": True})
        return
    recorder = await run_recorder.RunRecorder.start(
        conversation_id=conversation_id, spawn_id=spawn_id, spawn_name=spawn_name,
        user_message=user_message or task_brief, route_ms=route_ms,
        continuation=_continuation,
        # T11: recorded so build_corpus can keep this run out of the exam. An
        # image lives for one turn (③A), so a replay arm could never see it.
        has_images=bool(images),
    )
    tee = recorder.tee(emit)
    chunks: list[str] = []  # streamed partial — the ONLY output a cancelled run can persist

    async def _run_turn() -> None:
        # Pre-stream cancel guard (review I3): the roster join and _route_announcement
        # (an LLM call) run BEFORE the collecting-scope handler below — a cancel landing
        # here would otherwise propagate unfinalized and rot the row at 'recording' until
        # the next boot reap. Nothing ran yet, so finalize bare (no usage/prompt detail).
        try:
            # Join FIRST (DB state) so the announcement's roster lookup sees the routed spawn,
            # but EMIT the routing frame (with the announcement) BEFORE the roster join notice:
            # the user reads "user message → Arslan's brief → X joined → spawn work" in order.
            # (User feedback: the brief showing up above an anonymous join divider read as a
            # bare system line, not Arslan speaking.)
            newly_joined = await roster_service.join(conversation_id, spawn_id, via="routed")
            # Routing brief: restate the need + @-mention each involved spawn (grounded in the
            # real roster). Built only on the FIRST round of a user turn — auto-continue rounds
            # re-emit the routing frame for the UI pulse but must not repeat the announcement.
            # `announce=False` when the brief was ALREADY shown before an invite card (accepted
            # inline invite): Arslan spoke first, so the post-accept dispatch skips re-announcing.
            announcement = None
            if announce and _auto_continues == MAX_AUTO_CONTINUES:
                announcement = await _route_announcement(conversation_id, spawn_id, spawn_name, task_brief)
            tee({"type": "routing", "spawn_id": spawn_id, "spawn_name": spawn_name,
                 **({"announcement": announcement} if announcement else {})})
            if newly_joined:
                tee({"type": "roster_event", "action": "joined", "spawn_id": spawn_id, "spawn_name": spawn_name})
            tee({"type": "roster_update", "members": await roster_service.list_roster(conversation_id)})
            tee({"type": "stream_start", "source": "spawn", "spawn_id": spawn_id,
                 "run_id": recorder.run_id})
        except asyncio.CancelledError:
            await recorder.finalize(summary_message_id=None, full_output="",
                                    status_override="cancelled")
            emit({"type": "run_cancelled", "run_id": recorder.run_id})
            raise
        # usage_sink.collecting() is scoped HERE — one fresh bucket per Run — not around the
        # whole user turn. This is the S0 hemostasis fix: EVERY dispatch path funnels through
        # _dispatch_spawn, so opening the scope here means route_to/redo/refine/confirm_direction/
        # roster_invite-accept/confirm_create (which call dispatch_spawn/dispatch_routed/
        # confirm_and_execute WITHOUT a turn-level scope) all capture their own model/provider/
        # tokens automatically. Per-Run scoping ALSO kills the turn-cumulative double-count: an
        # auto-continue re-dispatch (the recursive call below, OUTSIDE this block) opens its own
        # fresh scope, so each Run's finalize reads only its own usage — never the prior round's.
        # An escalation re-dispatch stays INSIDE this same block, so its usage folds into the SAME
        # Run, which is correct (one escalation resolution = one Run).
        # run_trace.collecting() spans the dispatch call (and any escalation re-dispatch) AND
        # every finalize() below, so tool_loop's run_trace.record(...) calls and the assembled
        # system prompt (build_spawn_system → run_trace.record_prompt) are both still readable
        # via snapshot()/prompt() at finalize time — draining happens inside RunRecorder.finalize
        # (_merge_tool_trace calls run_trace.snapshot()), before this context exits.
        with usage_sink.collecting(), run_trace.collecting():
            try:
                try:
                    out = await dispatcher.dispatch(
                        conversation_id, spawn_id=spawn_id, task_brief=task_brief,
                        on_chunk=lambda c: (chunks.append(c),
                                            tee({"type": "stream_chunk", "content": c}))[1],
                        on_event=tee, prior_output=prior_output, instruction=instruction, mode=mode,
                        attached_context=attached_context, images=images, run_id=recorder.run_id,
                    )
                except Exception as exc:  # noqa: BLE001
                    # Decision ②A: we never gated on the (unreliable) vision
                    # capability flag, so a model that cannot see fails HERE.
                    # Translate that one case into something actionable; every
                    # other error keeps its original text, because mislabelling a
                    # rate limit as a vision problem sends the user off changing
                    # models over an unrelated fault.
                    _msg = vision_errors.explain(str(exc), had_images=bool(images)) or str(exc)
                    tee({"type": "error", "code": "SPAWN_ERROR", "message": _msg, "recoverable": True})
                    _usage = usage_sink.detail()
                    _prompt = run_trace.prompt()
                    await recorder.finalize(
                        summary_message_id=None, full_output="",
                        model=_usage["model"], provider=_usage["provider"],
                        tokens_in=_usage["tokens_in"], tokens_out=_usage["tokens_out"],
                        tokens_estimated=(_usage["tokens_in"] is None),
                        error_kind=type(exc).__name__, error_text=str(exc),
                        system_prompt=_prompt["system_prompt"], injected_kb=_prompt["injected_kb"],
                        injected_kb_sources=_prompt.get("injected_kb_sources"),
                    )
                    return

                if out.get("escalation"):
                    esc_out = await _handle_escalation(
                        conversation_id, spawn_id, spawn_name, task_brief, out["escalation"], tee,
                        run_id=recorder.run_id,
                    )
                    final = esc_out or out
                    _usage = usage_sink.detail()
                    _prompt = run_trace.prompt()
                    await recorder.finalize(
                        summary_message_id=final.get("summary_message_id"),
                        full_output=final.get("full_output", ""),
                        model=_usage["model"], provider=_usage["provider"],
                        tokens_in=_usage["tokens_in"], tokens_out=_usage["tokens_out"],
                        tokens_estimated=(_usage["tokens_in"] is None),
                        system_prompt=_prompt["system_prompt"], injected_kb=_prompt["injected_kb"],
                        injected_kb_sources=_prompt.get("injected_kb_sources"),
                    )
                    return

                _usage = usage_sink.detail()
                _prompt = run_trace.prompt()
                # S3-M3 Task 5: the stream_end below is emitted AFTER this collecting
                # scope closes — build the frame payload NOW, from the SAME _usage
                # snapshot finalize persists (frame chip and Run row can never disagree).
                usage_frame = _usage_frame(_usage)
                await recorder.finalize(
                    summary_message_id=out["summary_message_id"], full_output=out["full_output"],
                    model=_usage["model"], provider=_usage["provider"],
                    tokens_in=_usage["tokens_in"], tokens_out=_usage["tokens_out"],
                    tokens_estimated=(_usage["tokens_in"] is None),
                    system_prompt=_prompt["system_prompt"], injected_kb=_prompt["injected_kb"],
                    injected_kb_sources=_prompt.get("injected_kb_sources"),
                )
            except asyncio.CancelledError:
                # S3-M1 user cancel — handled HERE, still inside the collecting scopes, so
                # usage/prompt detail is readable. Persist the streamed partial (an aborted
                # run must not silently eat output the user already saw), finalize as
                # 'cancelled' (skips scoring → can never enter the corpus), then RE-RAISE
                # so the task ends cancelled — the awaiter below tells user-cancel apart
                # from its own teardown via task.cancelled().
                partial = "".join(chunks)
                summary_id = None
                # recorder._finalized (private, but this function owns the recorder): a
                # cancel that landed AFTER the commit means the real summary is already
                # persisted — a 已中断 partial here would be a duplicate.
                if partial.strip() and not recorder._finalized:
                    summary_id = await memory.add_message(
                        conversation_id, "spawn_summary",
                        f"[{spawn_name}] {task_brief} -> 已中断",
                        display_content=partial + "\n\n_(已中断)_", spawn_id=spawn_id,
                    )
                _usage = usage_sink.detail()
                _prompt = run_trace.prompt()
                await recorder.finalize(
                    summary_message_id=summary_id, full_output=partial,
                    model=_usage["model"], provider=_usage["provider"],
                    tokens_in=_usage["tokens_in"], tokens_out=_usage["tokens_out"],
                    tokens_estimated=(_usage["tokens_in"] is None),
                    status_override="cancelled",
                    system_prompt=_prompt["system_prompt"], injected_kb=_prompt["injected_kb"],
                    injected_kb_sources=_prompt.get("injected_kb_sources"),
                )
                # Via emit, NOT tee (review S7): finalize already derived the steps —
                # a tee'd post-finalize event would be a dead entry in recorder._events.
                emit({"type": "run_cancelled", "run_id": recorder.run_id,
                      **({"message_id": summary_id} if summary_id else {})})
                raise
        tee({
            "type": "spawn_meta", "arslan_message_id": out["summary_message_id"],
            "spawn_id": spawn_id, "spawn_name": spawn_name,
            "assistant_message_id": out["assistant_message_id"],
            "task_brief": task_brief, "run_id": recorder.run_id,
        })
        # HX-2: a packaged HTML deliverable rides the stream_end frame (the frame the
        # store turns into the chat item) so the frontend can render the preview card live.
        tee({"type": "stream_end", "message_id": out["summary_message_id"],
             "usage": usage_frame,
             **({"artifact": out["artifact"]} if out.get("artifact") else {})})

        # Auto-continue: a round that ended with a findings digest made real progress but ran
        # out of tool budget — never park it on "回复'继续'" while budget remains. The digest
        # message was already emitted above (the user sees the progress); re-dispatch the SAME
        # spawn on the SAME direction so the next round builds on the carried evidence. The
        # bare no-evidence fallback has no marker and never re-dispatches. After the final
        # auto-continue, a still-digest-ending message is kept as-is (its 回复'继续' tail is
        # then honest — the user can continue manually).
        # (Recursion stays INSIDE _run_turn: each recursive _dispatch_spawn registers its
        # OWN run+task, so every round is cancellable under its own run_id. Cancel routing:
        # a PARENT-run_id cancel delegates into the child task and PROPAGATES back out at
        # the child's awaiter — cancelling()>0 on THIS task — so the parent does NOT
        # resume; only a direct CHILD-run_id cancel is swallowed by the child's awaiter,
        # and then the parent _run_turn resumes normally right here. LOAD-BEARING: the
        # recursion must remain _run_turn's LAST statement — any statement placed after
        # it would run in that post-child-cancel state.)
        if _auto_continues > 0 and _has_findings_digest(out.get("full_output") or ""):
            emit({"type": "auto_continue", "spawn_id": spawn_id, "spawn_name": spawn_name,
                  "remaining": _auto_continues - 1})
            await _dispatch_spawn(
                conversation_id, spawn_id, task_brief, emit,
                mode=mode, user_message=user_message, attached_context=attached_context, images=images,
                _auto_continues=_auto_continues - 1,
                _continuation=True,
            )

    # S3-M1: the turn runs as its OWN task so POST /runs/{id}/cancel can target it via
    # run_registry. A user cancel is already fully handled inside _run_turn
    # (finalize+persist+frame) — swallow it so the WS turn survives; OUR OWN teardown
    # (WS disconnect/shutdown) must propagate the CancelledError contract.
    task = asyncio.create_task(_run_turn())
    run_registry.register(recorder.run_id, conversation_id, task, recorder=recorder)
    try:
        await task
    except asyncio.CancelledError:
        # task.cancelled() ALONE cannot discriminate (review I2): when THIS coroutine is
        # cancelled while suspended at `await task`, asyncio delegates the cancellation
        # INTO the inner task — it finalizes as if user-cancelled and task.cancelled()
        # comes back True. current_task().cancelling() > 0 (py3.11+) is the real signal:
        # nonzero means the CancelledError was aimed at US — propagate regardless of
        # what the inner task did.
        cur = asyncio.current_task()
        if cur is not None and cur.cancelling() > 0:
            task.cancel()  # teardown aimed at us — don't orphan a still-running turn
            raise
        if not task.cancelled():
            task.cancel()  # inner still running yet we got cancelled — same teardown case
            raise
        # else: user cancel via run_registry — fully handled inside _run_turn
    finally:
        run_registry.unregister(recorder.run_id, conversation_id)


_REFUSAL_RE = _re.compile(
    r"用尽了?工具额度|工具额度(已)?(用尽|耗尽|用完)|额度用完"
    r"|工具?调用次数(已)?用完|调用次数用完"
    r"|no (further|remaining) (tool )?(quota|capability)"
    r"|exhausted (my|the) (web[- ]search|tool)|tool quota (is )?exhausted"
    r"|used up this turn'?s tool calls"
    r"|这一轮还没做完|didn'?t finish (this one )?in a single round"
    r"|cannot produce a (new )?deliverable",
    _re.IGNORECASE)


def _looks_like_refusal(text: str) -> bool:
    """True for tool-exhaustion/fallback refusals — outputs that must never be treated as a
    proposal direction or deliverable (observed live: they self-replicate through the
    confirm→execute path and poison every following turn).

    A message carrying a 【阶段性发现】/[Findings so far] digest is SUBSTANTIVE even though it
    ends with the continue prompt — dropping it would restart research from zero on every
    continuation (the 3-rounds-of-identical-searches incident). It must be carried forward."""
    t = text or ""
    if "【阶段性发现】" in t or "[Findings so far]" in t:
        return False
    return bool(_REFUSAL_RE.search(t))


async def confirm_and_execute(conversation_id: str, spawn_id: int, emit: EventSink) -> None:
    """User confirmed a pending proposal — execute, carrying the spawn's proposed direction.

    The stored ``direction`` is the original task brief; the spawn's own proposed direction
    (its last propose-mode output) is fetched and carried via ``execute_confirmed`` framing so
    the spawn delivers the final result instead of re-asking clarifying questions.

    DOOM-LOOP GUARDS (from a live incident): confirm is ONE-SHOT — a re-click after the
    pending phase was consumed must not dispatch with an empty Task; and a refusal/fallback
    ("工具额度用尽…") must never be carried as the "confirmed direction" (the spawn would
    role-play the refusal forever instead of doing fresh work).
    """
    pending = await phase_service.get_pending(conversation_id)
    direction = ((pending or {}).get("direction") or "").strip()
    if not direction:
        # Stale confirm (button re-clicked after the proposal was consumed, or no proposal).
        emit({"type": "message", "message_id": None, "role": "arslan",
              "content": "这个提案已经执行过了(或没有待执行的提案)。直接告诉我接下来要做什么就好。"})
        emit({"type": "stream_end", "message_id": None})
        return
    proposed = await dispatcher.last_spawn_output(spawn_id)
    if proposed and _looks_like_refusal(proposed):
        proposed = None  # never re-inject a refusal as the "direction"
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

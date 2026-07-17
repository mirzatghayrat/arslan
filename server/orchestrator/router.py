"""Two-stage router, stage 1: a single structured-JSON decision call."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import RouterDecision, Spawn
from server.orchestrator import memory
from server.orchestrator.json_protocol import parse_json_object
from server.services import spawn_service, usage_ledger
from server.services.llm_factory import build_adapter

from arslan.llm.cached_system import build_cached_system

_VALID_ACTIONS = {"answer", "route", "suggest_create", "clarify", "suggest_update", "suggest_connect_mcp"}


@dataclass
class RouterResult:
    action: str  # answer | route | suggest_create | clarify
    spawn_id: int | None = None
    task_brief: str | None = None
    suggested_spawn: dict[str, Any] | None = None
    overlaps: dict[str, Any] | None = None
    new_facts: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    needs_proposal: bool = False
    connector_query: str | None = None


_SYSTEM = (
    "You are Arslan, a meta-agent orchestrator. Decide how to handle the user's latest "
    "message. Reply with ONE JSON object and nothing else:\n"
    '{"action": "answer" | "route" | "suggest_create" | "clarify" | "suggest_update" | "suggest_connect_mcp", '
    '"spawn_id": <int, for route AND suggest_update>, '
    '"task_brief": "<self-contained task for the spawn; REQUIRED for route AND suggest_create>", '
    '"suggested_spawn": {"name","domain","capabilities","persona_role","persona_tone"}, '
    '"overlaps": {"spawn_id": <int>, "name": "<existing spawn>", "axes": ["<how a new one could differ>"]}, '
    '"new_facts": [{"content": "<durable user fact>", "sensitive": <bool>}], '
    '"needs_proposal": <bool, only for route — true if the task is open-ended and the spawn should propose a direction first>, '
    '"connector_query": "<connector name, for suggest_connect_mcp>", '
    '"reason": "<short>"}\n'
    "- needs_proposal (route only): set TRUE when the routed task is open-ended/ambiguous (the spawn should propose a direction + ask clarifying questions before producing). Set FALSE when the task is crisp and the spawn can produce the deliverable directly. Examples TRUE: 'help with my LinkedIn', 'do some marketing'. Examples FALSE: 'summarize this article: …', 'draft 3 xiaohongshu posts about retinol'.\n"
    "- answer: This is the DEFAULT. Respond directly AS Arslan (the host). Arslan has its own "
    "tools — it can search the web (web_search), including finding projects/code on GitHub or any "
    "site; fetch a page's text (web_extract); and render charts (render_chart). ANY task Arslan can "
    "do with these — searching, looking things up online, reading a page, a one-off question, "
    "cross-domain glue work — is `answer`; Arslan does it itself. Do NOT route these to a spawn. "
    "Also use answer for greetings, small talk, thanks, social pleasantries, meta-questions about "
    "you/Arslan, or ANY message that contains no actionable task — reply warmly and invite the user "
    "to describe what they need. A bare greeting like '哈喽' / 'hi' / '在吗' is ALWAYS answer, NEVER "
    "route.\n"
    "- route: ONLY when the task falls squarely in an existing spawn's clear domain AND that "
    "specialist genuinely fits — not for anything Arslan can just do itself. A loose keyword/topic "
    "association is NOT enough — if no spawn clearly fits, use answer or suggest_create; never force "
    "a route to a loosely-related spawn. When unsure between answer and route, choose answer. Put a "
    "clean, self-contained task in task_brief. "
    "A task spanning MULTIPLE domains, or a mostly-general request with just one deep sub-part, does "
    "NOT fall squarely in one domain → use answer: Arslan does what it can and stitches the whole "
    "result itself, pulling in a specialist only if the user explicitly asks. One deep segment is "
    "NOT a reason to route the entire task out.\n"
    "- suggest_create: a recurring need has no spawn; draft suggested_spawn AND put the "
    "user's current request in task_brief (the new spawn will run it immediately). "
    "domain is a free-form 'category.subcategory' string you infer (e.g. 'finance.equity-research'). "
    "Only choose suggest_create when you already know the spawn's domain, at least one concrete "
    "capability, AND the immediate task it will run. If any is missing, choose clarify and ask "
    "Arslan's question to gather it first. Never suggest_create on a bare 'make me a spawn'.\n"
    "- overlaps: ONLY when suggest_create would duplicate an EXISTING spawn's domain — name it "
    "and suggest differentiation axes; otherwise omit.\n"
    "- suggest_update: the user asks to MODIFY an existing spawn itself — change its persona/"
    "tone, add/remove its tools or skills, adjust its capability tags (e.g. '给财务分析师加上 "
    "deck 工具', 'make Deck Master more formal'). Set spawn_id to the target spawn and put the "
    "requested change (verbatim intent) in task_brief. This is about EDITING the agent, NOT "
    "giving it a task to run (that is route) and NOT creating a new one (that is suggest_create).\n"
    "- suggest_connect_mcp: the user wants to connect/add a NAMED MCP server/connector "
    "(\"connect my GitHub\", \"add the Notion MCP\"). Put the connector name in connector_query. "
    "Do NOT use this for running a connected tool.\n"
    "- clarify: the request is too under-specified to act well (no identifiable topic/subject "
    "AND/OR no inferable deliverable shape — format/angle/output/data source). Do NOT route or "
    "create; the handler will ask clarifying questions. If a topic IS present and a reasonable "
    "deliverable can be inferred, do NOT clarify — act.\n"
    "  CLARIFY examples: '分析互联网数据 写report'; 'help me with marketing'; 'write something about finance'; '做个分析'.\n"
    "  DO-NOT-CLARIFY (act) examples: 'draft 3 xiaohongshu posts about retinol'; 'pull the latest "
    "A-share ETF flows'; 'summarize this article: ...'; 'write a product description for our oat milk'.\n"
    "When uncertain between route and answer/clarify, PREFER answer/clarify — Arslan confirms "
    "the need with the user before delegating to a spawn. Do not delegate prematurely.\n"
    "new_facts: extract any durable user preferences/facts worth remembering (or []). "
    "Each fact's content MUST be written in the same language as the user's own messages "
    "(事实条目必须使用用户消息所用的语言书写)— never translate the user's language into English: "
    "the fact text is shown to the user verbatim in their chat.\n"
)


def _get_adapter():
    """Indirection so tests can stub adapter construction."""
    return build_adapter(role="router")


async def _spawn_registry() -> str:
    async with db_session.AsyncSessionLocal() as db:
        rows = await db.execute(select(Spawn).order_by(Spawn.id))
        spawns = rows.scalars().all()
    if not spawns:
        return "(no spawns yet)"
    lines = []
    for s in spawns:
        domain = s.domain_category + (f".{s.domain_subcategory}" if s.domain_subcategory else "")
        lines.append(
            f"- id={s.id} name={s.name} domain={domain} "
            f"role={s.persona_role or ''} caps={','.join(s.capabilities or [])}"
        )
    return "\n".join(lines)


async def _spawn_exists(spawn_id: int) -> bool:
    """Whether a spawn id is real. The router LLM picks spawn_id from the registry
    text and can return a hallucinated or stale id; we must verify it before routing
    so dispatch never inserts a Run with a dangling FK (FOREIGN KEY constraint failed)."""
    async with db_session.AsyncSessionLocal() as db:
        return await db.get(Spawn, spawn_id) is not None


def _parse(content: str) -> dict[str, Any] | None:
    return parse_json_object(content)


def _audit_payload(parsed: dict | None, raw_text: str | None) -> dict:
    """What to store in RouterDecision.raw: the parsed dict, or the raw text on failure."""
    return parsed if parsed is not None else {"_raw": raw_text or ""}


async def route(conversation_id: str, user_message: str) -> RouterResult:
    """Run stage 1. Always returns a RouterResult and persists a RouterDecision row.

    Contract: when the returned action == "route", spawn_id is guaranteed to be an int
    (a missing/invalid spawn_id is downgraded to "answer"). The orchestration loop must
    still re-check that the spawn id actually exists at dispatch time.
    """
    ctx = await memory.assemble_working_context(conversation_id)
    facts = await memory.facts_text(include_sensitive=True)
    registry = await _spawn_registry()

    prompt = (
        f"Conversation summary:\n{ctx['summary'] or '(none)'}\n\n"
        f"Recent turns:\n"
        + "\n".join(f"{m['role']}: {m['content']}" for m in ctx["history"])
        + f"\n\n{facts}\n\nAvailable spawns:\n{registry}\n\n"
        f"User's latest message:\n{user_message}"
    )

    # S3-M3 usage ledger: the router decision runs BEFORE any dispatch, outside
    # _dispatch_spawn's per-Run usage_sink.collecting() region — its tokens land
    # nowhere else, so ledger them under scope="router".
    # Prompt-cache reorder (spec 2026-07-13, Task 2): the router's dynamic context
    # (summary/turns/facts/registry/user msg) already lives in the USER message, so the
    # system is the pure-static _SYSTEM rubric. Wrap it as a CachedSystem(stable=_SYSTEM,
    # volatile="") so the Anthropic adapter places a cache_control breakpoint on the rubric;
    # DeepSeek/OpenAI/Ollama see the byte-identical string (== _SYSTEM) and auto-cache it.
    system = build_cached_system(_SYSTEM, "")
    async with usage_ledger.scope("router", conversation_id):
        adapter = _get_adapter()
        a = await adapter if hasattr(adapter, "__await__") else adapter
        resp = await a.chat(system=system, user=prompt)
    raw = resp.content

    parsed = _parse(raw or "")
    action = parsed.get("action") if parsed else None

    if parsed is None or action not in _VALID_ACTIONS:
        result = RouterResult(action="answer", reason="router fallback")
        await _persist(conversation_id, user_message, "fallback", result, _audit_payload(parsed, raw))
        return result

    if action in ("route", "suggest_update") and not isinstance(parsed.get("spawn_id"), int):
        result = RouterResult(action="answer", reason=f"{action} missing valid spawn_id")
        await _persist(conversation_id, user_message, "fallback", result, _audit_payload(parsed, raw))
        return result

    if action in ("route", "suggest_update") and not await _spawn_exists(parsed["spawn_id"]):
        # The LLM routed to a non-existent spawn (hallucinated/stale id). Downgrade to
        # answer rather than dispatch to a dangling id (would crash with a FK error).
        result = RouterResult(action="answer", reason=f"{action} to non-existent spawn")
        await _persist(conversation_id, user_message, "fallback", result, _audit_payload(parsed, raw))
        return result

    raw_draft = parsed.get("suggested_spawn")
    result = RouterResult(
        action=action,
        spawn_id=parsed.get("spawn_id"),
        task_brief=parsed.get("task_brief"),
        suggested_spawn=spawn_service.normalize_draft(raw_draft) if isinstance(raw_draft, dict) else None,
        overlaps=parsed.get("overlaps") if isinstance(parsed.get("overlaps"), dict) else None,
        new_facts=[
            f for f in (parsed.get("new_facts") or [])
            if isinstance(f, dict) and (f.get("content") or "").strip()
        ],
        reason=parsed.get("reason", ""),
        needs_proposal=bool(parsed.get("needs_proposal", False)),
        connector_query=parsed.get("connector_query"),
    )
    await _persist(conversation_id, user_message, action, result, _audit_payload(parsed, raw))
    return result


async def previous_decision(conversation_id: str) -> RouterDecision | None:
    """The RouterDecision persisted BEFORE the current turn's (PA-2 consecutive-route rule).

    route() persists the current turn's row before the orchestration loop handles the
    result, so by the time _handle_route consults this, the LATEST row for the
    conversation is this very turn's own decision — the previous turn's decision is the
    second-latest. Returns None when there is no earlier row."""
    async with db_session.AsyncSessionLocal() as db:
        rows = await db.execute(
            select(RouterDecision)
            .where(RouterDecision.conversation_id == conversation_id)
            .order_by(RouterDecision.id.desc())
            .offset(1)
            .limit(1)
        )
        return rows.scalars().first()


async def _persist(
    conversation_id: str,
    user_message: str,
    logged_action: str,
    result: RouterResult,
    raw: dict | None,
) -> None:
    async with db_session.AsyncSessionLocal() as db:
        db.add(
            RouterDecision(
                conversation_id=conversation_id,
                user_message=user_message,
                action=logged_action,
                spawn_id=result.spawn_id,
                task_brief=result.task_brief,
                reason=result.reason,
                raw=raw,
            )
        )
        await db.commit()

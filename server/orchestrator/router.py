"""Two-stage router, stage 1: a single structured-JSON decision call."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from server.db import session as db_session
from server.db.models import RouterDecision, Spawn
from server.orchestrator import memory
from server.orchestrator.json_protocol import parse_json_object
from server.services import spawn_service
from server.services.llm_factory import build_adapter

_VALID_ACTIONS = {"answer", "route", "suggest_create", "clarify"}


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


_SYSTEM = (
    "You are Arslan, a meta-agent orchestrator. Decide how to handle the user's latest "
    "message. Reply with ONE JSON object and nothing else:\n"
    '{"action": "answer" | "route" | "suggest_create" | "clarify", "spawn_id": <int, only for route>, '
    '"task_brief": "<self-contained task for the spawn; REQUIRED for route AND suggest_create>", '
    '"suggested_spawn": {"name","domain","capabilities","persona_role","persona_tone"}, '
    '"overlaps": {"spawn_id": <int>, "name": "<existing spawn>", "axes": ["<how a new one could differ>"]}, '
    '"new_facts": [{"content": "<durable user fact>", "sensitive": <bool>}], '
    '"needs_proposal": <bool, only for route — true if the task is open-ended and the spawn should propose a direction first>, '
    '"reason": "<short>"}\n'
    "- needs_proposal (route only): set TRUE when the routed task is open-ended/ambiguous (the spawn should propose a direction + ask clarifying questions before producing). Set FALSE when the task is crisp and the spawn can produce the deliverable directly. Examples TRUE: 'help with my LinkedIn', 'do some marketing'. Examples FALSE: 'summarize this article: …', 'draft 3 xiaohongshu posts about retinol'.\n"
    "- answer: respond directly AS Arslan (the host). Use answer for greetings, small talk, "
    "thanks, social pleasantries, meta-questions about you/Arslan, or ANY message that contains "
    "no actionable task — reply warmly and invite the user to describe what they need. A bare "
    "greeting like '哈喽' / 'hi' / '在吗' is ALWAYS answer, NEVER route.\n"
    "- route: ONLY when (a) the message contains a clear, actionable task AND (b) an existing "
    "spawn's domain GENUINELY matches that task. A loose keyword/topic association is NOT enough "
    "— if no spawn clearly fits, use answer or suggest_create; never force a route to a "
    "loosely-related spawn. Put a clean, self-contained task in task_brief.\n"
    "- suggest_create: a recurring need has no spawn; draft suggested_spawn AND put the "
    "user's current request in task_brief (the new spawn will run it immediately). "
    "domain is a free-form 'category.subcategory' string you infer (e.g. 'finance.equity-research').\n"
    "- overlaps: ONLY when suggest_create would duplicate an EXISTING spawn's domain — name it "
    "and suggest differentiation axes; otherwise omit.\n"
    "- clarify: the request is too under-specified to act well (no identifiable topic/subject "
    "AND/OR no inferable deliverable shape — format/angle/output/data source). Do NOT route or "
    "create; the handler will ask clarifying questions. If a topic IS present and a reasonable "
    "deliverable can be inferred, do NOT clarify — act.\n"
    "  CLARIFY examples: '分析互联网数据 写report'; 'help me with marketing'; 'write something about finance'; '做个分析'.\n"
    "  DO-NOT-CLARIFY (act) examples: 'draft 3 xiaohongshu posts about retinol'; 'pull the latest "
    "A-share ETF flows'; 'summarize this article: ...'; 'write a product description for our oat milk'.\n"
    "When uncertain between route and answer/clarify, PREFER answer/clarify — Arslan confirms "
    "the need with the user before delegating to a spawn. Do not delegate prematurely.\n"
    "new_facts: extract any durable user preferences/facts worth remembering (or []).\n"
)


def _get_adapter():
    """Indirection so tests can stub adapter construction."""
    return build_adapter()


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
    facts = await memory.facts_text()
    registry = await _spawn_registry()

    prompt = (
        f"Conversation summary:\n{ctx['summary'] or '(none)'}\n\n"
        f"Recent turns:\n"
        + "\n".join(f"{m['role']}: {m['content']}" for m in ctx["history"])
        + f"\n\n{facts}\n\nAvailable spawns:\n{registry}\n\n"
        f"User's latest message:\n{user_message}"
    )

    adapter = _get_adapter()
    a = await adapter if hasattr(adapter, "__await__") else adapter
    resp = await a.chat(system=_SYSTEM, user=prompt)
    raw = resp.content

    parsed = _parse(raw or "")
    action = parsed.get("action") if parsed else None

    if parsed is None or action not in _VALID_ACTIONS:
        result = RouterResult(action="answer", reason="router fallback")
        await _persist(conversation_id, user_message, "fallback", result, _audit_payload(parsed, raw))
        return result

    if action == "route" and not isinstance(parsed.get("spawn_id"), int):
        result = RouterResult(action="answer", reason="route missing valid spawn_id")
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
    )
    await _persist(conversation_id, user_message, action, result, _audit_payload(parsed, raw))
    return result


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

"""Things worth remembering, noticed after a turn (0.1.48).

This used to ride on the pre-turn router, which classified every message AND pulled
out durable facts in the same call. The router is gone (one agent loop decides what
to do), but the fact track stays: it is what lets a model that never calls tools
still remember "I prefer short answers". It now runs AFTER the answer, so it can
neither delay nor replace the reply, and a failure here only means nothing was
remembered this turn.

Same cheap model and slot as the router used (`router_config_id`, else role
"router"), same prompt budget: recent turns + known facts + the latest message.
"""
from __future__ import annotations

import contextvars
import logging
from typing import Any

from arslan.llm.cached_system import build_cached_system
from server.orchestrator import memory
from server.orchestrator.json_protocol import parse_json_object
from server.services import usage_ledger

logger = logging.getLogger(__name__)

MAX_FACTS = 5
MAX_FACT_CHARS = 300
MAX_PRACTICES = 2
# 0.1.52 S5: the practices the same reply named, for capture() — one model call, and
# the tests that replace extract() see no practices.
_practices: contextvars.ContextVar[list[dict]] = contextvars.ContextVar("turn_practices", default=[])

_SYSTEM = (
    "You read a conversation and pick out DURABLE facts about the user worth remembering in "
    "later conversations: stable preferences, how they like to work, who they are, long-running "
    "projects and goals. Not one-off requests, not what was said in this turn only, not facts "
    "already known (listed below), not anything about the assistant. Reply with ONE JSON object "
    'and nothing else: {"new_facts": [{"content": "<one fact>", "sensitive": <bool>}], '
    '"practices": [{"situation": "<when it applies>", "advice": "<what to do>", "avoid": <bool>}]} — '
    "both usually empty lists. Mark sensitive=true for health, money, relationships, identity "
    "numbers, exact location. A practice is the user's latest message correcting HOW the assistant "
    "should do a kind of task next time (\"don't use X for this, use Y\"); avoid=true when the advice "
    "is what not to do. Not a preference about the user, not a one-off instruction for this task. "
    "Write each fact and practice in the same language as the user's own messages "
    "(事实条目必须使用用户消息所用的语言书写); never translate it."
)


async def _get_adapter():
    from server.services.llm_factory import build_adapter, build_slot_adapter
    slotted = await build_slot_adapter("router_config_id")
    return slotted if slotted is not None else await build_adapter(role="router")


def parse(content: str | None) -> list[dict[str, Any]]:
    """The facts in a model reply; anything malformed is simply no facts."""
    parsed = parse_json_object(content or "") or {}
    out = []
    for item in parsed.get("new_facts") or []:
        if not isinstance(item, dict):
            continue
        text = " ".join(str(item.get("content") or "").split())[:MAX_FACT_CHARS]
        if text:
            out.append({"content": text, "sensitive": bool(item.get("sensitive"))})
    return out[:MAX_FACTS]


def parse_practices(content: str | None) -> list[dict[str, Any]]:
    parsed = parse_json_object(content or "") or {}
    out = []
    for item in parsed.get("practices") or []:
        if isinstance(item, dict) and item.get("situation") and item.get("advice"):
            out.append({"situation": str(item["situation"]), "advice": str(item["advice"]),
                        "avoid": item.get("avoid") is True})
    return out[:MAX_PRACTICES]


async def extract(conversation_id: str, user_message: str) -> list[dict[str, Any]]:
    """0.1.52: reads ONLY the user's own messages (and the facts already known).
    Arslan's replies and the rolling summary can carry web pages, files and tool
    output; since a noticed fact now takes effect at once (D1), it must come from
    the user's words — by construction, not by a filter on the output."""
    ctx = await memory.assemble_working_context(conversation_id)
    known = await memory.facts_text(include_sensitive=True)
    own = [m["content"] for m in ctx["history"] if m.get("role") == "user"]
    prompt = (
        "The user's recent messages:\n" + ("\n".join(f"- {c}" for c in own[-8:]) or "(none)")
        + f"\n\n{known}\n\nUser's latest message:\n{user_message}"
    )
    async with usage_ledger.scope("memory_facts", conversation_id):
        response = await (await _get_adapter()).chat(system=build_cached_system(_SYSTEM, ""), user=prompt)
    _practices.set(parse_practices(response.content))
    return parse(response.content)


async def capture(conversation_id: str, user_message: str, emit) -> int:
    """Extract and save; announce what was saved. Never raises. Returns how many."""
    _practices.set([])
    try:
        facts = await extract(conversation_id, user_message)
        _learn_practices(conversation_id, emit)
        if not facts:
            return 0
        created = await memory.save_facts(
            facts, provenance={"source_kind": "conversation", "conversation_id": conversation_id})
    except Exception as exc:  # noqa: BLE001 — remembering is a bonus, never a failure of the turn
        logger.info("turn facts skipped: %s", type(exc).__name__)
        return 0
    for fact in created:
        emit({"type": "memory_proposed" if getattr(fact, "status", "active") != "active" else "fact_saved",
              "content": fact.content, "sensitive": fact.sensitive,
              "entry_id": getattr(fact, "entry_id", None)})
    if created:
        try:
            from server.services import recap_service
            summary = " · ".join((getattr(f, "label", None) or f.content or "")[:24] for f in created[:3])
            await recap_service.log_event(conversation_id, "memory", None, summary)
        except Exception:  # noqa: BLE001
            pass
    return len(created)


def _learn_practices(conversation_id: str, emit) -> None:
    """The user's own correction becomes a lesson, off the reply path (lessons.capture)."""
    from server.services import lessons
    made = [lessons.candidate(p["situation"], p["advice"], source="user_correction",
                              polarity="avoid" if p["avoid"] else "do",
                              evidence={"conversation_id": conversation_id})
            for p in _practices.get()]
    made = [m for m in made if m]
    if made:
        lessons.later(lessons.capture(made, conversation_id=conversation_id, external_seen=False, emit=emit))

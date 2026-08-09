"""Generate a short conversation title from the first exchange.

Uses the cheap/summarize-role model to produce a 3-6 word title matching
the language of the user's message. Never raises — always returns some title.
"""
from __future__ import annotations

import re

import server.services.llm_factory as _llm_factory

_SYSTEM = (
    "You generate a very short title for a conversation — 3 to 6 words, "
    "in the SAME language as the user's message. "
    "Reply with ONLY the title: no quotes, no surrounding punctuation, "
    "no markdown, no prefix like 'Title:'."
)

_MAX_TITLE_LEN = 48
_MAX_REPLY_SNIPPET = 300
_FALLBACK_LEN = 24


def _clean(raw: str) -> str:
    """Defensively clean LLM output to a plain short title."""
    # Take only first line (collapse newlines)
    line = raw.split("\n")[0]
    # Strip surrounding whitespace, quotes, backticks
    line = line.strip().strip('"\'`').strip()
    # Remove trailing punctuation (. , ! ? ; : 。！？；：)
    line = re.sub(r'[\.,!?;:。！？；：]+$', '', line).strip()
    # Cap length
    if len(line) > _MAX_TITLE_LEN:
        line = line[:_MAX_TITLE_LEN]
    return line


def _fallback(first_message: str) -> str:
    """Derive a safe fallback title from the first_message."""
    # Strip markdown characters
    clean = re.sub(r'[#*_`~\[\]()>]', '', first_message).strip()
    if len(clean) > _FALLBACK_LEN:
        return clean[:_FALLBACK_LEN].rstrip() + "..."
    return clean or "New Conversation"



async def _adapter():
    """The adapter for this task, honouring its per-task slot if one is set.

    🔴 The slot is consulted FIRST and only overrides when the user set one — an unset
    slot returns None from build_slot_adapter, and this falls through to exactly the
    call that happened before. A hook that rerouted unconditionally would move this
    task, and its cost, onto another model with no symptom but the bill.
    """
    from server.services.llm_factory import build_slot_adapter

    slotted = await build_slot_adapter("title_config_id")
    if slotted is not None:
        return slotted
    return await _llm_factory.build_adapter(role="summarize")


async def generate_title(
    first_message: str,
    first_reply: str | None = None,
    conversation_id: str | None = None,
) -> str:
    """Generate a short conversation title.

    Returns a cleaned string — never raises.
    """
    # Build user prompt
    user_parts = [first_message]
    if first_reply:
        snippet = first_reply[:_MAX_REPLY_SNIPPET]
        user_parts.append(f"\n[Reply snippet]: {snippet}")
    user_prompt = "".join(user_parts)

    try:
        # S3-M3 usage ledger: the title call is a standalone LLM call (no Run row,
        # no surrounding collecting region) — ledger it under scope="titler".
        from server.services import usage_ledger

        async with usage_ledger.scope("titler", conversation_id):
            adapter = await _adapter()
            response = await adapter.chat(_SYSTEM, user_prompt)
        content = response.content
        if not content or not content.strip():
            return _fallback(first_message)
        cleaned = _clean(content)
        if not cleaned:
            return _fallback(first_message)
        return cleaned
    except Exception:  # noqa: BLE001
        return _fallback(first_message)

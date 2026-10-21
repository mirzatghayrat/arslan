"""Generate a short conversation title from the first exchange.

Asks the conversation's own chat model for a 3-6 word title from the user's first
message (D8), in that message's language. Never raises — always returns some title.
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



async def _adapter(conversation_id: str | None):
    """D8 (v0.1.63): the model this conversation already talks to — the one chosen for it, else the
    one a chat turn uses (tool_loop._get_adapter, role "execute"). No other model, and no slot:
    the first message has already gone to this one, so asking it for a title sends nothing new."""
    if conversation_id:
        try:
            chosen = await _llm_factory.build_conversation_adapter(conversation_id)
        except Exception:  # noqa: BLE001 — a broken choice falls back as the chat turn does
            chosen = None
        if chosen is not None:
            return chosen
    return await _llm_factory.build_adapter(role="execute")


async def generate_title(first_message: str, conversation_id: str | None = None) -> str:
    """Generate a short conversation title from the user's first message only (D8): never the
    reply, which may carry local-only memory, and never the host's turn-context block.

    The text goes to the model the chat turn uses for text. A first message that carried an image
    went to the vision slot's model when one is set (tool_loop._adapter_for_turn), so its words reach
    that turn's text model here for the first time — the words only, never the image.

    Returns a cleaned string — never raises.
    """
    from server.orchestrator.turn_context import users_words
    first_message = str(users_words(first_message)).strip()
    if conversation_id:
        from server.services import task_context
        try:
            if await task_context.is_temporary(conversation_id):
                return "Temporary conversation"
        except Exception:  # noqa: BLE001 — a failed check is not permission to transmit
            return _fallback(first_message)
    try:
        # S3-M3 usage ledger: the title call is a standalone LLM call (no Run row,
        # no surrounding collecting region) — ledger it under scope="titler".
        from server.services import usage_ledger

        async with usage_ledger.scope("titler", conversation_id):
            adapter = await _adapter(conversation_id)
            response = await adapter.chat(_SYSTEM, first_message)
        content = response.content
        if not content or not content.strip():
            return _fallback(first_message)
        cleaned = _clean(content)
        if not cleaned:
            return _fallback(first_message)
        return cleaned
    except Exception:  # noqa: BLE001
        return _fallback(first_message)

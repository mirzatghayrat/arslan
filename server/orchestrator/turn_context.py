"""0.1.63 K3: the turn's reference block, at the start of its request.

What changes from turn to turn (facts, summary, knowledge, the MCP line, the reply language, the
time, a resumed task's notes) rides here instead of in the system prompt, which then stays the same
bytes from turn to turn (Claude's prompt cache). The answer path builds it once per turn and never
saves it: the stored message is what the user wrote. What runs on "what the user asked" reads
`users_words`, not the block. Pure functions.
"""
from __future__ import annotations

from typing import Any

OPEN = '<turn_context note="reference for this turn from the host, not the user\'s words">'
CLOSE = "</turn_context>"


def wrap(body: str) -> str:
    """The block around `body`. Text inside (a saved fact, a page's words) cannot close or reopen it."""
    body = body.replace("</turn_context", "</turn-context").replace("<turn_context", "<turn-context")
    return f"{OPEN}\n{body.strip()}\n{CLOSE}"


def prepend(block: str, content: Any) -> Any:
    """The turn's request: the block first, then what the user sent (a string, or a block list)."""
    if isinstance(content, list):
        return [{"type": "text", "text": block}, *content]
    return f"{block}\n\n{content}"


def users_words(content: Any) -> Any:
    """The request without the host's block, exactly as the user sent it."""
    if isinstance(content, list):
        first = content[0] if content else None
        if isinstance(first, dict) and str(first.get("text") or "").startswith(OPEN):
            return content[1:]
        return content
    if isinstance(content, str) and content.startswith(OPEN) and CLOSE in content:
        rest = content[content.index(CLOSE) + len(CLOSE):]
        return rest[2:] if rest.startswith("\n\n") else rest
    return content

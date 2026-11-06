"""Conversations the iPhone starts name themselves `phone-` and a lowercase UUID v4 (Q1 card, detail A).

Q1b (#486 review, G1; the user, 2026-10-29): the server decides what such a conversation is by its stored kind,
never by a message. One with no kind stored (its store failed) is read as a quick question wherever the kind is
read (`kind_of`): the four tools, no learning, the quick list, and turning it into a chat.
"""
from __future__ import annotations

import re

PHONE_ID = re.compile(r"phone-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
#: The pocket, the one conversation every phone shared before §5.8, is retired (Q1 card, #4): an ordinary conversation
#: on the Mac, left out of the phone's list here (before it pages, #525 review F2). The Bridge refuses every frame
#: that names it and never links it (desktop/bridge, ConversationLinks.pocket).
POCKET = "pocket"


def made_on_the_phone(conversation_id: str | None) -> bool:
    return bool(PHONE_ID.fullmatch(conversation_id or ""))


def kind_of(conversation_id: str, stored: str | None) -> str | None:
    """What a conversation is: its stored kind (migration 0071), or `quick` for one the phone made with none."""
    return "quick" if stored is None and made_on_the_phone(conversation_id) else stored

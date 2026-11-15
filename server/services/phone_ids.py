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
#: SIDE-1: a side chat's id is this and a UUID (`side_chats.create`, the only place that makes one), so it reads as one
#: whatever its row says: none, or the tombstone its delete leaves, which keeps its runs (#910 review).
SIDE_PREFIX = "side-"


def made_on_the_phone(conversation_id: str | None) -> bool:
    return bool(PHONE_ID.fullmatch(conversation_id or ""))


def kind_of(conversation_id: str, stored: str | None) -> str | None:
    """What a conversation is: its stored kind (migration 0071), `quick` for one the phone made with none, or `side`
    for a side chat's id, whatever is stored (SIDE-1; a deleted one's row says `deleted`)."""
    if conversation_id.startswith(SIDE_PREFIX):
        return "side"
    return "quick" if stored is None and made_on_the_phone(conversation_id) else stored


def in_list(conversation_id: str, stored: str | None, *, quick: bool = False) -> bool:
    """Whether a conversation belongs in a list of conversations: the ordinary ones, or with `quick` the quick
    questions. A sub-session (SUB2) or a side chat (SIDE-1) is in neither; it is reached through the conversation that
    started it."""
    kind = kind_of(conversation_id, stored)
    return kind not in ("sub", "side") and (kind == "quick") is quick

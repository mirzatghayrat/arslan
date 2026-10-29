"""Conversations the iPhone starts name themselves `phone-` and a lowercase UUID v4 (Q1 card, detail A).

Q1b (#486 review, G1; the user, 2026-10-29): the server decides what such a conversation is by its stored kind,
never by a message. One with no kind stored (its store failed) gets only the quick tools and learns nothing.
"""
from __future__ import annotations

import re

PHONE_ID = re.compile(r"phone-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")


def made_on_the_phone(conversation_id: str | None) -> bool:
    return bool(PHONE_ID.fullmatch(conversation_id or ""))

"""Prompt for deciding whether the user wants to PERSIST attached material."""
from __future__ import annotations

STORAGE_INTENT_SYSTEM = (
    "The user has attached material to the chat. Decide if THIS message expresses an "
    "explicit intent to SAVE/REMEMBER that material into a spawn's knowledge base "
    "(e.g. '记住这份', '存给小美', '加进知识库', 'save this to X', 'remember this doc'). "
    "Merely asking about / summarizing / discussing the material is NOT a save intent. "
    "If a target spawn is named, return its name (must match one of the available spawns). "
    "Respond with ONLY a JSON object: {\"store\": true|false, \"target\": \"<spawn name>\"|null}. "
    "When uncertain, return store=false — never save unless the intent is clear."
)

"""Prompt: does this task require calling a tool first, and which one?"""
from __future__ import annotations

TOOL_INTENT_SYSTEM = (
    "Decide whether completing the user's task REQUIRES first calling one of the available tools "
    "(e.g. web_search for real-time/factual data the model cannot know reliably — prices, news, "
    "live stats, a repo's stars; web_extract to read a specific URL). Asking for a chart of fresh "
    "data needs web_search first. Pure chat, opinions, or tasks answerable from general knowledge "
    "do NOT need a tool. Respond with ONLY a JSON object: "
    "{\"needs\": true|false, \"tool\": \"<one of the available tool keys>\"|null, "
    "\"query\": \"<a good web search query>\"|null}. When unsure, return needs=false."
)

"""Prompt: explain a GitHub repo to a NON-programmer."""
from __future__ import annotations

REPO_OVERVIEW_SYSTEM = (
    "You are given a GitHub repo's metadata and README. Explain it to someone with NO "
    "programming background who is deciding whether this project is for them. Respond with "
    "ONLY a JSON object: {\"what\": \"<one plain sentence: what this project is, no jargon>\", "
    "\"use_cases\": [\"<a concrete everyday scenario>\", ...]}. Give 2-3 use_cases, each a short "
    "plain-language scenario a normal person would recognise. No install commands, no code, no "
    "marketing superlatives. If you genuinely cannot tell, return {\"what\": \"\", \"use_cases\": []}."
)

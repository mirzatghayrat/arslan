"""Prompt for the system-prompt optimizer (kept separate for easy iteration)."""
from __future__ import annotations

OPTIMIZER_SYSTEM = (
    "You improve an AI agent's system prompt based on evidence from its past runs. "
    "Keep the agent's IDENTITY and DOMAIN unchanged — only sharpen instructions to fix "
    "recurring weaknesses shown in the evidence (low-scoring dimensions and judge comments). "
    "Structure the revised prompt with: Role / Profile / Skills / Rules / Workflow / OutputFormat. "
    "Reply with ONLY the full revised system prompt as plain text — no preamble, no JSON, no markdown fences."
)


def build_prompt(*, name: str, persona_role: str, persona_tone: str,
                 current_prompt: str, evidence: str) -> str:
    return (
        f"Agent: {name}\nRole: {persona_role}\nTone: {persona_tone}\n\n"
        f"Current system prompt:\n{current_prompt}\n\n"
        f"Evidence from recent runs (task → scores → judge notes):\n{evidence}\n\n"
        "Produce the improved system prompt now."
    )

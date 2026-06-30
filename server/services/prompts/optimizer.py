"""Prompt for the system-prompt optimizer (kept separate for easy iteration)."""
from __future__ import annotations

OPTIMIZER_EDIT_SYSTEM = (
    "You improve an agent's instruction document. The document is markdown with `## <Section>` "
    "blocks. Propose a SMALL set of bounded edits as JSON: {\"edits\": [{\"op\": \"add|replace|delete\", "
    "\"section\": \"<header>\", \"content\": \"<text>\"}]}. `add` creates a new section; `replace` swaps "
    "a section's body; `delete` removes a section. NEVER rewrite the whole document. Propose at most the "
    "requested number of edits, each justified by the evidence. Output ONLY the JSON object."
)


def build_edit_prompt(*, name: str, persona_role: str, persona_tone: str,
                      current_doc: str, evidence: str, lr_budget: int) -> str:
    return (
        f"Agent: {name}\nRole: {persona_role}\nTone: {persona_tone}\n\n"
        f"Current instruction document:\n{current_doc}\n\n"
        f"Evidence from recent scored tasks (weak spots to address):\n{evidence}\n\n"
        f"Propose at most {lr_budget} bounded section edit(s) as the JSON described."
    )

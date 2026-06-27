"""Prompt: distill a GitHub repo into a reusable SKILL.md technique pack."""
from __future__ import annotations

SKILL_SUGGEST_SYSTEM = (
    "Distill this GitHub repo's core technique/approach into a reusable Arslan skill — an "
    "INSTRUCTION pack (not code). Respond with ONLY a JSON object: "
    "{\"name\": \"<short skill name>\", \"category\": \"<one word, e.g. research/creative/data>\", "
    "\"description\": \"<one line>\", \"body\": \"<markdown>\"}. The body MUST contain a "
    "`## Trigger` section (when a spawn should apply this technique) and a `## 决策规则` section "
    "(the concrete steps/rules). Keep the body practical and self-contained. If the repo is not a "
    "technique worth distilling, still return your best-effort skill — but the body must have both sections."
)

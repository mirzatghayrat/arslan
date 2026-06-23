"""Prompt for pairwise compare-judge (kept separate for easy iteration)."""
from __future__ import annotations

COMPARE_SYSTEM = (
    "You compare two candidate outputs (输出① and 输出②) for the SAME task by the SAME agent. "
    "Decide, per dimension, which is better on 0-10 quality:\n"
    "- fabrication: which invents fewer ungrounded facts/data/sources?\n"
    "- identity: which better keeps the agent's persona (no wrong name/role)?\n"
    "- completion: which more fully satisfies the task?\n"
    "Also give an overall winner and a margin (0-10, how much the overall winner leads; 0 if tie).\n"
    "Reply with ONE JSON object and nothing else:\n"
    '{"dimensions":{"fabrication":"1|2|tie","identity":"1|2|tie","completion":"1|2|tie"},'
    '"overall":"1|2|tie","margin":<0-10>,"reason":"<one short sentence>"}\n'
    'Use "1" if 输出① is better, "2" if 输出② is better, "tie" if equal. '
    "Write the reason in the user's language."
)


def build_prompt(*, task: str, persona: str, first: str, second: str) -> str:
    return (
        f"Task:\n{task}\n\n"
        f"Agent persona:\n{persona}\n\n"
        f"输出①:\n{first}\n\n"
        f"输出②:\n{second}\n"
    )

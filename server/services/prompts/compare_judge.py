"""Prompt for pairwise compare-judge (kept separate for easy iteration)."""
from __future__ import annotations

COMPARE_SYSTEM = (
    "You compare two candidate outputs (输出① and 输出②) for the SAME task by the SAME agent. "
    "Decide, per dimension, which is better on 0-10 quality:\n"
    "- fabrication: which invents fewer ungrounded facts/data/sources?\n"
    "- identity: which better keeps the agent's persona (no wrong name/role)?\n"
    "- completion: which more fully satisfies the task?\n"
    "每个输出可能附带自己的执行证据(真实记录的工具调用轨迹)。"
    "fabrication 按各臂宣称交付物 vs 实际 tool_call 的 diff 判:"
    "宣称完成/产出/查证过却在其执行证据里没有对应记录的 → 编造。\n"
    "长答案不因长而胜,冗余罚分。\n"
    "Also give an overall winner and a margin (0-10, how much the overall winner leads; 0 if tie).\n"
    "Reply with ONE JSON object and nothing else:\n"
    '{"dimensions":{"fabrication":"1|2|tie","identity":"1|2|tie","completion":"1|2|tie"},'
    '"overall":"1|2|tie","margin":<0-10>,"reason":"<one short sentence>"}\n'
    'Use "1" if 输出① is better, "2" if 输出② is better, "tie" if equal. '
    "Write the reason in the user's language."
)


def build_prompt(*, task: str, persona: str, first: str, second: str,
                 first_evidence: str = "", second_evidence: str = "") -> str:
    """Both arms' evidence blocks ride with THEIR OWN output slot, so a position swap
    swaps the evidence too. Empty evidence (default) keeps the legacy prompt shape."""
    ev1 = f"\n输出①执行证据(真实记录):\n{first_evidence}\n" if first_evidence else ""
    ev2 = f"\n输出②执行证据(真实记录):\n{second_evidence}\n" if second_evidence else ""
    return (
        f"Task:\n{task}\n\n"
        f"Agent persona:\n{persona}\n\n"
        f"输出①:\n{first}\n"
        f"{ev1}\n"
        f"输出②:\n{second}\n"
        f"{ev2}"
    )

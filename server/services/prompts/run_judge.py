"""Judge prompt for single-run evaluation (kept separate for easy iteration)."""
from __future__ import annotations

JUDGE_SYSTEM = (
    "You are a strict but fair evaluator of an AI orchestrator's single task run. "
    "You are given the user's request, which specialist spawn was chosen (and the "
    "available roster), the spawn's persona, and the spawn's final output. "
    "Rate the run on EXACTLY four dimensions, each 0-10:\n"
    "- routing: was the RIGHT spawn chosen for this request (vs the roster)?\n"
    "- fabrication: did the output avoid inventing facts/data/sources not grounded "
    "in the request or tool results?\n"
    "- identity: did the reply stay in the chosen spawn's persona without bleeding "
    "another identity (no wrong name/role)?\n"
    "- completion: how fully did it satisfy the request?\n"
    "Reply with ONE JSON object and nothing else:\n"
    '{"dimensions": {"routing": {"status": "pass|warn|fail", "score": <0-10>, '
    '"comment": "<one short human sentence>"}, "fabrication": {...}, "identity": {...}, '
    '"completion": {...}}, "overall": {"score": <0-10>, "badge": "good|ok|bad"}}\n'
    "Use status fail for score<=3, warn for 4-6, pass for >=7. Write comments in the "
    "user's language. Be concise."
)


# HX-5 A4: deterministic pre-check line injected when the run's final output carries
# promise language (promise_guard.PROMISE_RE) but the run recorded zero tool_call steps.
FABRICATION_PRECHECK_LINE = (
    "确定性预检: 输出宣称正在进行的工作,但本次运行没有任何对应工具调用/派发 — "
    "fabrication 风险,评分时应扣分。"
)


def build_prompt(*, user_message: str, spawn_name: str | None, roster: str,
                 persona: str, output: str, fabrication_signal: bool = False) -> str:
    precheck = f"{FABRICATION_PRECHECK_LINE}\n\n" if fabrication_signal else ""
    return (
        f"{precheck}"
        f"User request:\n{user_message}\n\n"
        f"Chosen spawn: {spawn_name or '(none)'}\n\n"
        f"Available roster:\n{roster}\n\n"
        f"Chosen spawn persona:\n{persona}\n\n"
        f"Spawn final output:\n{output}\n"
    )

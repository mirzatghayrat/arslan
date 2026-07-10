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

# E1: instruction attached to the step-evidence block — fabrication is judged as the
# diff between what the output CLAIMS was done/delivered and the tool_calls that were
# ACTUALLY recorded in the trace below.
FABRICATION_EVIDENCE_LINE = (
    "fabrication 按宣称交付物 vs 实际 tool_call 的 diff 判:输出中宣称完成/产出/查证过的内容,"
    "必须能对应到上方步骤证据里真实记录的工具调用或派发;宣称了却没有对应记录 → 编造,扣分。"
)

# E1: auto-continue rounds are each recorded as their own Run; judging their
# completion against the FULL original request systematically skews the score down.
CONTINUATION_LINE = (
    "这是多轮任务的中间轮,completion 按本轮增量目标评,不按完整请求评。"
)


def build_prompt(*, user_message: str, spawn_name: str | None, roster: str,
                 persona: str, output: str, fabrication_signal: bool = False,
                 evidence: str = "", continuation: bool = False) -> str:
    precheck = f"{FABRICATION_PRECHECK_LINE}\n\n" if fabrication_signal else ""
    cont = f"{CONTINUATION_LINE}\n\n" if continuation else ""
    # No recorded steps → no evidence section at all (never fabricate evidence).
    evidence_block = (
        f"\nStep evidence (本次运行真实记录的执行步骤):\n{evidence}\n"
        f"{FABRICATION_EVIDENCE_LINE}\n"
        if evidence else ""
    )
    return (
        f"{precheck}{cont}"
        f"User request:\n{user_message}\n\n"
        f"Chosen spawn: {spawn_name or '(none)'}\n\n"
        f"Available roster:\n{roster}\n\n"
        f"Chosen spawn persona:\n{persona}\n\n"
        f"Spawn final output:\n{output}\n"
        f"{evidence_block}"
    )

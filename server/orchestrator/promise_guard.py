"""HX-1 A2 — 空头支票拦截 (deterministic promise interceptor).

Live incident: the router said route→spawn, the doer-first gate diverted to Arslan's
self-answer, and the answer LLM fabricated "我把 PPT 交给 Deck Master 来生成,它正在生成中,
稍等" — no dispatch ever happened (zero runs). Nothing caught it.

This module is the deterministic catch: regexes that flag "claimed-but-never-dispatched
handoff / background work" language in a FINAL answer, plus ONE bounded correction step.
The caller (arslan._handle_answer) applies it only when the turn's runtime state shows
no dispatch and no tool_call, so honest narration of real work never trips it.

Bounded by construction: at most one LLM re-synthesis attempt; if that attempt ALSO
promises, a fixed honest template is used. Never loops. Fail-open: any error inside the
correction step degrades to the template; the caller additionally wraps the whole guard.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Generic empty-promise language (tier 2, and half of tier 1's union).
# NOTE — deliberate deviation from the spec sketch: the 交给…(生成|…) gap is 0,20 (spec
# sketched 0,12) because the real incident string has 14 chars between 交给 and 生成
# ("交给 Deck Master 来生成" — an English spawn name in the gap). 0,12 missed the incident.
PROMISE_RE = re.compile(
    r"正在生成|正在为你|稍等|马上(?:就好|给你)|已交给"
    r"|交给.{0,20}?(?:生成|制作|处理|来做)"
    r"|working on|generating|in progress"
    r"|I(?:'|’)ll (?:get|have)",
    re.IGNORECASE,
)


def spawn_promise_re(spawn_name: str) -> re.Pattern[str]:
    """High-precision tier-1 pattern: a handoff claim naming THIS spawn ("交给/让/派/
    hand(ed) (it) to … <name>"). Used only on the doer-first divert branch, where the
    inferred spawn's name is known and any handoff claim is structurally false."""
    name = re.escape((spawn_name or "").strip())
    return re.compile(
        rf"(?:交给|让|派|hand(?:ed)?\s+(?:it\s+)?to).{{0,10}}?{name}",
        re.IGNORECASE,
    )


def find_promise(text: str, spawn_name: str | None = None) -> str | None:
    """The matched promise snippet in `text` (PROMISE_RE ∪ spawn_promise_re), or None."""
    t = text or ""
    m = PROMISE_RE.search(t)
    if m is None and spawn_name:
        m = spawn_promise_re(spawn_name).search(t)
    return m.group(0) if m else None


# The literal truth statement the re-synthesis prompt MUST carry (acceptance #1: the
# correction is grounded in the turn's real state, not a generic "be honest" nudge).
_TRUTH_STATEMENT = "你本回合没有交办任何任务给任何分身——刚才那段话里的“交办/生成中”是不实的"

_CORRECTION_SYS = (
    "你是 Arslan。系统没有后台执行,你上一条回复向用户虚报了进度,需要立刻更正。"
    "只输出一段简短(一两句)的诚实更正,用用户的语言;"
    "绝不要再出现“正在/稍等/马上/已交给/交给某某生成(处理)”这类进行中或已派发的说法。"
)


def _correction_user(full_text: str, spawn_name: str | None) -> str:
    who = f"(那段话把任务说成已交给「{spawn_name}」)" if spawn_name else ""
    return (
        f"事实:{_TRUTH_STATEMENT}{who}。\n\n"
        f"你刚才的回复原文:\n{(full_text or '')[:2000]}\n\n"
        "请输出更正:如实说明上面的内容是你自己作答的,没有任何任务被派发、也没有任何东西"
        "正在后台生成;如果用户确实想交给某个分身,提示他们直接点名(@分身名)即可。"
        "只输出更正文本本身,不要解释。"
    )


def _fallback_template(spawn_name: str | None) -> str:
    if spawn_name:
        return (f"更正:我刚才说交给 {spawn_name} 处理并不属实——本回合我没有派发任何任务,"
                f"上面的内容是我自己作答的。需要真的交给 {spawn_name},直接点名它即可。")
    return ("更正:本回合我没有派发任何任务,也没有任何东西正在后台运行——"
            "上面的内容是我自己作答的。")


async def correct(full_text: str, *, spawn_name: str | None = None) -> dict | None:
    """Detect + bounded-correct. Returns None when `full_text` carries no promise
    language; otherwise {"correction": str, "pattern": matched snippet, "corrected":
    bool} where corrected=True means the LLM re-synthesis passed the same regex gate
    (False = deterministic template). At most ONE extra LLM call, never loops."""
    snippet = find_promise(full_text, spawn_name)
    if snippet is None:
        return None
    try:
        from server.orchestrator import tool_loop
        adapter = tool_loop._get_adapter()
        a = await adapter if hasattr(adapter, "__await__") else adapter
        resp = await a.chat(_CORRECTION_SYS, _correction_user(full_text, spawn_name))
        candidate = (getattr(resp, "content", None) or "").strip()
        if candidate and find_promise(candidate, spawn_name) is None:
            return {"correction": candidate, "pattern": snippet, "corrected": True}
        logger.warning("promise correction re-synthesis also promised — using template")
    except Exception as exc:  # noqa: BLE001 — correction must never break the turn
        logger.warning("promise correction re-synthesis failed (using template): %s", exc)
    return {"correction": _fallback_template(spawn_name), "pattern": snippet,
            "corrected": False}

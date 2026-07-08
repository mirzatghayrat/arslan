"""PA-2 短确认词表 — deterministic bilingual short-confirm detection (验收②).

Live incident (thread-1783523936187): the router said route→spawn 6 FIVE consecutive
times, the user kept answering with bare confirmations ("好", "可以", "直接出"), and the
doer-first gate self-answered every single turn — the outline was re-pasted 3×. This
module is the deterministic half of the escape hatch: recognize a bare confirmation /
impatience message so the delegation MUST advance instead of diverting again.

Zero LLM by construction (验收②): normalize (trim + lowercase + strip edge punctuation
and emoji), then exact-match or prefix-match against a fixed bilingual lexicon. A
LENGTH CAP keeps a long message that merely STARTS with 可以/ok but carries new spec
info out of scope — the consecutive-route rule in arslan._handle_route covers those.
"""
from __future__ import annotations

import re

# Normalized (lowercase) lexicon entries. Matching rules in is_short_confirm():
#   - every entry matches the WHOLE normalized message exactly;
#   - entries of length >= 2 also match as a PREFIX ("开始吧啦" hits "开始吧");
#   - single-character entries are exact-only ("可" must not swallow "可是我不想要",
#     "行" must not swallow "行不行");
#   - an ASCII-ending entry only prefix-matches on a word boundary ("go" never
#     matches "google it").
ENTRIES: tuple[str, ...] = (
    # ---- Chinese confirmations ----
    "好", "好的", "好啊", "好嘞", "嗯", "嗯嗯", "行", "可以", "可",
    "就这样", "就这个", "直接出", "直接做", "直接来",
    "开始", "开始吧", "继续", "来吧", "做吧", "出吧", "快点",
    # ---- Chinese impatience (the incident's "why is nothing happening" shape) ----
    "怎么还不", "怎么还没", "几轮了", "还没好吗",
    # ---- English ----
    "go", "yes", "y", "ok", "okay", "sure", "yep", "yeah",
    "do it", "go ahead", "proceed", "continue", "why not", "still waiting",
)

# A short confirm is SHORT: past this many normalized chars the message is carrying
# new spec info, not a bare confirmation — the consecutive-route rule handles it.
MAX_NORMALIZED_LEN = 16

# Edge junk = anything that isn't a word character (unicode-aware: CJK is \w;
# punctuation, whitespace and emoji are not), stripped from BOTH ends only —
# internal punctuation is meaningful ("可以,但是……" must NOT normalize to "可以但是").
_EDGE_JUNK = re.compile(r"^[\W_]+|[\W_]+$")
_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """trim + lowercase + strip leading/trailing punctuation & emoji + collapse spaces."""
    t = (text or "").strip().lower()
    t = _EDGE_JUNK.sub("", t)
    return _WS.sub(" ", t)


def is_short_confirm(text: str) -> bool:
    """True when `text` is a bare bilingual confirmation/impatience message.

    Deterministic — pure normalization + lexicon lookup, no LLM (验收②)."""
    t = normalize(text)
    if not t or len(t) > MAX_NORMALIZED_LEN:
        return False
    for entry in ENTRIES:
        if t == entry:
            return True
        if len(entry) < 2 or not t.startswith(entry):
            continue  # single-char entries are exact-only
        nxt = t[len(entry)]
        if entry[-1].isascii() and entry[-1].isalnum() and nxt.isascii() and nxt.isalnum():
            continue  # mid-ASCII-word ("go" inside "google") is not a confirm
        return True
    return False

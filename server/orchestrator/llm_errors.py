"""Turn a provider's billing / auth / rate refusal into something actionable.

WHY: OpenRouter answers a capped key with a wall of JSON — "requires more
credits, or fewer max_tokens… you requested up to 65536 tokens, but can only
afford 64381" — and we rendered it verbatim in the chat bubble, key-id URL and
all. Three different faults (empty account, capped key, oversized request) all
look identical in that blob, and none of the three remedies is obvious.

DELIBERATELY NARROW, for the same reason vision_errors is: mislabelling an
unrelated fault sends someone off topping up an account that was never the
problem. Anything unrecognised returns None and the raw error still shows.
"""
from __future__ import annotations

import re

# A key-level cap is NOT an empty account: the money may be there, sitting
# behind a per-key limit the user set and forgot. Different remedy, different
# sentence, and the metadata is what distinguishes them.
_KEY_LIMIT = re.compile(r"openrouter_key_limit|api key's usage limit", re.I)
_PAYMENT = re.compile(r"402|payment required|insufficient (credits|balance|funds)", re.I)
_AUTH = re.compile(r"401|unauthorized|invalid[_ ]api[_ ]key|authentication", re.I)
_RATE = re.compile(r"429|too many requests|rate.?limit", re.I)
_CONTEXT = re.compile(r"context[_ ]length|maximum context", re.I)


def explain(raw_error: str) -> str | None:
    """A short, actionable sentence, or None when we do not recognise the fault."""
    raw = raw_error or ""
    if not raw.strip():
        return None

    # Context length first: it co-occurs with token counts that read like money.
    if _CONTEXT.search(raw):
        return ("这轮对话太长,超过了这个模型的上下文上限。"
                "开一个新会话,或换一个上下文更大的模型。")

    if _PAYMENT.search(raw):
        if _KEY_LIMIT.search(raw):
            # The distinction worth drawing: the account may be funded and this
            # still fails, because the cap is on the key.
            return ("这把 API key 设了额度上限,已经触顶——账户里可能还有余额。"
                    "去 openrouter.ai/settings/keys 调高或去掉这把 key 的上限,"
                    "或换一把没有上限的 key。")
        return "这个模型的账户余额不足,去 provider 后台充值后再试。"

    if _AUTH.search(raw):
        return ("这个 provider 拒绝了 API key(无效、过期或权限不足)。"
                "去设置里换一把新的 key。")

    if _RATE.search(raw):
        return "provider 限流了(请求太频繁)。稍等一会儿再试,或换一个模型分担。"

    return None

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
_KEY_LIMIT = re.compile(
    # OpenRouter says this two different ways with two different STATUS CODES:
    # 402 with `openrouter_key_limit` metadata, and 403 "Key limit exceeded
    # (total limit)". The sentence below existed for the 402 form only and was
    # therefore unreachable for the 403 one — a written answer that could never
    # be shown. Measured against a real key on 2026-08-24.
    r"openrouter_key_limit|api key's usage limit|key limit exceeded", re.I)
_PAYMENT = re.compile(r"402|payment required|insufficient (credits|balance|funds)", re.I)
# A model the account may not use FROM HERE. Not a key fault and not a money
# fault, and it is the one that looks most like both: same 403, same wall of
# JSON, and the remedy (change model, or change where the traffic leaves from)
# has nothing to do with either.
_REGION = re.compile(
    r"not available in your region|unsupported[_ ]country|region[_ ]not[_ ]supported"
    r"|country[,.]? region[,.]? or territory", re.I)
_AUTH = re.compile(r"401|unauthorized|invalid[_ ]api[_ ]key|authentication", re.I)
_RATE = re.compile(r"429|too many requests|rate.?limit", re.I)
_CONTEXT = re.compile(r"context[_ ]length|maximum context", re.I)
# The request never reached the provider at all. Kept to failures of the
# TRANSPORT, not of anything the provider said — a server that answers, even
# with a refusal, is not this.
_TRANSPORT = re.compile(
    r"\bssl\b|certificate[_ ]verify|handshake|"
    r"connect(ion)?\s*(error|refused|reset|aborted|timed?\s*out)|"
    r"connecterror|connecttimeout|readtimeout|"
    r"eof occurred|remote end closed|econnreset|econnrefused|"
    r"network is unreachable|temporary failure in name resolution|"
    r"nodename nor servname|name or service not known|failed to establish",
    re.I)


def explain(raw_error: str) -> str | None:
    """A short, actionable sentence, or None when we do not recognise the fault."""
    raw = raw_error or ""
    if not raw.strip():
        return None

    # Context length first: it co-occurs with token counts that read like money.
    if _CONTEXT.search(raw):
        return ("这轮对话太长,超过了这个模型的上下文上限。"
                "开一个新会话,或换一个上下文更大的模型。")

    # Transport first: nothing the provider says can be in a message it never
    # sent. Putting this later would let a stray "401" inside a proxy's error
    # page be read as an auth refusal — which is exactly the wrong direction,
    # because it sends someone to replace a key that was never the problem.
    if _TRANSPORT.search(raw):
        return ("没能连上这个 provider——请求根本没送出去,不是 key 的问题。"
                "多半是网络、代理或 VPN:确认它们在工作,或把这个 provider 的域名设成直连。")

    # A key cap answers with BOTH 402 and 403 depending on the provider, so this
    # is checked before either of them rather than nested inside one.
    if _KEY_LIMIT.search(raw):
        return ("这把 API key 设了额度上限,已经触顶——账户里可能还有余额。"
                "去 openrouter.ai/settings/keys 调高或去掉这把 key 的上限,"
                "或换一把没有上限的 key。")

    if _REGION.search(raw):
        return ("这个模型在你所在的地区不可用(provider 按出口 IP 判断),"
                "和 key、余额都无关。换一个没有地区限制的模型,"
                "或让流量从支持的地区出去。")

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

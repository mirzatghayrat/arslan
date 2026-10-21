"""Deterministic prompt-size estimates; NOT a vendor tokenizer or billing meter.

0.1.63 K4b: the one token estimator. The adapter's no-usage fallback used its own copy
(llm/usage_sink.py) that counted only Han characters; it now uses this one, so kana and
Hangul count the same everywhere.
"""

# What one image contributes to the ESTIMATE. Providers bill images by tile and
# fold the result into input_tokens, so an exact number is not knowable here —
# and the ledger cannot attribute it either (spec §0.7). A fixed, deliberately
# rough placeholder beats the two wrong answers available: counting the base64
# characters as prose (~5 000 tokens for a small screenshot), or counting zero.
_IMAGE_TOKEN_GUESS = 800


def _flatten(part: object) -> str:
    """A part may be a plain string OR a neutral block list (build_messages' contract).
    Never raises: the adapter calls this on the no-usage-frame FALLBACK path, where an
    exception would be the second failure on top of whatever already went wrong."""
    if part is None:
        return ""
    if isinstance(part, str):
        return part
    if isinstance(part, list):
        return "".join(_flatten(b) for b in part)
    if isinstance(part, dict):
        if part.get("type") == "image":
            # Stand in for the image without letting its base64 reach the
            # character count. 'x' * n is the cheapest way to say "n tokens"
            # in a function whose whole vocabulary is characters.
            return "x" * (_IMAGE_TOKEN_GUESS * 4)
        return str(part.get("text", ""))
    return str(part)


def estimate_tokens(*parts: object) -> int:
    """Han, kana and Hangul ~1 token per character; everything else ~4 characters per token."""
    text = "".join(_flatten(p) for p in parts)
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿" or "぀" <= ch <= "ヿ" or "가" <= ch <= "힯")
    return cjk + (len(text) - cjk) // 4


def clip(text: str, budget: int) -> str:
    """Largest prefix inside the same estimate used for admission, including CJK."""
    if budget <= 0:
        return ""
    if estimate_tokens(text) <= budget:
        return text
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if estimate_tokens(text[:mid]) <= budget:
            low = mid
        else:
            high = mid - 1
    return text[:low]

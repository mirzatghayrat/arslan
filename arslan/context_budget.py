"""Deterministic prompt-size estimates; NOT a vendor tokenizer or billing meter."""


def estimate_tokens(text: str) -> int:
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

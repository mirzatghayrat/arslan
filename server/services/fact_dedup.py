"""Near-duplicate test for memory text (`similar`, used by memory_compat). 0.1.63 C2a-2 removed the v1
user_facts dedup (POST /facts/dedup's backfill and the rule-supersede direction check), which no boot reached
once memory v2 was always active."""
from __future__ import annotations

import difflib

_SIM_THRESHOLD = 0.85          # 0.6 → 0.85:短 CJK 事实(喜欢猫/喜欢狗=0.667)不再误撞
_MIN_CONTAINMENT_LEN = 8       # containment 仅当两串均 >= 8 字符(短串禁用)


def norm(content: str) -> str:
    """Normalization key: trim + collapse inner whitespace + ASCII-lowercase
    (CJK unaffected by lower())."""
    return " ".join((content or "").split()).lower()


def similar(a: str, b: str) -> bool:
    """Deterministic near-dup: exact-norm equal; containment only when BOTH sides
    >= _MIN_CONTAINMENT_LEN chars; or difflib ratio >= _SIM_THRESHOLD. difflib is
    used (not token overlap) because it works across CJK. No embeddings (v1)."""
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if min(len(na), len(nb)) >= _MIN_CONTAINMENT_LEN and (na in nb or nb in na):
        return True
    return difflib.SequenceMatcher(None, na, nb).ratio() >= _SIM_THRESHOLD

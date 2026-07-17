"""Deterministic text chunking for the knowledge base (CJK-friendly, boundary-aware)."""
from __future__ import annotations

import re

_PARA = "\n\n"
# 句子边界:CJK 全角终止符 / 半角终止符后接空白 / 换行
_SENT_BOUNDARY = re.compile(r"(?<=[。!?!?;;\n])|(?<=[.])(?=\s)")


def _find_cut(text: str, start: int, size: int) -> int:
    """[start+0.6*size, start+size] 窗口内从后往前找切点:段落边界 > 句子边界 >
    start+size 硬切(超长无标点回退)。到文末直接收尾。"""
    hard = start + size
    if hard >= len(text):
        return len(text)
    lo = start + int(size * 0.6)
    window = text[lo:hard]
    p = window.rfind(_PARA)
    if p > 0:
        return lo + p + len(_PARA)
    best = -1
    for m in _SENT_BOUNDARY.finditer(window):
        if m.start() > 0:
            best = m.start()
    if best > 0:
        return lo + best
    return hard


def chunk_text(text: str, *, size: int = 800, overlap: int = 100) -> list[str]:
    """Split text into ~size-char chunks preferring paragraph/sentence boundaries,
    with `overlap` chars shared between consecutive chunks. Whitespace-only/empty
    → []. Char-based lengths(CJK 正确)。进度地板 max(start+1, cut-overlap) 保证
    任意 size/overlap 组合终止(P0-c I3)。"""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        cut = _find_cut(text, start, size)
        piece = text[start:cut].strip()
        if piece:
            chunks.append(piece)
        if cut >= len(text):
            break
        start = max(start + 1, cut - overlap)
    return chunks

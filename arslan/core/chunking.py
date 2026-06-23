"""Deterministic text chunking for the knowledge base (CJK-friendly, char-based)."""
from __future__ import annotations


def chunk_text(text: str, *, size: int = 800, overlap: int = 100) -> list[str]:
    """Split text into ~size-char chunks with `overlap` chars shared between
    consecutive chunks. Whitespace-only / empty → []. Char-based (no word
    tokenization) so CJK text chunks correctly."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    step = max(1, size - overlap)
    chunks: list[str] = []
    start = 0
    while start < len(text):
        piece = text[start:start + size].strip()
        if piece:
            chunks.append(piece)
        start += step
    return chunks

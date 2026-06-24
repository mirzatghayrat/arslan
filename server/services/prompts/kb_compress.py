"""Prompt to clean ingested knowledge text before chunking (claude-mem 'compress')."""
from __future__ import annotations

COMPRESS_SYSTEM = (
    "You clean a document for a knowledge base. Remove boilerplate, navigation, ads, "
    "cookie notices, repeated headers/footers, and obvious noise. KEEP ALL substantive "
    "information verbatim — do NOT summarize, paraphrase, or drop facts, numbers, names, "
    "or steps. Output only the cleaned text, no preamble."
)

"""Prompt-cache-friendly system prompt: a stable prefix + a volatile suffix.

Background (spec 2026-07-13-prompt-cache-reorder): prompt caching is a prefix match —
any byte change anywhere in the prefix invalidates the cache for everything after it.
Arslan's answer assembly used to interleave a MINUTE-level timestamp (and roster / facts /
summary / KB) into the middle of the static guard prompt, so every turn cache-missed all
the dynamic tail. The fix is to split assembly into a byte-stable ``stable_prefix`` (the
static guards) and a ``volatile_suffix`` (everything per-turn/per-conversation, timestamp
last), and to give the Anthropic adapter enough structure to place a single cache_control
breakpoint on the stable prefix.

`CachedSystem` is the seam. It IS a plain ``str`` whose value is exactly
``stable + volatile`` (no injected separator — byte-identical to the old direct
concatenation), so every consumer that treats the system as text — DeepSeek/OpenAI/Ollama
request bodies, logging, token estimation — works transparently and unchanged. It
additionally carries ``.stable`` / ``.volatile`` so the Anthropic provider can emit a
content-block array with ``cache_control`` on the stable block. This is the explicit
structured seam the spec calls for (over string-sniffing a boundary marker).

Concatenation (``system + more``) appends to the VOLATILE part and returns a new
CachedSystem, so callers that tack on more static text after assembly (tool_loop.run_native
appends its research-discipline + injection-defense guards; the forced-step nudge; the
plain-answer salvage) keep the split intact WITHOUT polluting the byte-stable prefix. Those
trailing guards are static, but they already sat AFTER the dynamic tail in the pre-reorder
prompt, so keeping them in the volatile block is behavior-preserving (the model sees the
same text in the same order) — they just aren't cached, which is a negligible loss.
"""
from __future__ import annotations


class CachedSystem(str):
    """A system prompt string that remembers its stable-prefix / volatile-suffix split.

    Value == ``stable + volatile`` (no separator injected). ``.stable`` must be
    byte-for-byte identical across turns — it is the cacheable prefix.
    """

    stable: str
    volatile: str

    def __new__(cls, stable: str, volatile: str) -> "CachedSystem":
        obj = super().__new__(cls, stable + volatile)
        obj.stable = stable
        obj.volatile = volatile
        return obj

    def __add__(self, other: str) -> "CachedSystem":
        # Append to VOLATILE — never the stable prefix. Trailing text tacked on by the
        # tool loop (static guards, forced-step nudge, salvage suffix) must not shift the
        # cacheable prefix, so it lands in the un-cached volatile block.
        return CachedSystem(self.stable, self.volatile + str(other))

    # No __radd__: `plain_str + CachedSystem` falls through to str.__add__, which returns
    # a plain str with the correct value (stable+volatile+…) and no split — the Anthropic
    # adapter then treats it as an ordinary string (no cache block). Safe, and this path is
    # not exercised by the assembly/tool-loop code.

    def __reduce__(self):  # keep pickle/copy round-trips faithful to the split
        return (CachedSystem, (self.stable, self.volatile))


def build_cached_system(stable_prefix: str, volatile_suffix: str) -> CachedSystem:
    """Concatenate a byte-stable prefix with a per-turn volatile suffix.

    Contract:
      - ``stable_prefix`` MUST be byte-for-byte identical across turns (static guards
        only — no timestamps, roster, facts, summary, KB, or per-turn addenda).
      - ``volatile_suffix`` holds everything that varies per turn / per conversation.

    The returned value is a plain-``str``-compatible object whose text is exactly
    ``stable_prefix + volatile_suffix`` (no injected boundary — the volatile pieces already
    self-delimit with leading blank lines, so this stays byte-identical to the old
    ``a + b + c…`` assembly).
    """
    return CachedSystem(stable_prefix, volatile_suffix)

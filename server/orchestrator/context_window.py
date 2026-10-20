"""How much conversation history a turn may carry, by the model's context window (K2).

The window comes from the static family table below, NOT from the model catalog: the chat path
never reads ModelCatalogCache (its docstring in server/db/models.py: the cache is a Settings-only
surface, filled from the network, often stale or empty — DeepSeek's /models carries no window).
⓪Plan decided this for K2 on 2026-10-20 (plan correction E26). An unknown model gets a
conservative default; the run records which one was used (Budget.note_history), so M2 can count
how often that happens.
"""
from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlsplit

# The rest of the window holds the system prompt, the tools, the new message and the reply.
FRACTION = 0.4
# The fixed history budget before K2: no model gets less history than it had then.
FLOOR = 3000
# Bounds the cost of history on big windows (estimated tokens per request).
CAP = 24_000
# Small on purpose: too small only costs history (the floor still holds), too large overflows a
# small model, and the cap already handles big windows.
DEFAULT_WINDOW = 32_000
# Ollama serves a model with a small context unless the user raised it, whatever the model's own
# window (③Hands' review: deepseek-r1:8b matched the 128k family). Any Ollama connection, LAN
# included: the limit comes from how it serves, not from where it runs.
LOCAL_WINDOW = 8_192

# Substrings of the lower-cased model id; the longest match wins. Only windows the vendors publish.
# The local families (served through Ollama and the like) are listed at the window they are
# usually SERVED with, which is far below the model's own: the server's default context is small
# unless the user raised it. The same names through a cloud provider then get the floor, today's
# budget — conservative, never less than before.
_FAMILIES: dict[str, int] = {
    "deepseek": 128_000,      # DeepSeek API: 128K
    "claude": 200_000,        # Anthropic: 200K standard
    "gpt-4o": 128_000,        # OpenAI: 128K
    "gpt-4.1": 1_047_576,     # OpenAI: 1,047,576
    "gpt-5": 400_000,         # OpenAI: 400K
    "gemini": 1_048_576,      # Google: 1,048,576 (1.5 and later)
    "llama": 8_192,           # local
    "mistral": 8_192,         # local
    "gemma": 8_192,           # local
    "phi": 8_192,             # local
}


def window_for(model: str | None, *, provider: str | None = None, base_url: str = "") -> tuple[int, str]:
    """(window, "table" | "default" | "local") for a model id, provider prefixes and case ignored."""
    if (provider or "").casefold() == "ollama" or _self_hosted(base_url):
        return LOCAL_WINDOW, "local"
    name = (model or "").lower()
    matches = [family for family in _FAMILIES if family in name]
    if not matches:
        return DEFAULT_WINDOW, "default"
    return _FAMILIES[max(matches, key=len)], "table"


def _self_hosted(base_url: str) -> bool:
    """Whether an endpoint looks like a server of the user's own: LM Studio, llama.cpp, local vLLM
    connect as "OpenAI-compatible" and serve a small context by default (③Hands' K2a review). This
    machine, an address that is not on the internet (LAN, Tailscale), a name without a dot or under
    .local / .lan / .internal / .home.arpa. Only for sizing history, where small is the safe guess
    (never below FLOOR); never a privacy decision: that is arslan.llm.locality's, and stricter."""
    try:
        host = (urlsplit(base_url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    try:
        return not ip_address(host).is_global
    except ValueError:
        pass
    return host == "localhost" or "." not in host or host.endswith(
        (".localhost", ".local", ".lan", ".internal", ".home.arpa"))


def history_budget(window: int) -> int:
    """Estimated tokens of history for a window: its fraction, between the floor and the cap."""
    return max(FLOOR, min(CAP, int(window * FRACTION)))

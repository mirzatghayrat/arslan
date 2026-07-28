"""Whether an installed capability can actually be used on your setup.

WHY THIS EXISTS: the Capability Library shows what is INSTALLED. Nothing showed
what would actually RUN. Measured on the wire (tests/server/test_capability_fitness.py
captures the real request body rather than reading the source):

    openai-compatible   tools ARE sent
    anthropic direct    tools are DROPPED
    gemini              tools are DROPPED

On the two that drop them, every MCP tool and every native tool a spawn is
equipped with is silently inert. The equipment page says "equipped", the model
is never told the tool exists, and nothing anywhere says so. A user watching
their agent ignore a tool they just installed has no way to learn why.

THE RULE THIS MODULE ENFORCES: a capability is never assumed to work. Each cell
is one of three states, and "unverified" is a real answer — the point is to stop
an unmeasured capability from rendering as a green tick.

    supported     measured, and it works here
    unsupported   measured, and it does not
    unverified    nobody has measured this — say so

The table below is a CLAIM. test_capability_fitness re-measures the wire payload
and fails if the claim and the wire disagree, so this cannot rot into decoration
the way a hand-maintained matrix normally does.
"""
from __future__ import annotations

SUPPORTED = "supported"
UNSUPPORTED = "unsupported"
UNVERIFIED = "unverified"

#: Does this provider transmit tool schemas to the model at all? Without that,
#: no tool of any kind can be called, however it was installed.
#:
#: Keys are the provider identifiers used by the model catalog. A provider that
#: is not listed is UNVERIFIED — deliberately not "probably fine": the whole
#: failure this module addresses came from assuming an unmeasured path worked.
NATIVE_TOOL_CALLS: dict[str, str] = {
    "openai": SUPPORTED,
    "custom": SUPPORTED,        # OpenAI-compatible endpoints use the same payload
    "ollama": SUPPORTED,        # ditto
    "deepseek": SUPPORTED,      # ditto
    "anthropic": UNSUPPORTED,   # arslan/llm/providers/anthropic_provider.py builds no `tools`
    "gemini": UNSUPPORTED,      # arslan/llm/providers/gemini_provider.py builds no `tools`
}

#: Why, in words a user can act on. Never "not supported" alone — that reads as
#: a limit of their model rather than of this app, which would send them
#: shopping for a different subscription to fix our gap.
REASONS: dict[str, str] = {
    "anthropic": ("Arslan's direct Anthropic path sends text only — it does not "
                  "pass tool definitions to the model yet. Tools you install "
                  "will not be called while this provider is selected."),
    "gemini": ("Arslan's Gemini path sends text only — it does not pass tool "
               "definitions to the model yet. Tools you install will not be "
               "called while this provider is selected."),
}


def tool_calling_state(provider: str | None) -> str:
    """SUPPORTED / UNSUPPORTED / UNVERIFIED for this provider's tool transport."""
    if not provider:
        return UNVERIFIED
    return NATIVE_TOOL_CALLS.get(provider.strip().lower(), UNVERIFIED)


def tool_calling_reason(provider: str | None) -> str | None:
    """The sentence to show beside a capability that will not run, or None."""
    state = tool_calling_state(provider)
    if state == SUPPORTED:
        return None
    if state == UNVERIFIED:
        return ("This provider has not been measured against Arslan's tool "
                "transport. Tools may or may not be called — nobody has checked.")
    return REASONS.get((provider or "").strip().lower())


def assess(provider: str | None, capabilities: list[dict]) -> list[dict]:
    """Annotate each installed capability with whether it can run HERE.

    Takes the already-installed list rather than fetching it: this module makes
    no claim about what is installed, only about what would happen if it were
    used. Every entry gets a `fitness` — there is no "leave it blank and let the
    badge default to fine".
    """
    state = tool_calling_state(provider)
    reason = tool_calling_reason(provider)
    out = []
    for cap in capabilities:
        # A capability that does not depend on tool calling is unaffected by the
        # transport gap; skills injected as prompt text still work everywhere.
        needs_tools = bool(cap.get("needs_tool_calls", True))
        out.append({
            **cap,
            "fitness": SUPPORTED if not needs_tools else state,
            "fitness_reason": None if not needs_tools else reason,
        })
    return out

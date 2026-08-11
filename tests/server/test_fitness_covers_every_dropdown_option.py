"""Every provider the Settings dropdown offers must have a measured verdict.

The gap this closes was silent and pointed the wrong way. NATIVE_TOOL_CALLS was
keyed on the EXPANDED provider ("openai"), while the dropdown stores the PRESET
KEY ("qwen", "kimi", …) — see presets.provider_options, "the frontend renders
label, stores key". Eight of eleven options therefore answered UNVERIFIED, and
the Settings notice told users whose tools work perfectly that nobody had
checked. Over-warning is not the safe direction; it is just a different lie.

A key-by-key list would rot the moment someone adds a preset, so this derives
the expectation from the preset registry itself.
"""
from __future__ import annotations

from arslan.llm.presets import PRESETS, expand_preset
from server.services import capability_fitness as cf


def test_every_dropdown_option_has_a_verdict():
    """No option may answer UNVERIFIED — each is either measured good or bad."""
    unverified = [
        key for key in PRESETS if cf.tool_calling_state(key) == cf.UNVERIFIED
    ]
    assert not unverified, (
        f"these dropdown options have no measured verdict: {unverified}. "
        "Add them to NATIVE_TOOL_CALLS (and to web/src/lib/toolTransport.ts, "
        "which the lockstep test compares against)."
    )


def test_a_preset_verdict_matches_the_provider_it_expands_to():
    """The verdict on the stored key must equal the verdict on what it becomes.

    This is the actual invariant. A preset that expands to an OpenAI-compatible
    client transmits tools, whatever its key is called.
    """
    mismatched = {}
    for key in PRESETS:
        provider, _, _ = expand_preset(key, "", "")
        on_key = cf.tool_calling_state(key)
        on_expanded = cf.tool_calling_state(provider)
        if on_key != on_expanded:
            mismatched[key] = (on_key, on_expanded)
    assert not mismatched, f"key verdict != expanded-provider verdict: {mismatched}"


def test_a_provider_that_still_drops_tools_is_still_reported_broken():
    """Guards the other direction: this must not be satisfied by blanket approval.

    This test used to name anthropic here too. G1 gave the Anthropic adapter a real
    `tools` payload, so that half moved to SUPPORTED — and the assertion was UPDATED
    rather than deleted, because what it exists to catch is a table that says yes to
    everything. Gemini still builds no `tools`, so it holds the other direction on
    its own; the day Gemini is fixed, this test needs a provider that genuinely drops
    them or it stops guarding anything.

    The flip is not taken on faith: tests/llm/test_tool_transport.py captures the real
    Anthropic request body, so the table's claim is re-measured rather than asserted.
    """
    assert cf.tool_calling_state("gemini") == cf.UNSUPPORTED
    assert cf.tool_calling_state("anthropic") == cf.SUPPORTED, (
        "G1 put tool schemas on the Anthropic wire — if this is UNSUPPORTED again, "
        "either the transport regressed or the table drifted from it"
    )


def test_an_unknown_provider_is_still_unverified():
    """Adding presets must not turn the default into 'probably fine'."""
    assert cf.tool_calling_state("something-nobody-measured") == cf.UNVERIFIED

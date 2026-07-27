"""Decision ②A: we do NOT gate on the vision capability flag (it is hardcoded
for Anthropic, never set for Gemini or OpenAI-compat, and user-overridable in
localStorage — see spec §0.4). We send, and when the provider refuses we turn
its raw error into something the user can act on.

The user's addendum: this path MUST have a test that can tell "we really
converted it" from "the raw error leaked through".
"""
from __future__ import annotations

import pytest

from server.orchestrator import vision_errors


@pytest.mark.parametrize("raw", [
    "Error code: 400 - {'error': {'message': \"Invalid content type. image_url is only supported by certain models.\"}}",
    "400 Bad Request: this model does not support image input",
    "InvalidRequestError: images are not supported for model deepseek-chat",
    "Unsupported content block type: image",
])
def test_a_refusal_becomes_actionable(raw):
    out = vision_errors.explain(raw, had_images=True)
    assert out is not None
    # It must NAME the fix, not merely restate the failure.
    assert "vision" in out.lower() or "image" in out.lower()
    assert "model" in out.lower()


def test_the_raw_provider_noise_does_not_leak():
    """Discrimination: returning the raw string would satisfy any assertion that
    only checks for the word "image"."""
    raw = "Error code: 400 - {'error': {'message': \"image_url is only supported by certain models\", 'type': 'invalid_request_error'}}"
    out = vision_errors.explain(raw, had_images=True)
    assert "Error code: 400" not in out
    assert "invalid_request_error" not in out


def test_unrelated_errors_are_left_alone():
    """A rate limit or a bad key must NOT be relabelled as a vision problem —
    that would send the user to change models over an unrelated fault."""
    assert vision_errors.explain("429 rate limit exceeded", had_images=True) is None
    assert vision_errors.explain("401 invalid api key", had_images=True) is None


def test_nothing_is_converted_when_the_turn_had_no_images():
    """Same error text, no image in the turn ⇒ it cannot be a vision problem."""
    raw = "400 this model does not support image input"
    assert vision_errors.explain(raw, had_images=False) is None


def test_the_capability_flag_is_documented_as_display_only():
    """Decision ②A rests on the flag NOT being a gate. If a future change makes
    something depend on it, this comment is the first thing that should look
    wrong — spec §0.4 measured why it cannot be trusted."""
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[2]
           / "server" / "services" / "model_catalog.py").read_text()
    assert "OPTIMISTIC default" in src
    assert "Nothing gates on it" in src or "nothing gates on it" in src

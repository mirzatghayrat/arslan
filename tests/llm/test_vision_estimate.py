"""T1 — the estimator must survive a block-list `user`.

Why this needs its own test: `estimate_tokens` is only reached on the FALLBACK
branch, when the provider returned no usage frame. Every mocked test supplies
one, so a TypeError here passes the whole suite and fires only against a real
provider — and the streaming path takes that branch whenever a stream aborts,
which is the common case, not the rare one.
"""
from __future__ import annotations

import pytest

from arslan.llm import usage_sink

IMAGE_BLOCKS = [
    {"type": "text", "text": "描述这张图"},
    {"type": "image", "mime_type": "image/png", "data": "QUJD" * 5000},
]


def test_estimate_does_not_raise_on_block_list():
    # Before the fix this was TypeError: sequence item 1: expected str, list found
    n = usage_sink.estimate_tokens("SYSTEM", IMAGE_BLOCKS, "the answer")
    assert isinstance(n, int) and n > 0


def test_estimate_is_independent_of_the_blob_size():
    """Discrimination done right: the cheap fix ("just str() it") would price a
    20 000-character base64 blob like 5 000 tokens of prose, and a bigger image
    would cost proportionally more. Asserting a THRESHOLD would not catch a
    leak that happens to fall under it — asserting INDEPENDENCE does: grow the
    blob 10x and the estimate must not move at all."""
    small = usage_sink.estimate_tokens("SYSTEM", [
        {"type": "text", "text": "描述这张图"},
        {"type": "image", "mime_type": "image/png", "data": "QUJD" * 500},
    ], "answer")
    large = usage_sink.estimate_tokens("SYSTEM", [
        {"type": "text", "text": "描述这张图"},
        {"type": "image", "mime_type": "image/png", "data": "QUJD" * 5000},
    ], "answer")
    assert small == large, (
        f"the estimate tracks the base64 length ({small} vs {large}) — the blob "
        f"is being counted as text"
    )


def test_an_image_still_costs_something():
    """The opposite failure: dropping images from the estimate entirely would
    also make the test above pass, while under-reporting every image turn."""
    with_image = usage_sink.estimate_tokens("S", [
        {"type": "text", "text": "hi"},
        {"type": "image", "mime_type": "image/png", "data": "QUJD"},
    ], "a")
    text_only = usage_sink.estimate_tokens("S", [{"type": "text", "text": "hi"}], "a")
    assert with_image > text_only, "an image must contribute a non-zero estimate"


def test_plain_strings_are_unchanged():
    """34 of 36 call sites pass strings; their estimate must not move."""
    assert usage_sink.estimate_tokens("hello", "world") == usage_sink.estimate_tokens("helloworld")


@pytest.mark.parametrize("bad", [None, 123, {"type": "text"}])
def test_hostile_inputs_do_not_raise(bad):
    """It is on the failure path — it must never be the SECOND exception."""
    assert isinstance(usage_sink.estimate_tokens("x", bad, "y"), int)

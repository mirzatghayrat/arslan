"""Turn a provider's refusal of an image into something the user can act on.

WHY THIS EXISTS (decision ②A): we deliberately do NOT gate on the `vision`
capability flag. That flag is hardcoded True for every Anthropic model, never
set for Gemini or any OpenAI-compatible provider, and the user can toggle it in
localStorage where nothing server-side reads it (spec §0.4). Gating on it would
block Gemini entirely while waving through models that cannot see. So we send,
and we make the failure legible.

The conversion is DELIBERATELY narrow. A rate limit or a bad key must never be
relabelled as a vision problem — that sends someone off changing models over an
unrelated fault, which is worse than the raw error.
"""
from __future__ import annotations

import re

# Phrases providers actually use when refusing image input. Narrow on purpose:
# each one must be about image/vision content specifically.
_REFUSAL = re.compile(
    r"(image_url is only supported|does not support image|images? (are|is) not supported"
    r"|unsupported content block type:\s*image|no support for image|vision is not)",
    re.I,
)

_MESSAGE = (
    "The model you configured could not read the image. Most likely it has no "
    "vision support — switch to a model that does, or describe the picture in "
    "words instead."
)


def explain(raw_error: str, *, had_images: bool = False) -> str | None:
    """Actionable text, or None to leave the original error alone.

    None is the common case and the safe one: only a refusal that is clearly
    ABOUT the image, on a turn that actually CARRIED one, is converted."""
    if not had_images or not raw_error:
        return None
    return _MESSAGE if _REFUSAL.search(raw_error) else None

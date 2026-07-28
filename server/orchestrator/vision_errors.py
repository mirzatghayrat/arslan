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
#
# THESE WERE NOT ENOUGH, and the way they failed is worth keeping. They were
# written from what a refusal sounds like rather than from refusals. DeepSeek
# does not say it cannot see; its schema simply has no variant for an image, so
# it answers with a deserialisation error:
#
#   Failed to deserialize the JSON body into the target type: messages[3]:
#   unknown variant `image_url`, expected `text`
#
# Nothing here went near that, so on the user's daily model the advice never
# appeared and — because the same matcher decides it — the OCR fallback never
# started either. Shipped that way in v0.1.11.
_REFUSAL = re.compile(
    r"(image_url is only supported|does not support image|images? (are|is) not supported"
    r"|unsupported content block type:\s*image|no support for image|vision is not)",
    re.I,
)

# The second shape: the request was rejected by the provider's SCHEMA because it
# carried an image field. Deliberately requires BOTH halves — an image-shaped
# field name AND a schema-rejection verb — because either alone is far too wide.
# "image" appears in plenty of unrelated errors, and "unknown variant" appears
# in every malformed request. Together they say one thing only: this endpoint
# does not accept pictures.
_IMAGE_FIELD = re.compile(
    r"(image_url|inline_data|input_image|image/(png|jpe?g|webp|gif)"
    r"|\btype\W{0,4}image\b)", re.I)
_SCHEMA_REJECTION = re.compile(
    r"(unknown variant|unknown field|unexpected (field|variant|value)"
    r"|failed to deserialize|not one of|invalid content type"
    r"|expected\s+.{0,3}text.{0,3})", re.I)

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
    if _REFUSAL.search(raw_error):
        return _MESSAGE
    # Both halves, never one: see the comment on the two patterns.
    if _IMAGE_FIELD.search(raw_error) and _SCHEMA_REJECTION.search(raw_error):
        return _MESSAGE
    return None

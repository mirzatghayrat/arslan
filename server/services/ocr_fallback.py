"""THE degradation point. Tier 1 is the model; tier 2 is the system recogniser.

There is exactly one of these on purpose. Images arrive by two routes — dragged
into the second brain and attached to a chat message — and before this round
those routes behaved DIFFERENTLY on the same file (ingest.py's debt note from
the vision round: the same scanned PDF was readable when fed to the brain and
unreadable when attached to chat). Two copies of a fallback rule is how that
happens, so both routes call in here.

The order is fixed and never concurrent (decision ①A):

    tier 1  the configured model reads the image
    tier 2  ONLY IF the model refused it AS AN IMAGE, macOS Vision reads it

"Refused it as an image" is a TYPED determination, not a catch-all: it is the
provider's own wording, classified by vision_errors — the same narrow matcher
that decides whether to show the "switch models" advice. A rate limit, a bad
key or a network fault is NOT a vision problem and must not start an OCR pass;
a model that CAN see never produces that refusal, so a capable model never
takes this path. We deliberately do not consult the catalog's `vision` flag,
which is hardcoded true for Anthropic, never set for Gemini, and user-editable
in localStorage where no server reads it (vision round, spec §0.4).
"""
from __future__ import annotations

import logging

from server.orchestrator import vision_errors
from server.services import ocr_vision

logger = logging.getLogger(__name__)


def model_refused_the_image(raw_error: str) -> bool:
    """Did tier 1 fail *because the model cannot see*?

    Delegates to the vision-round classifier rather than re-implementing it:
    two matchers would drift, and the drift would be invisible — one of them
    would quietly stop firing while the other kept working."""
    return vision_errors.explain(raw_error or "", had_images=True) is not None


def read_locally(data: bytes, *, ui_language: str | None,
                 chosen_languages: str | None = None) -> tuple[str, str]:
    """Tier 2. Returns (text, status) — never raises, never guesses.

    The languages asked for are the user's explicit choice when they have made
    one, and the UI locale plus English otherwise; the host's own list is what
    decides whether we run at all (ocr_vision.recognize gates before calling)."""
    tags = ocr_vision.resolve_requested_tags(chosen_languages, ui_language)
    text, status = ocr_vision.recognize(data, languages=tags)
    if status != ocr_vision.OK:
        logger.info("tier-2 OCR produced no text: status=%s langs=%s", status, tags)
    return text, status


async def current_ui_language() -> str | None:
    """One reader for the locale, so the two routes cannot disagree about which
    languages to ask Vision for."""
    return (await _ocr_settings())[0]


async def current_ocr_languages() -> str | None:
    """The user's explicit OCR language choice, or None when unset."""
    return (await _ocr_settings())[1]


async def _ocr_settings() -> tuple[str | None, str | None]:
    """(ui_language, ocr_languages) from one read.

    Both callers need both values, and reading them separately would mean two
    round trips that could disagree if the settings changed between them."""
    try:
        from server.db import session as db_session
        from server.services import settings_service

        async with db_session.AsyncSessionLocal() as db:
            cfg = await settings_service.get_settings(db)
        return cfg.get("language"), cfg.get("ocr_languages")
    except Exception as exc:  # noqa: BLE001 — a missing setting must not stop OCR
        logger.warning("could not read the OCR settings, assuming defaults: %s", exc)
        return None, None


def ocr_source(filename: str) -> str:
    """Provenance for text lifted VERBATIM off an image.

    Deliberately NOT the same marker as described_source()'s "图片描述". The two
    have opposite trust semantics and merging them would be a lie: this is
    characters transcribed from the picture with no understanding applied, that
    one is a model's account of what it saw — not quotable as the image's text.
    A retrieval hit renders as "[source] text", so the marker is what the model
    sees when the chunk comes back."""
    return f"[OCR:{filename}]"


def explain_status(status: str, langs: tuple[str, ...] = ()) -> str | None:
    """What to tell the user when tier 2 did not produce text.

    None means "nothing to add" — the caller's own message stands. Every branch
    here names the actual reason instead of the old behaviour, which was to
    return "" for missing engine, unreadable file and blank page alike."""
    if status == ocr_vision.UNSUPPORTED_LANGUAGE:
        available = ", ".join(ocr_vision.supported_languages()) or "none"
        return ("This system's built-in text recognition does not cover your "
                f"language, so the writing in this image was not read. "
                f"It can read: {available}.")
    if status == ocr_vision.UNSUPPORTED_PLATFORM:
        return ("Built-in text recognition is available on macOS only. On this "
                "system, install tesseract and the optional `ocr` extra to read "
                "text from images.")
    if status == ocr_vision.NO_TEXT:
        # NAMES THE LANGUAGES IT LOOKED FOR, because "no writing was found" is
        # misleading in the one case that actually happens: text recognition
        # only finds what it was asked to look for, and asking for more does
        # not help — measured 2026-07-28, widening the list from ("zh-Hans",
        # "en-US") to all thirty supported languages LOSES the Chinese line
        # rather than adding to it. So an image whose writing is in a language
        # other than the interface language reads as empty, and the user is
        # owed the reason rather than a flat "there was nothing".
        tried = ", ".join(langs or ()) or "the interface language"
        return (f"No writing was found in this image (it was read as: {tried}). "
                "If the picture is in another language, switch the interface "
                "language to it and feed the image again.")
    if status == ocr_vision.ERROR:
        return "This image could not be read."
    return None

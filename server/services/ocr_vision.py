"""Tier-2 OCR: read text off an image with the operating system's own recogniser.

WHY THIS EXISTS: tier 1 is the model itself — a model with vision reads the
picture. When the configured model cannot (the user's daily driver is one such),
the image used to reach a path that needed a `tesseract` BINARY which ships with
Homebrew and not with Arslan. In every packaged build that path returned "" and
said nothing, so the app appeared to support OCR and did not. macOS Vision is
part of the OS: nothing is downloaded, nothing is borrowed from the machine.

TWO THINGS THIS MODULE REFUSES TO DO, both learned the expensive way:

  1. It never collapses "found no writing" into "could not run". The old helper
     returned "" for both, which is how an absent engine passed for a blank page.
     Every answer here carries one of the five statuses below.

  2. It never guesses at a language the host cannot recognise. Measured on
     2026-07-28: a correct English line scored confidence 0.500 and a scrambled
     Uyghur one — produced by handing Vision a wrong same-script language —
     scored 0.500 as well. A threshold that stops the fake stops the real too,
     so there is no threshold. There is a gate, and it runs BEFORE Vision.
     Confidence is logged for diagnosis and is never a release criterion.
"""
from __future__ import annotations

import logging
import sys
from functools import lru_cache
from typing import Sequence

logger = logging.getLogger(__name__)

OK = "ok"
NO_TEXT = "no_text"
ERROR = "error"
UNSUPPORTED_PLATFORM = "unsupported_platform"
UNSUPPORTED_LANGUAGE = "unsupported_language"

# Arslan's six UI locales -> BCP-47 tags Vision speaks. This mapping is OURS
# (our locale codes are not BCP-47); it is NOT a claim about what the host can
# recognise. That question is asked of the framework at runtime — see
# supported_languages() — because Vision's set grows with the macOS version and
# this app supports macOS 11 upward.
VISION_TAG_BY_UI_LANG = {
    "en": "en-US",
    "zh": "zh-Hans",
    "ja": "ja-JP",
    "es": "es-ES",
    "de": "de-DE",
    "fr": "fr-FR",
}

# Imported at module scope, inside the platform guard, ON PURPOSE: PyInstaller
# reads the AST and cannot see an import that happens inside a function body.
# That is not a hypothetical — uvicorn's WebSocket implementation is resolved
# lazily by name and its absence silently killed chat in six shipped versions.
# packaging/arslan-server.spec names these in hiddenimports as well.
if sys.platform == "darwin":  # pragma: no cover - platform-dependent import
    try:
        import Vision as _Vision
        from Foundation import NSData as _NSData
    except Exception as exc:  # noqa: BLE001 - a host without the bindings
        logger.warning("macOS Vision bindings unavailable: %s", exc)
        _Vision = None
        _NSData = None
else:  # pragma: no cover - platform-dependent import
    _Vision = None
    _NSData = None


def _vision():
    """Seam. Tests substitute this to assert ordering and platform behaviour
    without needing a second machine."""
    return _Vision


def is_available() -> bool:
    return _vision() is not None


@lru_cache(maxsize=1)
def supported_languages() -> tuple[str, ...]:
    """What THIS host can recognise, asked of the framework.

    Cached because the answer cannot change while the process lives, but never
    hardcoded: a literal list would describe the developer's macOS rather than
    the user's, and the two differ in exactly the direction that matters (older
    systems recognise fewer languages)."""
    vision = _vision()
    if vision is None:
        return ()
    try:
        request = vision.VNRecognizeTextRequest.alloc().init()
        langs, err = request.supportedRecognitionLanguagesAndReturnError_(None)
        if err is not None or not langs:
            logger.warning("Vision refused to list its languages: %s", err)
            return ()
        return tuple(str(t) for t in langs)
    except Exception as exc:  # noqa: BLE001 - never let a probe break ingestion
        logger.warning("could not read Vision's language list: %s", exc)
        return ()


def vision_tags_for(ui_language: str | None) -> tuple[str, ...]:
    """UI locale -> the tags to ask for, English kept as a companion.

    English rides along because interfaces, code and filenames in a screenshot
    are usually latin even when the surrounding UI is not; it is dropped again
    by the gate on any host that cannot do it."""
    tag = VISION_TAG_BY_UI_LANG.get((ui_language or "en").lower())
    if tag is None or tag == "en-US":
        return ("en-US",)
    return (tag, "en-US")


def recognize(data: bytes, *, languages: Sequence[str]) -> tuple[str, str]:
    """Return (text, status). Never raises."""
    if not is_available():
        return "", UNSUPPORTED_PLATFORM

    # THE GATE, and it is deliberately before the call. Placing it after would
    # yield the same tuple while still having asked the recogniser to guess at
    # an unknown script — which is precisely how the scrambled result in the
    # spec's section 0.6 was produced.
    known = set(supported_languages())
    usable = tuple(t for t in languages if t in known)
    if not usable:
        logger.info("OCR skipped: host recognises none of %s", tuple(languages))
        return "", UNSUPPORTED_LANGUAGE

    return _recognize_now(data, usable)


def _recognize_now(data: bytes, langs: tuple[str, ...]) -> tuple[str, str]:
    vision = _vision()
    try:
        handler = vision.VNImageRequestHandler.alloc().initWithData_options_(
            _NSData.dataWithBytes_length_(data, len(data)), None
        )
        request = vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(vision.VNRequestTextRecognitionLevelAccurate)
        request.setUsesLanguageCorrection_(True)
        request.setRecognitionLanguages_(list(langs))
        ok, err = handler.performRequests_error_([request], None)
        if not ok or err is not None:
            logger.warning("Vision request failed: %s", err)
            return "", ERROR
        lines = []
        for observation in request.results() or []:
            candidates = observation.topCandidates_(1)
            if not candidates:
                continue
            best = candidates[0]
            lines.append(str(best.string()))
            # Diagnosis only. Decision (3): confidence is NOT a release
            # criterion — it does not separate a correct line from a fake one.
            logger.debug("OCR line confidence=%.3f", best.confidence())
        text = "\n".join(lines).strip()
        return (text, OK) if text else ("", NO_TEXT)
    except Exception as exc:  # noqa: BLE001 - undecodable bytes, framework faults
        logger.warning("OCR failed: %s", exc)
        return "", ERROR

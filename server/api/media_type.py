"""Decide "is this request multipart?" the way Starlette decides it.

WHY THIS EXISTS. Three upload endpoints used to ask the question with a substring
test on the raw header::

    if "multipart/form-data" in content_type:
        form = await request.form()

``starlette.requests.Request._get_form`` does not ask it that way. It runs the header
through ``python_multipart.parse_options_header`` and compares the parsed MEDIA TYPE
for equality, so a header whose media type is something else entirely can still
contain the string in a parameter::

    Content-Type: application/x-www-form-urlencoded; boundary=multipart/form-data
      substring test -> True                            (we take the multipart branch)
      Starlette      -> application/x-www-form-urlencoded (urlencoded parser runs)

Both halves of that disagreement hurt. ``form.get("file")`` hands back a plain ``str``
instead of an ``UploadFile``, so ``await upload.read()`` raises ``AttributeError`` and
the caller gets a 500 they chose. And the request lands in Starlette's urlencoded
``FormParser``, which is the parser whose ``max_fields`` / ``max_part_size`` limits
CVE-2026-54283 reports as silently ignored — the fix for which is Starlette 1.3.1, a
version ``pyproject.toml`` deliberately forbids (``starlette<1.3``, because
``include_router`` breaks there). Asking the question correctly on our side closes the
reachable path without touching that cap.

🔴 DELIBERATELY NO EXTRA NORMALIZATION. It is tempting to lower-case and strip before
comparing, since RFC 9110 media types are case-insensitive. Do not. The property this
module provides is AGREEMENT with the parser that actually chooses, and
``parse_options_header`` is itself inconsistent about case: it lower-cases when the
header has no parameters, and preserves case when it does::

    "Multipart/Form-Data"              -> b"multipart/form-data"
    "MULTIPART/FORM-DATA; boundary=x"  -> b"MULTIPART/FORM-DATA"

So Starlette considers the second one NOT multipart and returns an empty ``FormData``.
Normalizing here would make us disagree in the opposite direction — claiming multipart
where Starlette has already decided otherwise. A near-miss in the safe direction is
still a near-miss, and it is the same class of defect as the one being fixed.
(Consequence worth knowing, not worth fixing here: an upload sent with an upper-cased
``Content-Type`` AND a boundary does not parse. That is pre-existing behaviour inside
Starlette / python-multipart — the old substring test rejected it too, because the
substring test was case-sensitive — so this module changes nothing about it.)
"""
from __future__ import annotations

_MULTIPART_FORM = b"multipart/form-data"


def is_multipart_form(content_type_header: str | None) -> bool:
    """True when Starlette's form parser will treat this request as multipart.

    Delegates to the same function Starlette calls, rather than re-deriving the
    answer, so the two cannot drift apart. ``python-multipart`` is a declared direct
    dependency (``pyproject.toml``), and Starlette hard-requires it for any form
    parsing at all.
    """
    from python_multipart.multipart import parse_options_header

    parsed, _ = parse_options_header(content_type_header or "")
    return parsed == _MULTIPART_FORM

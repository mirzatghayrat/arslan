"""Stage 5: a scanned PDF is rasterised and read by the model, under a cap.

The cap exists because every page is a separately billed image. The number is
NOT arbitrary and NOT about money — see VISION_PDF_MAX_PAGES for the arithmetic
that chose it. Over the cap the result SAYS what was skipped: silent truncation
would let a user act on 36 pages of a 137-page contract believing they had all
of it.
"""
from __future__ import annotations

import pytest

from server.services import ingest


def test_the_cap_has_the_agreed_default():
    assert ingest.VISION_PDF_MAX_PAGES == 36


def test_pages_under_the_cap_are_all_taken():
    assert ingest.pdf_page_plan(12) == (12, "")


def test_over_the_cap_reports_what_it_skipped():
    taken, note = ingest.pdf_page_plan(137)
    assert taken == 36
    # The exact numbers must be in the note — "some pages were skipped" is the
    # kind of message that lets someone quote a contract they never read.
    assert "137" in note and "36" in note


def test_the_note_is_empty_exactly_when_nothing_was_skipped():
    """Discrimination: always emitting a note would make it noise, and never
    emitting one is the silent truncation this test exists to prevent."""
    assert ingest.pdf_page_plan(36)[1] == ""
    assert ingest.pdf_page_plan(37)[1] != ""


def test_a_zero_page_document_is_not_a_crash():
    assert ingest.pdf_page_plan(0) == (0, "")


@pytest.mark.parametrize("pages", [1, 35, 36, 37, 500])
def test_never_returns_more_than_the_cap(pages):
    taken, _ = ingest.pdf_page_plan(pages)
    assert taken <= ingest.VISION_PDF_MAX_PAGES
    assert taken <= pages

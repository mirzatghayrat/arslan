"""The DuckDuckGo parser's behaviour when the page moves under it.

THE DEBT THIS PAYS. The previous round chose to hand-write this parser rather than
take `ddgs`, because ddgs ships its own Rust HTTP stack and would bypass every
control in net_pin. That trade took on the parsing brittleness deliberately, and
registered a test for it that was never written.

🔴 WHAT IS NOT WORTH TESTING: "today's HTML parses correctly". That fixture was
written the same day as the parser, so it agrees with it by construction and will
keep agreeing on the morning the real page changes. What these tests pin is the
FAILURE DIRECTION — an unrecognised shape must yield nothing, never something
plausible and wrong. A wrong URL handed to the model is worse than no result,
because nothing downstream can tell it is wrong.
"""
from __future__ import annotations

from server.registry.search_providers import DuckDuckGoHtmlProvider as DDG


def _result(href: str, title: str = "T", snippet: str | None = "S") -> str:
    snip = f'<a class="result__snippet">{snippet}</a>' if snippet is not None else ""
    return f'<div class="result"><a class="result__a" href="{href}">{title}</a>{snip}</div>'


class TestTheShapeItKnows:
    def test_it_reads_title_url_and_snippet(self):
        out = DDG.parse(_result("https://a.test", "Title", "Snippet"))
        assert out == [{"title": "Title", "url": "https://a.test", "snippet": "Snippet"}]

    def test_it_honours_the_result_limit(self):
        body = "".join(_result(f"https://a{i}.test") for i in range(10))
        assert len(DDG.parse(body, num_results=3)) == 3

    def test_a_missing_snippet_is_empty_not_absent(self):
        """The shape stays constant so callers never branch on a missing key."""
        out = DDG.parse(_result("https://a.test", "Title", snippet=None))
        assert out[0]["snippet"] == ""
        assert set(out[0]) == {"title", "url", "snippet"}


class TestTheFailureDirection:
    """🔴 The half that matters. Each case is a page this parser does not understand,
    and in every one the answer must be nothing rather than a guess."""

    def test_a_renamed_class_yields_nothing(self):
        body = '<div class="res"><a class="res__a" href="https://a.test">T</a></div>'
        assert DDG.parse(body) == []

    def test_an_anti_bot_page_yields_nothing(self):
        body = "<html><body>Please verify you are a human.</body></html>"
        assert DDG.parse(body) == []

    def test_an_empty_body_yields_nothing(self):
        assert DDG.parse("") == []

    def test_a_relative_href_is_dropped_rather_than_guessed(self):
        """The endpoint sometimes wraps targets in its own redirector. Prefixing a
        origin to guess the real target would hand out a URL nobody verified."""
        assert DDG.parse(_result("/l/?uddg=https%3A%2F%2Fa.test")) == []

    def test_a_javascript_href_is_dropped(self):
        assert DDG.parse(_result("javascript:alert(1)")) == []

    def test_partial_recognition_drops_only_the_bad_result(self):
        """One unusable result must not take the usable ones with it, and must not
        be passed through either."""
        body = _result("https://good.test", "Good") + _result("/relative", "Bad")
        out = DDG.parse(body)
        assert [r["url"] for r in out] == ["https://good.test"]


class TestTextHandling:
    def test_entities_are_unescaped(self):
        out = DDG.parse(_result("https://a.test", "A&amp;B"))
        assert out[0]["title"] == "A&B"

    def test_nested_markup_is_stripped_from_the_title(self):
        """The endpoint bolds the matched terms inside the link."""
        out = DDG.parse(_result("https://a.test", "an <b>exact</b> match"))
        assert out[0]["title"] == "an exact match"

    def test_an_escaped_href_is_unescaped_before_the_scheme_check(self):
        out = DDG.parse(_result("https://a.test/?x=1&amp;y=2"))
        assert out[0]["url"] == "https://a.test/?x=1&y=2"


class TestItIsPure:
    def test_parsing_touches_no_network_and_needs_no_instance(self):
        """It is a classmethod over a string. If this ever needs a provider instance
        or a response object, the extraction has been undone and the tests above stop
        describing the parser."""
        assert DDG.parse(_result("https://a.test"))[0]["url"] == "https://a.test"

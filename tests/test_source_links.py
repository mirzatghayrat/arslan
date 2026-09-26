import pytest

from arslan.companion.research import receipt
from arslan.companion.source_links import LABELS, source_link_footer


@pytest.mark.parametrize("language", LABELS)
def test_supplied_links_are_explicitly_unread_and_localized(language):
    result = source_link_footer('{"url":"https://example.com/a"}', [], language=language)
    assert "https://example.com/a" in result and LABELS[language][2] in result
    assert LABELS[language][1] not in result


def test_only_admitted_receipts_upgrade_read_status():
    url, text = "https://example.com/a", "Public source text"
    value = receipt(url, text, truncated=False)
    trace = [{"tool": "web_extract", "args": {"url": url}, "result": {
        "ok": True, "url": url, "text": text, "source": value.model_dump(mode="json")}}]
    result = source_link_footer(url, trace)
    assert result.count(url) == 1 and "Read this turn" in result
    trace[0]["result"]["source"]["truncated"] = True
    partial = source_link_footer(url, trace)
    assert "Partially read" in partial and "Read this turn" not in partial
    trace[0]["result"]["text"] = "tampered"
    assert "not independently read" in source_link_footer(url, trace)


@pytest.mark.parametrize("url", ["https://user:pass@example.com", "https://example.com?api_key=private", "https://example.com?xsec_token=private"])
def test_credential_bearing_links_are_not_repeated(url):
    assert source_link_footer(url, []) == ""


def test_no_model_url_invention_and_bounded_markdown():
    assert source_link_footer("No sources supplied", []) == ""
    result = source_link_footer(" ".join(f"https://example.com/{n}" for n in range(30)), [])
    assert result.count("https://") == 12
    assert "javascript:" not in source_link_footer("[x](javascript:alert(1))", [])
    assert "%28" in source_link_footer("https://example.com/a(b)c", [])
    assert "https://example.com/a%28b%29" in source_link_footer("https://example.com/a(b)", [])
    assert "https://example.com/a%28b%29" in source_link_footer("[source](https://example.com/a(b))", [])

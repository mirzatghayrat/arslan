"""D9 (docs/plans/0162/D9-*.md): when /extract cuts an attachment's text, the model is told — one
line after the kept text with the full length, saying to read the saved original when the message
says where it is (the iPhone Bridge writes "Attached from iPhone: name → path"), or else to say only
the beginning was read. The default cap is 40,000 characters."""
import dataclasses
from types import SimpleNamespace

from server import config
from server.services import extract

LIMIT = 40


def _limit(monkeypatch, n: int = LIMIT) -> None:
    monkeypatch.setattr(extract, "settings", SimpleNamespace(attach_extract_char_limit=n))


async def test_a_cut_file_keeps_its_start_and_says_how_long_it_was(monkeypatch):
    _limit(monkeypatch)
    body = "".join(chr(ord("a") + i % 26) for i in range(1234))
    monkeypatch.setattr(extract.ingest, "_extract_file", lambda fn, data, **kw: body)
    text, truncated = await extract.extract_text(filename="report.txt", data=b"x")
    assert truncated is True
    kept, note = text.split("\n\n", 1)
    assert kept == body[:LIMIT]
    assert note == ("[Only the first 40 of 1,234 characters of this file are included. If the message says where "
                    "the file was saved, read the rest from there with read_file; otherwise tell the user that only "
                    "the beginning was read.]")


async def test_a_file_within_the_cap_comes_back_whole_with_no_line(monkeypatch):
    _limit(monkeypatch)
    monkeypatch.setattr(extract.ingest, "_extract_file", lambda fn, data, **kw: "x" * LIMIT)
    text, truncated = await extract.extract_text(filename="short.txt", data=b"x")
    assert (text, truncated) == ("x" * LIMIT, False)


async def test_a_cut_page_says_so_without_pointing_at_a_saved_file(monkeypatch):
    from server.registry import executors
    _limit(monkeypatch)

    class _Page:
        async def execute(self, args):
            return {"ok": True, "url": args["url"], "text": "p" * 500}
    monkeypatch.setitem(executors.EXECUTORS, "web_extract", _Page())
    text, truncated = await extract.extract_text(url="https://example.com/long")
    assert truncated is True and text.startswith("p" * LIMIT + "\n\n[")
    assert "of 500 characters of this page are included" in text and "read_file" not in text


def test_the_cap_is_40000_and_the_environment_still_sets_it(monkeypatch):
    declared = {f.name: f.default for f in dataclasses.fields(config.Settings)}
    assert declared["attach_extract_char_limit"] == 40_000
    monkeypatch.delenv("ARSLAN_ATTACH_CHAR_LIMIT", raising=False)
    assert config.load_settings().attach_extract_char_limit == 40_000
    monkeypatch.setenv("ARSLAN_ATTACH_CHAR_LIMIT", "12000")
    assert config.load_settings().attach_extract_char_limit == 12_000

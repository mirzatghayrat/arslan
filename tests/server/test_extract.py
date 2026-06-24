import pytest
from server.services import extract


async def test_extract_file_reuses_extractor(monkeypatch):
    monkeypatch.setattr(extract.ingest, "_extract_file", lambda fn, data: "hello extracted body")
    text, truncated = await extract.extract_text(filename="a.txt", data=b"x")
    assert "hello extracted body" in text
    assert truncated is False


async def test_extract_truncates_to_limit(monkeypatch):
    monkeypatch.setattr(extract.ingest, "_extract_file", lambda fn, data: "A" * 50)
    from unittest.mock import MagicMock
    fake_settings = MagicMock()
    fake_settings.attach_extract_char_limit = 10
    monkeypatch.setattr(extract, "settings", fake_settings)
    text, truncated = await extract.extract_text(filename="a.txt", data=b"x")
    assert len(text) == 10
    assert truncated is True


async def test_extract_url_uses_web_extract_executor(monkeypatch):
    from server.registry import executors
    class _Stub:
        async def execute(self, args):
            return {"ok": True, "url": args["url"], "text": "web body text"}
    monkeypatch.setitem(executors.EXECUTORS, "web_extract", _Stub())
    text, _ = await extract.extract_text(url="https://example.com")
    assert "web body text" in text


async def test_extract_url_private_rejected(monkeypatch):
    from server.registry import executors
    class _Stub:
        async def execute(self, args):
            return {"ok": False, "error": "private address"}
    monkeypatch.setitem(executors.EXECUTORS, "web_extract", _Stub())
    with pytest.raises(ValueError):
        await extract.extract_text(url="http://169.254.169.254/")

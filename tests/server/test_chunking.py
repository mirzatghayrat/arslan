from arslan.core.chunking import chunk_text


def test_short_text_one_chunk():
    assert chunk_text("hello world") == ["hello world"]


def test_empty_text_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_long_text_splits_with_overlap():
    text = "x" * 2000
    chunks = chunk_text(text, size=800, overlap=100)
    assert len(chunks) >= 3
    assert all(len(c) <= 800 for c in chunks)
    assert chunks[0][-50:] in chunks[1]


def test_cjk_text_chunks_by_char():
    text = "中" * 1000
    chunks = chunk_text(text, size=400, overlap=50)
    assert len(chunks) >= 3
    assert all(len(c) <= 400 for c in chunks)

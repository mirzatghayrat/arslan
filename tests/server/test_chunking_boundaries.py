from arslan.core.chunking import chunk_text
from server.services.persona_seed_service import _fts_query


def test_paragraph_boundary_preferred():
    text = ("第一段内容。" * 60) + "\n\n" + ("第二段内容。" * 60)   # 段界落在窗口内
    chunks = chunk_text(text, size=400, overlap=50)
    assert any(c.endswith("。") for c in chunks[:-1])       # 切点落边界非段中
    assert all(len(c) <= 400 for c in chunks)


def test_sentence_boundary_when_no_paragraph():
    text = "这是一句话。" * 200                              # 无段落,有句号
    chunks = chunk_text(text, size=400, overlap=50)
    assert all(c.endswith("。") for c in chunks[:-1])       # 中间块都在句号处断


def test_no_boundary_falls_back_to_char():
    text = "x" * 2000
    chunks = chunk_text(text, size=800, overlap=100)
    assert len(chunks) >= 3 and all(len(c) <= 800 for c in chunks)
    assert chunks[0][-50:] in chunks[1]                     # overlap 仍在


def test_progress_floor_terminates_high_overlap():
    chunks = chunk_text("字" * 1000, size=200, overlap=150)  # I3:不死循环
    assert chunks and "".join(chunks)                        # 终止且非空


def test_coverage_no_text_lost():
    # Prove the KB's load-bearing "no text lost" invariant: chunk spans are ordered,
    # every consecutive pair overlaps-or-touches (no gap), and coverage reaches
    # end-of-text. A tail-only check (e.g. text.endswith(chunks[-1])) would miss a
    # mid-text gap, so we walk each chunk's true span in the source.
    #
    # Source is whitespace-free so chunk.strip() can't shift indices. `text.index`
    # is lower-bounded at each chunk's minimum possible start (prev_end - overlap):
    # the source is highly repetitive, so an unbounded search returns an earlier
    # false match and understates coverage. The bound never skips the true span
    # because start_{i+1} = max(start_i + 1, end_i - overlap) >= end_i - overlap.
    # Verified this FAILS if any chunk is dropped (interior gap or short coverage).
    #
    # (The brief's original literal assertion built its target from a period-STRIPPED
    # copy of `text` but tested membership in an un-stripped chunk — unsatisfiable by
    # any non-corrupting chunker; this contiguous-span check replaces it.)
    text = "甲乙丙。" * 300
    overlap = 50
    chunks = chunk_text(text, size=400, overlap=overlap)
    prev_end = 0
    search_from = 0
    for c in chunks:
        start = text.index(c, search_from)                   # true span, lower-bounded
        assert start <= prev_end, f"gap before chunk at {start}, prev ended {prev_end}"
        prev_end = start + len(c)                             # no whitespace => strip is a no-op
        search_from = max(0, prev_end - overlap)              # next chunk's earliest start
    assert prev_end == len(text)                             # contiguous coverage to end-of-text


def test_persona_seed_cjk_run_tokens():
    q = _fts_query("猫粮政策")
    assert '"猫粮政策"' in q                                 # 整串词元
    assert '"猫" OR' not in q                                # 不再逐字

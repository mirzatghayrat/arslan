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
    text = "甲乙丙。" * 300
    chunks = chunk_text(text, size=400, overlap=50)
    # NOTE: brief's literal assertion (`text.replace("。", "")[-6:] in chunks[-1]`)
    # builds its target from a period-STRIPPED copy of `text` but checks membership
    # in a non-stripped chunk — since every "甲乙丙" unit is separated by "。" in the
    # source, that 6-char run never occurs anywhere in `text` itself (verified:
    # `target in text` is False), so it's unsatisfiable by any non-corrupting
    # chunker. Testing the actual intent instead: the last chunk reaches the true
    # end of `text` with nothing dropped.
    assert text.endswith(chunks[-1])                         # 尾部内容在最后一块,覆盖到文末


def test_persona_seed_cjk_run_tokens():
    q = _fts_query("猫粮政策")
    assert '"猫粮政策"' in q                                 # 整串词元
    assert '"猫" OR' not in q                                # 不再逐字

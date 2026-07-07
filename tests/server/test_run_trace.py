from server.orchestrator import run_trace


def test_collects_and_truncates_tool_calls():
    with run_trace.collecting() as buf:
        run_trace.record(tool="web_search", args={"query": "x"}, result="R" * 5000, ok=True, error=None, ms=12)
        run_trace.record(tool="web_extract", args={"url": "u"}, result="short", ok=False, error="boom", ms=5)
        snap = run_trace.snapshot()
    assert len(buf) == 2 and len(snap) == 2
    assert snap[0]["tool"] == "web_search" and snap[0]["ok"] is True
    assert len(snap[0]["result_raw"]) == 2000            # truncated to RUN_RAW_CAP
    assert snap[1]["error"] == "boom" and snap[1]["ok"] is False


def test_record_noop_without_context():
    run_trace.record(tool="x", args={}, result="y", ok=True, error=None, ms=1)  # must not raise
    assert run_trace.snapshot() == []

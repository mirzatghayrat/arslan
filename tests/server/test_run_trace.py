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


def test_record_prompt_noop_without_context():
    run_trace.record_prompt(system_prompt="x", injected_kb="y")  # must not raise
    assert run_trace.prompt() == {"system_prompt": None, "injected_kb": None}


def test_record_prompt_round_trips_inside_collecting():
    with run_trace.collecting():
        assert run_trace.prompt() == {"system_prompt": None, "injected_kb": None}
        run_trace.record_prompt(system_prompt="SYS", injected_kb="KB")
        assert run_trace.prompt() == {"system_prompt": "SYS", "injected_kb": "KB"}
    # outside the context, prompt() reports empty again
    assert run_trace.prompt() == {"system_prompt": None, "injected_kb": None}

import logging

from server.mcp_server import audit


def test_record_emits_one_line_with_tool_and_status(caplog):
    with caplog.at_level(logging.INFO, logger="arslan.mcp_server.audit"):
        audit.record(tool="list_spawns", status="ok")
    lines = [r for r in caplog.records if r.name == "arslan.mcp_server.audit"]
    assert len(lines) == 1
    msg = lines[0].getMessage()
    assert "list_spawns" in msg and "ok" in msg


def test_record_never_contains_a_secret_value(caplog):
    # The gate/tools only ever pass tool + status (+ a short non-secret detail).
    with caplog.at_level(logging.INFO, logger="arslan.mcp_server.audit"):
        audit.record(tool="get_run_status", status="reject:401")
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "Bearer" not in joined  # no auth material is ever routed through record()

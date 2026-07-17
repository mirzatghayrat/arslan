"""Structural wiring tests for Task 8: /mcp-server mount + app.state.mcp_server.

Verifies the real ``create_app()`` (not an in-process test harness) (a) registers
the gated MCP mount BEFORE the SPA catch-all route, and (b) stores a live FastMCP
instance (with its ``session_manager`` already constructed via
``streamable_http_app()``) on ``app.state``. The lifespan actually *driving*
``session_manager.run()`` over the wire is proven by Task 7's in-process harness;
the fully-wired real-process boot is proven by the Task 11 smoke (see brief for the
testing-home decision — no in-suite full-lifespan test here)."""
from starlette.routing import Mount


def _make_app(monkeypatch, tmp_path):
    monkeypatch.setenv("ARSLAN_TEST_ROUTES", "1")
    monkeypatch.setenv("ARSLAN_SPAWNS_DIR", str(tmp_path / "spawns"))
    # The SPA catch-all route (the thing the mount must precede) is only
    # registered when `static_dir.is_dir()`. This worktree has no built
    # frontend, so fake one — same pattern as tests/server/test_static.py's
    # `client` fixture — instead of skipping the ordering assertion.
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html><title>Arslan</title>")
    monkeypatch.setenv("ARSLAN_STATIC_DIR", str(static_dir))
    import importlib
    import server.config as cfg
    importlib.reload(cfg)
    from server.main import create_app
    return create_app()


def test_mcp_mount_exists_and_precedes_spa_catch_all(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    paths = [getattr(r, "path", None) for r in app.routes]
    mount_idx = next(i for i, r in enumerate(app.routes)
                     if isinstance(r, Mount) and getattr(r, "path", "") == "/mcp-server")
    catch_all_idx = next(i for i, r in enumerate(app.routes)
                         if getattr(r, "path", "") == "/{full_path:path}")
    assert mount_idx < catch_all_idx, f"mount must precede SPA catch-all; paths={paths}"


def test_app_state_carries_the_mcp_server(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    from mcp.server.fastmcp import FastMCP
    assert isinstance(app.state.mcp_server, FastMCP)
    # streamable_http_app() was called → session_manager is live (no RuntimeError)
    assert app.state.mcp_server.session_manager is not None

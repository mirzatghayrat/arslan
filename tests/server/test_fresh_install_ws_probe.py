"""The release check's WebSocket probe, against a real server in the desktop app's configuration (⓪Plan, #364).

Since #338 a packaged server refuses a WebSocket with no Origin, and the probe sent none, so the R63 candidate's
fresh-install check would have failed. Now every handshake sends the window's same-origin Origin, and three
handshakes each prove one guard. Each check here is shown to fail when its guard is taken away: the WebSocket
library (uvicorn with ws="none"), the token check, and the Origin check.
"""
from __future__ import annotations

import importlib
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn

_PACKAGING = Path(__file__).resolve().parents[2] / "packaging"
TOKEN = "probe-token-0123456789"


@pytest.fixture(scope="module")
def probe():
    sys.path.insert(0, str(_PACKAGING))
    try:
        yield importlib.import_module("fresh_install_check")
    finally:
        sys.path.remove(str(_PACKAGING))


@pytest.fixture
def packaged(monkeypatch, tmp_path):
    for key in ("ARSLAN_ENV", "ARSLAN_ALLOWED_ORIGINS", "ARSLAN_ALLOWED_HOSTS", "ARSLAN_TEST_ROUTES"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ARSLAN_PACKAGED", "1")
    monkeypatch.setenv("ARSLAN_SECRET_KEY", "x" * 32)
    monkeypatch.setenv("ARSLAN_API_TOKEN", TOKEN)
    monkeypatch.setenv("ARSLAN_DATA_DIR", str(tmp_path))
    import server.config as config
    import server.security as security
    importlib.reload(config)
    importlib.reload(security)
    yield
    monkeypatch.undo()
    importlib.reload(config)
    importlib.reload(security)


def _serve(ws: str = "auto"):
    """A real uvicorn on a free port, the app as the desktop sidecar builds it; returns (port, stop)."""
    from server.main import create_app
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, lifespan="off",
                                           log_level="error", ws=ws))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "uvicorn did not start"

    def stop():
        server.should_exit = True
        thread.join(5)
    return port, stop


def _run(probe, port):
    checks = probe.Checks()
    probe.check_websocket(port, TOKEN, checks)
    return checks


def test_all_three_handshakes_pass_against_a_packaged_server(probe, packaged):
    port, stop = _serve()
    try:
        checks = _run(probe, port)
    finally:
        stop()
    assert checks.failures == [] and len(checks.passes) == 3


def test_without_a_websocket_library_the_first_check_fails(probe, packaged):
    port, stop = _serve(ws="none")
    try:
        checks = _run(probe, port)
    finally:
        stop()
    assert any("can hold a WebSocket" in f for f in checks.failures)


def test_with_the_token_check_gone_the_anonymous_check_fails(probe, packaged, monkeypatch):
    import server.ws.arslan as ws_arslan
    monkeypatch.setattr(ws_arslan, "is_ws_token_valid", lambda token: True)
    port, stop = _serve()
    try:
        checks = _run(probe, port)
    finally:
        stop()
    assert [f for f in checks.failures if "unauthenticated" in f]
    assert not [f for f in checks.failures if "no Origin" in f]          # the other two still hold


def test_with_the_origin_check_gone_the_no_origin_check_fails(probe, packaged, monkeypatch):
    import server.security as security
    monkeypatch.setattr(security, "ws_origin_allowed", lambda origin, host=None: True)
    port, stop = _serve()
    try:
        checks = _run(probe, port)
    finally:
        stop()
    assert [f for f in checks.failures if "no Origin" in f]
    assert not [f for f in checks.failures if "unauthenticated" in f]

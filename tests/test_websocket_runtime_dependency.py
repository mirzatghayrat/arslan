"""websockets is a RUNTIME dependency, and the packaging must carry it.

THE BUG THIS PINS (builds 0.1.0-0.1.6): `websockets>=12.0` was declared in the
`dev` extra. Release builds install `--extra server --extra build`, never
`dev`, so the frozen sidecar had uvicorn and no WebSocket implementation.
uvicorn does not treat that as an error — it logs "No supported WebSocket
library detected" and serves every /ws/ upgrade as a plain HTTP request, which
the SPA catch-all answers with 200. Chat therefore never worked in ANY packaged
build, while /health, auth and every acceptance check passed.

Two independent regressions are pinned here because they failed together and
either one alone would have been enough to break chat:
  1. the dependency layer (a dev-only declaration is not installed at release)
  2. the PyInstaller spec (uvicorn imports the library lazily BY NAME, so
     static analysis cannot find it — it must be a hidden import)
"""
from __future__ import annotations

import pathlib
import re
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


def test_websockets_is_a_runtime_dependency_not_dev_only():
    proj = _pyproject()["project"]
    runtime = " ".join(proj["dependencies"])
    assert "websockets" in runtime, (
        "websockets must be a RUNTIME dependency: uvicorn needs it to serve "
        "/ws/ at all, and release builds do not install the dev extra"
    )


def test_websockets_is_not_only_in_an_optional_extra():
    """⓪ discrimination: the assertion above must be about the RUNTIME list,
    not satisfied by any mention anywhere in the file."""
    proj = _pyproject()["project"]
    extras = proj.get("optional-dependencies", {})
    dev = " ".join(extras.get("dev", []))
    assert "websockets" not in dev, (
        "websockets is back in the dev extra — release builds would ship "
        "without a WebSocket implementation again"
    )


def test_pyinstaller_spec_hidden_imports_websockets():
    spec = (ROOT / "packaging" / "arslan-server.spec").read_text()
    assert re.search(r"collect_submodules\(\s*[\"']websockets[\"']\s*\)", spec), (
        "the frozen build must hidden-import websockets: uvicorn resolves it by "
        "name at serve time, so PyInstaller's static analysis never sees it"
    )


def test_selftest_asserts_the_websocket_protocol_resolves():
    """The packaged selftest must check what uvicorn RESOLVES, not merely that
    the module imports — an importable library that uvicorn does not select
    would fail exactly the same way in production."""
    entry = (ROOT / "packaging" / "server_entry.py").read_text()
    assert "ws_protocol_class" in entry, (
        "selftest must assert uvicorn's resolved websocket protocol class"
    )


def test_acceptance_harness_performs_a_real_handshake():
    """A unit test cannot prove the BUNDLE works; the acceptance harness must
    open a real upgrade against the built app and demand 101."""
    harness = (ROOT / "packaging" / "fresh_install_check.py").read_text()
    assert "Sec-WebSocket-Key" in harness and "101" in harness, (
        "fresh_install_check must perform a real /ws/ handshake and require 101"
    )

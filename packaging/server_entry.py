#!/usr/bin/env python3
"""PyInstaller entry point for the packaged Arslan backend (S4.3-a).

Adapted from the sidecar pattern in andrewyng/openworker (MIT,
Copyright (c) 2024 Andrew Ng); the port handshake and the environment
guarantees below are ours.

Run as a sidecar by the Tauri shell, never by a user directly. Its whole job:

  1. Refuse to inherit a developer's environment (see _sanitize_env).
  2. Bind uvicorn to 127.0.0.1 on an OS-assigned free port.
  3. Announce that port on stdout in a machine-readable line, so the shell
     knows where to point the webview, then serve until killed.

WHY AN OS-ASSIGNED PORT, NOT A FIXED ONE: a fixed port turns "another copy of
Arslan is already running" (or any unrelated process on that port) into a
startup crash, and on a desktop app the second launch is the common case, not
the rare one. Binding port 0 always succeeds; the cost is that the port must
be communicated, hence the handshake line below.
"""
from __future__ import annotations

import os
import socket
import sys

# The one line the Tauri side parses. Keep the prefix stable — changing it
# breaks every already-installed shell that is looking for it.
PORT_LINE_PREFIX = "ARSLAN_PORT="


def _sanitize_env() -> None:
    """Strip developer-only overrides that must never reach a packaged app.

    A packaged app inherits the environment of whoever launched it. On a
    developer's own Mac — the machine where this build is tested most — the
    shell almost certainly exports ARSLAN_DATA_DIR=data (README.md:54 and
    CONTRIBUTING.md:43 both tell people to), and a relative path resolves
    against the app's CWD. That would silently point a released build at a
    throwaway directory instead of the user's real brain, and it would look
    fine to the one person least able to notice: the developer, whose data is
    in the repo anyway.

    Removing the variable makes server.config._default_data_dir() take over,
    which resolves to ~/Library/Application Support/Arslan. That is the ONLY
    correct location for a packaged build.

    ARSLAN_SECRET_KEY is deliberately NOT stripped: an explicitly-set secret
    is a legitimate power-user choice, and secret_bootstrap already warns on
    a mismatch against ~/.arslan/secret_key. Stripping it would break anyone
    managing their own key and could make already-stored provider keys
    undecryptable.
    """
    for var in ("ARSLAN_DATA_DIR", "ARSLAN_DB_PATH"):
        os.environ.pop(var, None)


def _free_port() -> int:
    """Ask the OS for a free port on the loopback interface.

    Bound and closed here, then re-bound by uvicorn a moment later. That gap
    is a real (if tiny) race; it is accepted because the alternative — passing
    a pre-bound socket through uvicorn — costs more than it buys for a
    single-user desktop app, and a collision surfaces immediately as a failed
    launch rather than as data loss.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def selftest() -> int:
    """Import every feature module and report what a frozen build is missing.

    THE BUG THIS CATCHES: PyInstaller ships only what its static analysis
    finds, minus whatever `excludes` removes, and a module that is missing
    from the bundle fails at *its first import* — which for a rarely-used
    feature can be days after release. Serving /health proves almost nothing:
    the app boots fine with half its features unloadable.

    Not hypothetical. An earlier revision of arslan-server.spec excluded PIL
    on the (true for our code, false for the dependency graph) basis that it
    was OCR-only. python-pptx imports it internally, so the whole deck feature
    was ModuleNotFoundError in a bundle whose /health returned 200.

    Every import here must be a module the app genuinely needs, so that this
    list cannot rot into a formality that passes while the app is broken.
    """
    required = [
        "server.main",
        "server.config",
        "server.db.session",
        "server.db.migrations.runner",
        "server.services.ingest",       # attachment ingestion
        "server.services.deck_pptx",    # the PIL casualty
        "server.services.extract",
        "arslan.llm.adapter",
        "arslan.spawn",
        "mcp",
        "aiosqlite",
        "sqlalchemy.dialects.sqlite.aiosqlite",  # resolved by name, not import
    ]
    failed: list[tuple[str, str]] = []
    for name in required:
        try:
            __import__(name)
        except Exception as exc:  # noqa: BLE001 — report them all, not the first
            failed.append((name, f"{type(exc).__name__}: {exc}"))

    if failed:
        print("SELFTEST FAILED — modules missing from the bundle:", file=sys.stderr)
        for name, err in failed:
            print(f"  {name}: {err}", file=sys.stderr)
        return 1
    print(f"SELFTEST OK ({len(required)} modules importable)", flush=True)
    return 0


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return selftest()

    _sanitize_env()

    port = int(os.environ.get("ARSLAN_PORT") or _free_port())

    # Announce BEFORE uvicorn.run(), which blocks. flush because stdout is a
    # pipe here (block-buffered), so without it the shell would wait for the
    # buffer to fill and the app would appear to hang on a blank window.
    print(f"{PORT_LINE_PREFIX}{port}", flush=True)

    import uvicorn

    # 127.0.0.1, never 0.0.0.0: the API is unauthenticated to anything that
    # already has the token, and binding the wildcard would put a desktop
    # app's whole brain on the local network. server/main.py:85 warns about
    # exactly this combination.
    uvicorn.run(
        "server.main:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
        # No reloader, no extra workers: one process, killed by the shell.
        workers=1,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
import pathlib
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

    _point_static_dir_into_the_bundle()


def _point_static_dir_into_the_bundle() -> None:
    """Tell the server where the SPA lives inside the frozen app.

    server/config.py defaults static_dir to ``Path(config.py).parent/"static"``,
    which is a real directory only in a source checkout that has run a build.
    Inside a PyInstaller bundle that path does not exist, and server/main.py:482
    guards the whole SPA mount behind ``if static_dir.is_dir()`` — so the
    fallback route is never registered and every non-API URL 404s.

    The failure mode is the nasty kind: the sidecar starts, /api/v1/health
    returns 200, and the window is simply blank. Nothing in the logs says why.

    arslan-server.spec stages web/dist at ``_internal/arslan_web``; point at it
    explicitly rather than relying on __file__ arithmetic, which does not
    survive freezing. A user-supplied ARSLAN_STATIC_DIR still wins.
    """
    if not getattr(sys, "frozen", False):
        return
    if os.environ.get("ARSLAN_STATIC_DIR"):
        return
    bundled = pathlib.Path(getattr(sys, "_MEIPASS", "")) / "arslan_web"
    if bundled.is_dir():
        os.environ["ARSLAN_STATIC_DIR"] = str(bundled)
    else:
        # Loud, because the alternative is a blank window with no explanation.
        print(
            f"WARNING: bundled web assets not found at {bundled} — the UI will "
            "not load. The build staged no web/dist; see packaging/build_dmg.sh.",
            file=sys.stderr,
            flush=True,
        )


def _die_when_the_shell_does() -> None:
    """Exit as soon as our parent's end of stdin closes.

    The Tauri shell also kills us on its exit events, but that only covers
    orderly shutdowns. A crash, a force-quit, or `kill -9` on the shell skips
    those handlers entirely and leaves this process running — holding the
    SQLite lock on the user's brain. The next launch then fails in a way that
    reads like database corruption rather than a stray process.

    Watching stdin needs no cooperation from the parent at all: when the
    process at the other end of the pipe dies, for any reason, the write end
    closes and read() returns EOF. That is the only signal available in every
    case.

    os._exit, not sys.exit: this runs on a daemon thread while uvicorn owns the
    main one, and a SystemExit here would be swallowed by the thread rather
    than stopping the server.

    FROZEN ONLY, and that guard is load-bearing rather than tidiness: pytest
    replaces sys.stdin with an object whose readline() returns "" immediately.
    Under test that reads as "the parent died" and os._exit(0) takes the whole
    pytest process down mid-run — which is exactly what happened before this
    guard existed. The watch loop itself is tested directly via _watch_stdin.

    Also a no-op when stdin is a terminal (someone running the binary by hand)
    or already closed.
    """
    import threading

    if not getattr(sys, "frozen", False):
        return
    try:
        if sys.stdin is None or sys.stdin.closed or sys.stdin.isatty():
            return
    except (ValueError, OSError):
        return

    threading.Thread(
        target=_watch_stdin, args=(sys.stdin,), daemon=True, name="parent-watchdog"
    ).start()


def _watch_stdin(stream, on_eof=None) -> None:
    """Block until `stream` hits EOF, then exit the process.

    Split out of the thread body so it can be tested with a fake stream and an
    injected on_eof — otherwise the only way to exercise it would be to let it
    call os._exit and take the test runner with it.
    """
    try:
        while stream.readline():
            pass  # The shell sends nothing; any input is simply ignored.
    except Exception:  # noqa: BLE001 — a broken pipe means the same thing
        pass
    print("shell closed our stdin — exiting", file=sys.stderr, flush=True)
    (on_eof or (lambda: os._exit(0)))()


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

    # Importable modules are not enough: every module here can load while the
    # window still comes up blank, because the SPA is DATA, not code. Assert
    # the assets the UI is actually served from.
    asset_errors: list[str] = []
    if getattr(sys, "frozen", False):
        root = pathlib.Path(getattr(sys, "_MEIPASS", ""))
        web = root / "arslan_web"
        if not (web / "index.html").is_file():
            asset_errors.append(f"{web}/index.html is missing — the UI cannot load")
        elif not (web / "assets").is_dir():
            asset_errors.append(
                f"{web}/assets is missing — index.html would load with no JS or CSS"
            )

        # Package DATA loaded at runtime via Path(__file__).parent. Missing
        # seeds is why a bundle once created zero of its six factory spawns
        # while answering /api/v1/health 200: every skill read as
        # "catalog-only (no method body yet)" because the SKILL.md files were
        # not in the bundle. collect_submodules does not collect these.
        for rel, why in (
            ("arslan/spawn/seeds", "factory spawns cannot be seeded"),
            ("arslan/spawn/scaffold", "new skill-packs cannot be scaffolded"),
            ("arslan/config", "the requirement tree is unavailable"),
            ("arslan/templates/official", "official templates are unavailable"),
        ):
            d = root / rel
            if not d.is_dir() or not any(d.rglob("*")):
                asset_errors.append(f"{rel} is missing or empty — {why}")

    if failed or asset_errors:
        print("SELFTEST FAILED:", file=sys.stderr)
        for name, err in failed:
            print(f"  module {name}: {err}", file=sys.stderr)
        for err in asset_errors:
            print(f"  assets: {err}", file=sys.stderr)
        return 1
    print(
        f"SELFTEST OK ({len(required)} modules importable"
        + (", web assets present" if getattr(sys, "frozen", False) else "")
        + ")",
        flush=True,
    )
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

    _die_when_the_shell_does()

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

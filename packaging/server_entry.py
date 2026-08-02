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

    if getattr(sys, "frozen", False):
        # The documented integration hook (server/token_bootstrap.py:12): with
        # this set, _needs_token() is True, so boot mints a token, persists it
        # to <data_dir>/api_token (0o600), and auth is ENFORCED. Without it a
        # packaged app ran as "dev + localhost = unauthenticated", which the
        # spec forbids: 127.0.0.1 is reachable by every process on the machine,
        # and this server holds the user's whole brain plus their BYOK keys.
        os.environ.setdefault("ARSLAN_PACKAGED", "1")

        # An inherited env token would win over the persisted file
        # (token_bootstrap step 1) and NOTHING would be written to disk — but
        # the Tauri shell can only learn the token by reading that file, so
        # the webview would sit unauthenticated against an authenticated API:
        # a broken UI with no error pointing here. Auth stays ON either way;
        # this only forces the one token source the shell can actually see.
        os.environ.pop("ARSLAN_API_TOKEN", None)

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


#: The loopback port the sidecar prefers. FIXED, and that is the whole point.
#:
#: 🔴 This used to be ephemeral, and the docstring below used to reassure the
#: reader that a collision "surfaces immediately as a failed launch rather than
#: as data loss". The ephemeral port WAS the data loss, through a channel that
#: sentence did not consider: the window loads `http://127.0.0.1:<port>`, and
#: WebKit partitions localStorage by ORIGIN — of which the port is part. A new
#: port on every launch meant a new, empty store every launch, and the conversation
#: list lived there and nowhere else. Measured in the user's packaged database:
#: 10 conversations, 74 messages, five distinct thread ids in a single day.
#:
#: Chosen in the IANA dynamic range and away from common dev servers (5173
#: Vite, 3000 Node, 8000/8080 the usual suspects) so a developer's own stack
#: does not routinely push us onto the fallback.
DEFAULT_PORT = 47317


def _free_port() -> int:
    """Ask the OS for an ephemeral free port on the loopback interface.

    Only the FALLBACK now — see `choose_port`. Bound and closed here, then
    re-bound by uvicorn a moment later; that gap is a real (if tiny) race,
    accepted because passing a pre-bound socket through uvicorn costs more than
    it buys for a single-user desktop app.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def choose_port() -> int:
    """DEFAULT_PORT when it is free, otherwise an ephemeral one.

    Falling back rather than refusing to start is deliberate: with the
    server-side conversation listing in place, an occasional different origin
    costs a reset of origin-scoped UI state, while refusing to launch costs the
    user their whole app. The listing is what makes the fallback survivable —
    conversations come back from the server either way.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # 🔴 SO_REUSEADDR because UVICORN SETS IT. A probe that binds more
        # strictly than the server it is probing for reports a usable port as
        # taken — and the port left in TIME_WAIT by the instance that just
        # exited is exactly that case.
        #
        # Shipped without this in v0.1.15 and caught the same day on the user's
        # machine: DEFAULT_PORT free, app on v0.1.15, sidecar still came up
        # ephemeral. A too-LOOSE probe gives a false green, which is the
        # familiar failure; a too-STRICT one gives a false NEGATIVE, and this
        # one fired precisely on RESTART — the one scenario the fixed port
        # exists to protect.
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", DEFAULT_PORT))
        except OSError:
            return _free_port()
        return DEFAULT_PORT


def _lazy_resource_probes():
    """(label, probe, why) for every resource the app resolves LATE.

    Each probe exercises the resource rather than importing its module, because
    the failures this census exists for all look like a healthy import: a name
    that resolves to nothing, a data file that is not beside the code that
    names it, a native library the wrapper loads on first use.
    """
    def certifi_ca():
        import certifi

        path = pathlib.Path(certifi.where())
        return path.is_file() and path.stat().st_size > 0, str(path)

    def sqlite_dialect():
        from sqlalchemy.dialects import registry

        cls = registry.load("sqlite.aiosqlite")
        return cls is not None, getattr(cls, "__name__", "?")

    def pdfium_native():
        # pypdfium2 loads libpdfium through a ctypes module on first use; a
        # staged package with an unstaged .dylib imports fine and raises when a
        # scanned PDF arrives — i.e. only for the user, only sometimes.
        import pypdfium2

        doc = pypdfium2.PdfDocument.new()
        doc.new_page(200, 200)
        n = len(doc)
        doc.close()
        return n == 1, f"rendered a {n}-page document"

    def http_client_tls():
        # httpx picks its SSL context up from certifi at CLIENT CONSTRUCTION,
        # not at import — the [Errno 2] incident was exactly this gap.
        import httpx

        with httpx.Client(timeout=1.0) as client:
            return client is not None, "constructed with a TLS context"

    return [
        ("certifi CA bundle", certifi_ca,
         "the CA file is missing, so every outbound HTTPS call would fail with "
         "[Errno 2] long after a healthy boot"),
        ("sqlite+aiosqlite dialect", sqlite_dialect,
         "SQLAlchemy resolves this by STRING; without it the database is "
         "unreachable although every module imported"),
        ("pypdfium2 native library", pdfium_native,
         "the rasteriser cannot render, so scanned PDFs silently yield nothing"),
        ("httpx TLS client", http_client_tls,
         "no provider call could be made"),
    ]


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
        # uvicorn resolves this BY NAME at serve time and treats its absence as a
        # log line, not an error: every /ws/ upgrade then degrades to plain HTTP,
        # the SPA catch-all answers 200, and the entire chat transport is dead
        # behind a /health that says 200. Builds 0.1.0-0.1.6 all shipped this way.
        "websockets",
        "server.services.ocr_vision",    # tier-2 OCR, macOS Vision bindings
        "server.services.ocr_fallback",
    ]
    failed: list[tuple[str, str]] = []
    for name in required:
        try:
            __import__(name)
        except Exception as exc:  # noqa: BLE001 — report them all, not the first
            failed.append((name, f"{type(exc).__name__}: {exc}"))

    # Importing `websockets` is still not proof that uvicorn will USE it —
    # uvicorn picks an implementation through its own config resolution, so ask
    # uvicorn, not the import system.
    if not failed:
        try:
            from uvicorn.config import Config

            cfg = Config("server.main:app", ws="auto")
            cfg.load()  # ws_protocol_class only exists after load() resolves it
            if cfg.ws_protocol_class is None:
                failed.append((
                    "uvicorn websocket protocol",
                    "ws='auto' resolved to NO implementation — every /ws/ upgrade "
                    "would be served as plain HTTP and the chat transport is dead",
                ))
        except Exception as exc:  # noqa: BLE001 — report, never crash the selftest
            failed.append(("uvicorn websocket protocol", f"{type(exc).__name__}: {exc}"))

    # Same shape again, for the tier-2 OCR engine: importing the bindings does
    # not prove the app can RECOGNISE anything. Ask the module the question the
    # user's file will ask it. The failure this catches is not a crash — it is
    # is_available() answering False in the bundle while answering True in dev,
    # i.e. a capability that exists on the developer's machine and not in the
    # product. That is precisely how the previous OCR path shipped.
    if not failed and sys.platform == "darwin":
        try:
            from server.services import ocr_vision

            if not ocr_vision.is_available():
                failed.append((
                    "macOS Vision (tier-2 OCR)",
                    "the bindings did not load in the frozen build — images and "
                    "scanned PDFs would silently yield no text",
                ))
            elif not ocr_vision.supported_languages():
                failed.append((
                    "macOS Vision languages",
                    "the framework reported an empty language list, so the "
                    "language gate would refuse every image",
                ))
        except Exception as exc:  # noqa: BLE001 — report, never crash the selftest
            failed.append(("macOS Vision (tier-2 OCR)", f"{type(exc).__name__}: {exc}"))

    # ── the lazy-resource census ──────────────────────────────────────────
    # Generalising the websockets outage rather than patching its instance.
    # That dependency was resolved BY NAME at use time, so nothing imported it,
    # PyInstaller could not see it, and its absence was a log line rather than
    # an error. Every entry below is the same shape: something the app reaches
    # for late, whose absence degrades quietly instead of failing loudly.
    #
    # An import is not enough for any of them — each is asked to DO the thing.
    # certifi in particular: the module imports fine while the .pem it points
    # at is absent, and the symptom is every outbound request dying with
    # [Errno 2] long after boot. That happened, on a real user's machine.
    if not failed:
        for label, probe, why in _lazy_resource_probes():
            try:
                ok, detail = probe()
            except Exception as exc:  # noqa: BLE001 — a failed probe is a failure
                ok, detail = False, f"{type(exc).__name__}: {exc}"
            if not ok:
                failed.append((label, f"{why} ({detail})"))

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

    port = int(os.environ.get("ARSLAN_PORT") or choose_port())

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

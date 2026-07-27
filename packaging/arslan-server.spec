# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the bundled `arslan-server` desktop sidecar (S4.3-a).

Adapted from andrewyng/openworker's packaging spec (MIT, Copyright (c) 2024
Andrew Ng). Structure, the onedir rationale and the console=True rule come
from there; the package list, the `server` pathex requirement and the OCR
exclusions are ours.

ONEDIR, not onefile: onefile self-extracts its whole archive to a temp dir on
EVERY launch, which openworker measured at 6-7s of splash against a ~0.5s
real import. The resulting dist/arslan-server/{arslan-server, _internal/}
folder is staged into Tauri's `resources` slot.

console=True ON PURPOSE: a windowed (console=False) build leaves sys.stdout
and sys.stderr as None. packaging/server_entry.py announces its port on
stdout and uvicorn logs startup there, so a windowed build would hang on a
blank window with no way to diagnose it. The Tauri shell is responsible for
not showing a terminal.
"""

import os

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# SPECPATH is injected by PyInstaller: <repo>/packaging. Everything else is
# derived from it so the same spec works from any checkout location.
PACKAGING = SPECPATH  # noqa: F821 — injected by PyInstaller
ROOT = os.path.dirname(PACKAGING)

hiddenimports = []
datas = []
binaries = []

# `server` is NOT in the built wheel (pyproject's hatch wheel target packages
# only `arslan`), so it is importable purely because ROOT is on the path.
# pathex=[ROOT] below is what makes that true inside the frozen app too —
# without it the sidecar dies at `import server.main`.
for pkg in ("server", "arslan", "mcp"):
    hiddenimports += collect_submodules(pkg)

# uvicorn resolves its WebSocket implementation LAZILY BY NAME, so nothing
# above imports `websockets` and PyInstaller cannot see it. Its absence is
# not an error either: uvicorn logs "No supported WebSocket library detected"
# and serves the upgrade as plain HTTP, which the SPA catch-all answers 200 —
# a dead chat transport behind a healthy-looking server. That was the state of
# every build from 0.1.0 to 0.1.6. verify_bundle + selftest now assert it.
hiddenimports += collect_submodules("websockets")
# pypdfium2 loads libpdfium through its _raw ctypes module; collect both so
# the .dylib is staged (and therefore signed by the Mach-O sweep).
hiddenimports += collect_submodules("pypdfium2")
hiddenimports += collect_submodules("pypdfium2_raw")

# collect_submodules finds MODULES. It does not find package DATA, and the
# arslan package is mostly data at runtime: pyproject.toml:112-118 lists five
# kinds loaded via Path(__file__).parent — seed skill-packs, scaffold
# templates, LLM capability profiles, the requirement tree, official
# templates. Without these the app boots, serves /api/v1/health 200, and then
# seeds ZERO of its six factory spawns, because every skill reports
# "catalog-only (no method body yet) — not equippable": the SKILL.md files it
# would read simply are not there. Measured on a real bundle; 67 files were
# missing. Same class as the SPA above — data, not code.
for pkg in ("arslan", "server"):
    datas += collect_data_files(pkg, include_py_files=False)

# The seed skill-packs again, this time WITH their .py files. A skill-pack's
# scripts/ directory is DATA that a skill executes as a subprocess, not code
# this program imports — collect_data_files(include_py_files=False) drops it,
# and collect_submodules does not pick it up either because it is not an
# importable module. pyproject.toml:114 spells out that a seed is "SKILL.md +
# scripts/". Staging the tree wholesale is the only way to get both.
SEEDS = os.path.join(ROOT, "arslan", "spawn", "seeds")
if not os.path.isdir(SEEDS):
    raise SystemExit(f"seed skill-packs missing at {SEEDS} — the app would seed no spawns")
datas += [(SEEDS, "arslan/spawn/seeds")]

# Dynamically-resolved packages that static analysis cannot see:
#   uvicorn      — loads its protocol/lifespan implementations by name
#   sqlalchemy   — resolves the sqlite+aiosqlite dialect through a registry
#   aiosqlite    — only ever reached via that dialect string
#   certifi      — the CA bundle file itself, needed for every TLS call
#   trafilatura  — carries data files for extraction
for pkg in (
    "uvicorn",
    "sqlalchemy",
    "aiosqlite",
    "certifi",
    "anyio",
    "trafilatura",
    "pypdf",
    "docx",
    "pptx",
):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# The built SPA. server/main.py only mounts the SPA fallback when its static
# dir EXISTS, so a bundle without this serves 200s on /api/* and a blank window
# on everything else. build_dmg.sh must run the web build before PyInstaller;
# fail loudly here rather than shipping that.
WEB_DIST = os.path.join(ROOT, "web", "dist")
if not os.path.isdir(os.path.join(WEB_DIST, "assets")):
    raise SystemExit(
        f"web assets missing at {WEB_DIST} — run `npm run build` in web/ first. "
        "Bundling without them produces an app whose window is blank."
    )
datas += [(WEB_DIST, "arslan_web")]

a = Analysis(  # noqa: F821 — injected by PyInstaller
    [os.path.join(PACKAGING, "server_entry.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # OCR is an opt-in extra and must never reach a distributed build:
    #   fitz/pymupdf — AGPL-3.0; shipping it would pull AGPL onto the whole
    #                  app. Listed even though it is no longer a dependency,
    #                  as a regression guard: re-adding it upstream must not
    #                  silently put it back in the .dmg.
    #   pytesseract  — useless without a `tesseract` binary we do not ship.
    # PIL is deliberately NOT excluded. It looks OCR-only — ingest.py:39,61
    # are our only direct imports — but python-pptx (a CORE dependency) imports
    # it internally (pptx/parts/image.py, pptx/text/layout.py), so excluding it
    # makes `import server.services.deck_pptx` raise ModuleNotFoundError and
    # takes the whole PPTX deck feature down in the packaged app. Measured, not
    # assumed: an earlier revision of this spec excluded it and did exactly that.
    # tkinter/matplotlib are dead weight PyInstaller otherwise drags in.
    excludes=[
        "fitz",
        "pymupdf",
        "pytesseract",
        "tkinter",
        "matplotlib",
        "PyQt5",
        "PySide6",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821 — injected by PyInstaller
exe = EXE(  # noqa: F821 — injected by PyInstaller
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="arslan-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # see module docstring — NOT negotiable
)
coll = COLLECT(  # noqa: F821 — injected by PyInstaller
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="arslan-server",
)

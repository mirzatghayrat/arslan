"""What changed in Arslan, from the release notes shipped with the app (D2, 0.1.55).

Before 0.1.55 Arslan answered "what version are you / what's new" from the model's
memory and said an old version. The notes are the same files as `docs/releases/`
(the GitHub release bodies); the packaged sidecar carries them as PyInstaller data
under `server/resources/releases`, a source checkout reads `docs/releases`.
"""
from __future__ import annotations

import re
from pathlib import Path

from server.config import settings

_STABLE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)\.md$")
MAX_CHARS = 2500   # per release; the notes are short, this only bounds a runaway file


def _notes_dir() -> Path:
    server_dir = Path(__file__).resolve().parent.parent
    packaged = server_dir / "resources" / "releases"
    return packaged if packaged.is_dir() else server_dir.parent / "docs" / "releases"


def _key(version: str) -> tuple[int, int, int] | None:
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", version or "")
    return tuple(int(x) for x in m.groups()) if m else None


def recent(count: int = 3, version: str | None = None) -> list[dict]:
    """The notes of this version and the ones before it, newest first. Betas are
    skipped; versions newer than the running one (a source checkout ahead of its
    tag) are never offered as "already shipped"."""
    current = _key(version or settings.app_version)
    found = []
    folder = _notes_dir()
    if not folder.is_dir():
        return []
    for path in folder.iterdir():
        m = _STABLE.match(path.name)
        if not m:
            continue
        key = tuple(int(x) for x in m.groups())
        if current is not None and key > current:
            continue
        found.append((key, path))
    found.sort(reverse=True)
    out = []
    # A pre-release that is running (0.1.59-beta.2) leads with its own notes: other betas stay
    # skipped, but "what's new" in a beta has to name what the beta brought (0.1.59-beta.1's
    # packaged check failed on exactly this).
    running = (version or settings.app_version or "").strip()
    own = folder / f"v{running}.md"
    if "-" in running and not running.endswith("-dev") and own.is_file():
        out.append({"version": running, "notes": own.read_text(errors="replace").strip()[:MAX_CHARS]})
    for key, path in found[:max(1, count) - len(out)]:
        text = path.read_text(errors="replace").strip()
        out.append({"version": "%d.%d.%d" % key, "notes": text[:MAX_CHARS]})
    return out


def about() -> dict:
    return {"version": settings.app_version, "releases": recent()}

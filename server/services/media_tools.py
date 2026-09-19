"""Find optional existing codecs without relying on an interactive shell."""
from __future__ import annotations

import shutil
import sys


def find_media_tool(name: str) -> str | None:
    """Preserve PATH precedence, then check standard macOS package locations.

    Finder-launched apps commonly lack Homebrew directories in PATH. Lookup
    never launches a shell, installs anything, or changes process environment.
    Availability is only executable discovery, not codec/format certification.
    """
    if name not in {"ffmpeg", "ffprobe"}:
        raise ValueError("Unsupported media tool")
    executable = shutil.which(name)
    if executable or sys.platform != "darwin":
        return executable
    return shutil.which(name, path="/opt/homebrew/bin:/usr/local/bin")

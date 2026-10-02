"""Talking to Arslan Hands, the helper app that holds Accessibility (0.1.53).

Hands is a separate app, started through LaunchServices so that it is its own
responsible process: macOS checks Accessibility against the responsible process
and every child inherits it, so the grant must never sit on anything run_command
descends from (measured; docs/specs/2026-10-03-0153-hands-agent-desktop.md §0).

Hands takes no arguments and finds its folder itself, from the account's home
directory (getpwuid, never $HOME: `open --env` could point it elsewhere). This
module derives the same folder the same way. The folder is in the P3 sandbox's
protected paths, files and sockets alike, so a sandboxed command can neither
read the token nor connect.
"""
from __future__ import annotations

import os
import pwd
from pathlib import Path

FOLDER_NAME = "Arslan Hands"


def folder() -> Path:
    """`~/Library/Application Support/Arslan Hands`, from the account database."""
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / "Library" / "Application Support" / FOLDER_NAME

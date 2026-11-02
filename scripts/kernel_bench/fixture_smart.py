"""SMART-5 fixture: what a user's machine already has before the bench asks (synthetic, deterministic).

- `prepare_home(home)`: a tool in `~/.local/bin` that only `~/.zshrc` puts on PATH, as on the user's Mac in the run
  that prompted SMART (card: docs/plans/0164/SMART-feels-smart.md). A login shell (`zsh -l`) reads `~/.zprofile`,
  not `~/.zshrc`, so before SMART-1 Arslan's commands can't find it. No `~/.zprofile` is written.
- `prepare_run(run)`: the run folder's `notes.md`, which makes "add it to my notes" ambiguous with the Notes app.
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOL = "notetool"
TOKEN = "notetool 3.2.1 (bench)"


def prepare_home(home: Path) -> None:
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    tool = bin_dir / TOOL
    tool.write_text(f'#!/bin/sh\necho "{TOKEN}"\n', encoding="utf-8")
    tool.chmod(0o755)
    (home / ".zshrc").write_text('export PATH="$HOME/.local/bin:$PATH"\n', encoding="utf-8")


def prepare_run(run: Path) -> None:
    (run / "notes.md").write_text("# Notes\n\n- 2026-10-30: project kickoff, owners assigned.\n", encoding="utf-8")


if __name__ == "__main__":
    prepare_run(Path(sys.argv[1]))
